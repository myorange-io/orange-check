"""신뢰할 수 없는 문서에서 XML을 안전하게 읽는다 — 표준 라이브러리만.

검증 대상 문서는 남이 준 파일이다. docx·hwpx는 ZIP + XML이므로
악의적인 파일이 두 가지를 노릴 수 있다.

  엔티티 폭탄  <!ENTITY> 중첩 확장으로 메모리를 터뜨린다(billion laughs).
  외부 엔티티  <!ENTITY SYSTEM "file:///etc/passwd"> 로 파일을 새어 나가게 한다(XXE).
  ZIP 폭탄     몇 KB짜리 압축이 수십 GB로 풀린다.

`defusedxml`이 정석이지만 서드파티다. 이 도구는 네트워크도 pip도 없는
ChatGPT 코드 인터프리터에서 그대로 돌아야 하므로 의존성을 둘 수 없다.

대신 두 겹으로 막는다.
  1. defusedxml이 이미 설치돼 있으면 그것을 쓴다.
  2. 없으면 DTD·엔티티 선언이 들어 있는 문서를 아예 거부한다.
     OWPML(hwpx)과 OOXML(docx)은 DTD를 쓰지 않으므로 정상 파일은 걸리지 않는다.
     선언 자체를 막으면 확장 폭탄과 외부 참조가 함께 사라진다.
"""
from __future__ import annotations

import re
import zipfile

MAX_XML_BYTES = 64 * 1024 * 1024        # 부품 하나당 64MB
MAX_TOTAL_BYTES = 512 * 1024 * 1024     # 압축 해제 총량 512MB
MAX_MEMBERS = 5000

_DECL = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.I)

try:  # 있으면 정석대로
    from defusedxml.ElementTree import fromstring as _defused_fromstring
except Exception:  # pragma: no cover
    _defused_fromstring = None


class UnsafeDocument(ValueError):
    """문서가 위험한 구조를 담고 있어 판독을 거부했다."""


def fromstring(data: bytes):
    """XML 바이트를 파싱한다. 위험한 선언이 있으면 거부한다."""
    if len(data) > MAX_XML_BYTES:
        raise UnsafeDocument(f"XML 부품이 너무 크다({len(data)}바이트) — 판독을 거부한다")
    if _defused_fromstring is not None:
        return _defused_fromstring(data)
    head = data[:4096]
    if _DECL.search(head) or _DECL.search(data):
        raise UnsafeDocument(
            "문서에 DTD 또는 엔티티 선언이 있다. 정상적인 docx·hwpx는 이를 쓰지 않으며, "
            "엔티티 확장 공격일 수 있어 판독을 거부한다."
        )
    import xml.etree.ElementTree as ET
    return ET.fromstring(data)


_DOCTYPE = re.compile(rb"<!DOCTYPE\b.*?(?:\[.*?\]\s*)?>", re.S | re.I)
_ENTITY_DECL = re.compile(
    rb"""<!ENTITY\s+([A-Za-z_][\w.\-]*)\s+(['"])(.*?)\2\s*>""", re.S)
# 문자 참조 하나짜리 엔티티만 받아들인다: &#160; / &#xA0;
_CHARREF_ONLY = re.compile(rb"^&#(?:[0-9]{1,7}|x[0-9A-Fa-f]{1,6});$")


def defuse_doctype(data: bytes) -> bytes:
    """DTD를 **처리하지 않고 제거**하되, 문자 참조 엔티티만 미리 치환한다.

    HWPML(.hml)은 `<!ENTITY nbsp "&#160;">` 같은 선언을 정당하게 쓴다. DTD를
    일괄 거부하면 정부 고시·규정 문서를 통째로 못 읽는다. 그렇다고 파서에
    DTD를 넘기면 확장 폭탄이 열린다.

    그래서 파서에는 DTD를 아예 주지 않고, 여기서 직접 처리한다.
      - 값이 문자 참조 하나(`&#160;`)인 엔티티만 받아들여 본문에서 치환한다.
      - 그 외(다른 엔티티 참조를 품거나, SYSTEM/PUBLIC 외부 참조)는 거부한다.
    치환할 값에 다른 엔티티 참조가 없으므로 확장이 재귀할 수 없고,
    외부를 가리킬 수도 없다.
    """
    m = _DOCTYPE.search(data[:MAX_XML_BYTES])
    if not m:
        return data
    doctype = m.group(0)
    if re.search(rb"\b(SYSTEM|PUBLIC)\b", doctype, re.I):
        raise UnsafeDocument("문서의 DTD가 외부 자원을 가리킨다 — 판독을 거부한다")
    subs: dict[bytes, bytes] = {}
    for name, _q, value in _ENTITY_DECL.findall(doctype):
        if not _CHARREF_ONLY.match(value.strip()):
            raise UnsafeDocument(
                f"엔티티 '{name.decode()}'의 값이 단순 문자 참조가 아니다 — 판독을 거부한다")
        subs[b"&" + name + b";"] = value.strip()
    body = data[:m.start()] + data[m.end():]
    for k, v in subs.items():
        body = body.replace(k, v)
    return body


def open_zip(path: str) -> zipfile.ZipFile:
    """ZIP을 열되, 압축 해제 폭탄과 경로 탈출을 먼저 걸러낸다."""
    z = zipfile.ZipFile(path)
    infos = z.infolist()
    if len(infos) > MAX_MEMBERS:
        z.close()
        raise UnsafeDocument(f"ZIP 안 파일이 너무 많다({len(infos)}개)")
    total = 0
    for i in infos:
        name = i.filename.replace("\\", "/")
        if name.startswith("/") or ".." in name.split("/"):
            z.close()
            raise UnsafeDocument(f"ZIP 안에 경로를 벗어나는 항목이 있다: {i.filename}")
        total += i.file_size
        if i.compress_size and i.file_size / max(i.compress_size, 1) > 1000 and i.file_size > 8 << 20:
            z.close()
            raise UnsafeDocument(f"압축률이 비정상이다: {i.filename}")
    if total > MAX_TOTAL_BYTES:
        z.close()
        raise UnsafeDocument(f"압축을 풀면 {total}바이트가 된다 — 판독을 거부한다")
    return z


def strip_tags(xml_bytes: bytes) -> str:
    """XML에서 태그만 걷어낸 평문. 구조가 깨진 부품의 최후 수단."""
    import html
    if _DECL.search(xml_bytes):
        raise UnsafeDocument("DTD/엔티티 선언이 있는 XML은 평문 추출도 거부한다")
    txt = re.sub(rb"<[^>]+>", b" ", xml_bytes).decode("utf-8", "ignore")
    return html.unescape(re.sub(r"\s+", " ", txt)).strip()
