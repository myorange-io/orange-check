#!/usr/bin/env python3
"""벤치마크 빌더 — 사양(spec) + 산문(prose) → 코퍼스 PDF · 벤치마크 docx · 정답표.

이 스크립트가 Layer 0(심판의 심판)의 전부다. 원칙:

  1. 정답은 심어서 만든다. 사양이 유일한 진실이고, 나머지는 전부 여기서 파생된다.
  2. 파생 과정은 자기검증한다. 사실 문장이 PDF에 없거나, 두 번 나오거나,
     금지어가 새어 나오거나, 주장 문장이 문서에 없으면 빌드를 실패시킨다.
     정답표는 "빌드가 성공했다"는 사실만으로 신뢰할 수 있어야 한다.

실행: python3 benchmark/build.py [--bench bench-01]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import unicodedata
import zipfile
from html import escape
from pathlib import Path

import fitz  # PyMuPDF

ROOT = Path(__file__).resolve().parent
PAGE_W, PAGE_H = 595.0, 842.0
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 62.0, 64.0, 62.0
LINE_H = 15.6
FS_BODY = 10.5
FS_HEAD = 12.5
FS_TITLE = 15.0
FS_MARK = 7.6
FONT_KR = "korea"
FONT_EN = "helv"

FAILURES: list[str] = []


def fail(msg: str) -> None:
    FAILURES.append(msg)
    print(f"  ✗ {msg}", file=sys.stderr)


def norm(s: str) -> str:
    """공백을 전부 제거해 줄바꿈 위치와 무관하게 문자열을 비교한다."""
    s = unicodedata.normalize("NFC", s)
    return re.sub(r"\s+", "", s)


# ────────────────────────────────────────────────────────────── PDF 렌더링

def wrap(text: str, font: str, size: float, max_w: float) -> list[str]:
    """한글(공백 없이 이어짐)과 영문(단어 단위)을 모두 처리하는 탐욕적 줄바꿈."""
    out: list[str] = []
    line = ""
    i = 0
    while i < len(text):
        ch = text[i]
        trial = line + ch
        if fitz.get_text_length(trial, fontname=font, fontsize=size) > max_w and line:
            # 영문 단어 중간이면 마지막 공백까지 되감는다.
            if ch.isalnum() and ch.isascii() and " " in line.rstrip():
                cut = line.rstrip().rfind(" ")
                if cut > len(line) * 0.4:
                    out.append(line[:cut])
                    line = line[cut + 1:] + ch
                    i += 1
                    continue
            out.append(line)
            line = ch
        else:
            line = trial
        i += 1
    if line:
        out.append(line)
    return out


class PdfWriter:
    """한 줄씩 고정 위치에 찍고, 찍은 줄 번호를 그대로 기록한다.

    추출 순서(page.get_text())가 삽입 순서와 일치함을 build 마지막에 재확인한다.
    """

    def __init__(self, watermark: str, body_font: str) -> None:
        self.doc = fitz.open()
        self.wm = watermark
        self.font = body_font
        self.page = None
        self.y = 0.0
        self.lineno = 0
        self.pageno = 0
        # (pageno, lineno) -> 텍스트, 그리고 페이지별 평문
        self.page_lines: dict[int, list[str]] = {}
        self._new_page()

    def _new_page(self) -> None:
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.pageno += 1
        self.lineno = 0
        self.page_lines[self.pageno] = []
        self.y = MARGIN_TOP
        self._raw(self.wm, FONT_KR, 7.2, color=(0.45, 0.45, 0.45))
        self.y += 6.0

    def _raw(self, text: str, font: str, size: float, color=(0, 0, 0)) -> int:
        self.page.insert_text((MARGIN_X, self.y), text, fontname=font, fontsize=size, color=color)
        self.lineno += 1
        self.page_lines[self.pageno].append(text)
        self.y += LINE_H
        return self.lineno

    def _ensure(self, need: float = LINE_H) -> None:
        if self.y + need > PAGE_H - MARGIN_BOTTOM:
            self._new_page()

    def block(self, text: str, size: float = FS_BODY, indent: bool = True) -> list[tuple[int, int]]:
        """문단을 쓰고 [(page, line), ...] 좌표 목록을 돌려준다."""
        width = PAGE_W - 2 * MARGIN_X
        body = ("  " + text) if indent else text
        coords = []
        for ln in wrap(body, self.font, size, width):
            self._ensure()
            coords.append((self.pageno, self._raw(ln, self.font, size)))
        self.y += 3.4
        return coords

    def heading(self, text: str) -> None:
        self._ensure(LINE_H * 2)
        self.y += 6.0
        self._ensure()
        self._raw(text, self.font, FS_HEAD)
        self.y += 2.6

    def title(self, text: str, subtitle: str = "") -> None:
        self._raw(text, self.font, FS_TITLE)
        if subtitle:
            self._raw(subtitle, self.font, FS_BODY, color=(0.3, 0.3, 0.3))
        self.y += 10.0

    def table(self, caption: str, rows: list[list[str]]) -> None:
        """표를 칸 맞춘 텍스트 줄로 그린다.

        실제 보고서는 통계를 표에 담는다. 산문만으로 만든 코퍼스는 그 상황을
        시험하지 못한다. PDF에서 표는 결국 줄 단위 텍스트로 추출되므로,
        여기서도 줄로 그리되 칸을 공백으로 맞춘다. 대조는 공백을 지우고 하므로
        사양에는 `"산업 부문 2,318 2,241"`처럼 칸을 한 칸씩 띄워 적으면 된다.
        """
        widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
        self._ensure(LINE_H * (len(rows) + 3))
        self.y += 4.0
        if caption:
            self._ensure()
            self._raw(caption, self.font, FS_BODY)
        for idx, row in enumerate(rows):
            cells = [str(c).ljust(widths[i] + 2) for i, c in enumerate(row)]
            self._ensure()
            self._raw("  " + "".join(cells).rstrip(), self.font, FS_BODY)
            if idx == 0:
                self._ensure()
                # 구분선은 ASCII로 긋는다. U+2500은 영문 폰트가 그리지 못해
                # 그 줄이 통째로 사라지고, 삽입 줄 수와 추출 줄 수가 어긋난다.
                self._raw("  " + "-" * min(60, sum(widths) + 2 * len(widths)),
                          self.font, FS_BODY, color=(0.4, 0.4, 0.4))
        self.y += 5.0

    def save(self, path: Path) -> None:
        # 같은 사양에서 같은 바이트가 나와야 한다. 그러지 않으면 게이트를 돌릴
        # 때마다 코퍼스가 바뀐 것으로 잡혀 진짜 변경을 가린다.
        # PDF는 기본으로 생성 시각과 무작위 ID를 넣으므로 둘 다 고정한다.
        self.doc.set_metadata({
            "producer": "orange-check benchmark builder",
            "creator": "orange-check", "title": "", "author": "",
            "subject": "", "keywords": "",
            "creationDate": "D:20260101000000Z", "modDate": "D:20260101000000Z",
        })
        self.doc.save(str(path), garbage=3, deflate=True, no_new_id=True)


def build_source_pdf(src: dict, prose: dict, watermark: str, out: Path) -> dict:
    font = FONT_EN if src.get("language") == "en" else FONT_KR
    w = PdfWriter(watermark, font)
    m = src["meta"]
    sub = " · ".join(x for x in [m.get("publisher"), m.get("series"), m.get("date")] if x)
    w.title(m["title"], sub)
    tables = {t["section"]: t for t in (src.get("tables") or [])}
    for sec in prose["sections"]:
        w.heading(sec["heading"])
        for para in sec["paragraphs"]:
            w.block(para)
        t = tables.pop(sec["heading"], None)
        if t:
            w.table(t.get("caption", ""), t["rows"])
    for t in tables.values():
        fail(f"{src['id']}: 표를 붙일 절 '{t['section']}'이 산문에 없다")
    w.save(out)

    # 재추출로 삽입 순서 == 추출 순서 확인
    doc = fitz.open(str(out))
    pages: dict[int, list[str]] = {}
    for i in range(doc.page_count):
        lines = [l for l in doc[i].get_text().split("\n")]
        while lines and not lines[-1].strip():
            lines.pop()
        pages[i + 1] = lines
    for pno, expected in w.page_lines.items():
        got = pages.get(pno, [])
        if [x for x in got] != [x for x in expected]:
            fail(f"{src['id']}: p{pno} 렌더링 순서 불일치 (삽입 {len(expected)}줄 / 추출 {len(got)}줄)")
            break
    return pages


def flat_index(pages: dict[int, list[str]]) -> tuple[str, list[tuple[int, int]]]:
    """문서 전체를 공백 없는 한 줄로 잇고, 각 문자의 (page, line)을 기록한다.

    각 페이지 1행은 워터마크이므로 색인에서 제외한다. 그러지 않으면
    페이지를 넘나드는 문장 한가운데 워터마크가 끼어들어 매칭이 끊긴다.
    행 번호는 워터마크를 포함한 실제 번호를 그대로 쓴다 — PDF를 열어 센 값과 같아야 한다.
    """
    flat: list[str] = []
    idx: list[tuple[int, int]] = []
    for pno in sorted(pages):
        for lineno, line in enumerate(pages[pno], 1):
            if lineno == 1:  # 워터마크
                continue
            for ch in norm(line):
                flat.append(ch)
                idx.append((pno, lineno))
    return "".join(flat), idx


def locate(pages: dict[int, list[str]], sentence: str) -> list[dict]:
    """문장이 등장하는 위치 목록. 공백 무시 매칭, 페이지 경계를 넘어도 찾는다."""
    flat, idx = flat_index(pages)
    target = norm(sentence)
    hits = []
    start = flat.find(target)
    while start != -1:
        p0, l0 = idx[start]
        p1, l1 = idx[start + len(target) - 1]
        hits.append({"page": p0, "line_start": l0, "page_end": p1, "line_end": l1})
        start = flat.find(target, start + 1)
    return hits


def count_occurrences(pages: dict[int, list[str]], needle: str) -> int:
    flat, _ = flat_index(pages)
    return flat.count(norm(needle))


# ────────────────────────────────────────────────────────────── docx 작성

NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)


def run(text: str, *, sup: bool = False, bold: bool = False, size: int | None = None) -> str:
    props = ""
    if bold:
        props += "<w:b/>"
    if size:
        props += f'<w:sz w:val="{size}"/>'
    if sup:
        props += '<w:vertAlign w:val="superscript"/>'
    rpr = f"<w:rPr>{props}</w:rPr>" if props else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def note_ref(kind: str, nid: int) -> str:
    tag = "footnoteReference" if kind == "footnote" else "endnoteReference"
    return (
        f'<w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr>'
        f'<w:{tag} w:id="{nid}"/></w:r>'
    )


def para(inner: str, style: str = "") -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}{inner}</w:p>"


def format_ref(meta: dict) -> str:
    bits = [meta.get("authors", ""), f"({meta.get('year','')})", meta.get("title", "")]
    for k in ("journal", "volume", "issue", "pages", "series", "publisher", "date"):
        v = meta.get(k)
        if not v:
            continue
        if k == "volume":
            bits.append(f"제{v}권")
        elif k == "issue":
            bits.append(f"제{v}호")
        elif k == "pages":
            bits.append(f"pp.{v}")
        else:
            bits.append(str(v))
    return ", ".join(b for b in bits if b).replace(", (", " (")


def inline_marker(meta: dict) -> str:
    return f"({meta.get('authors','')}, {meta.get('year','')})"


def build_docx(spec: dict, doc_prose: dict, out: Path) -> dict:
    """OOXML을 직접 조립한다. python-docx는 각주/미주를 쓰지 못하기 때문."""
    src_by_id = {s["id"]: s for s in spec["sources"]}
    cit_by_id = {c["id"]: c for c in spec["citations"]}

    def cited_meta(c: dict) -> dict:
        if c.get("fabricated_source"):
            return dict(c["fabricated_source"])
        m = dict(src_by_id[c["cites"]]["meta"])
        m.update(c.get("cited_meta_override") or {})
        return m

    body: list[str] = []
    footnotes: list[tuple[int, str]] = []
    endnotes: list[tuple[int, str]] = []
    fn_id, en_id = 1, 1
    note_map: dict[str, tuple[str, int]] = {}
    placed: set[str] = set()

    body.append(para(run(spec["document"]["title"], bold=True, size=32)))
    body.append(para(run(f"{spec['document']['author']} · {spec['document']['date']}", size=20)))

    for sec in doc_prose["sections"]:
        body.append(para(run(sec["heading"], bold=True, size=26)))
        for blk in sec["blocks"]:
            text = blk["text"]
            runs: list[str] = []
            cursor = 0
            for cid in blk.get("citation_ids", []):
                c = cit_by_id.get(cid)
                if c is None:
                    fail(f"문서 산문이 알 수 없는 인용 id를 참조: {cid}")
                    continue
                pos = text.find(c["claim"], cursor)
                if pos == -1:
                    continue  # 검증 단계에서 별도로 잡는다
                end = pos + len(c["claim"])
                runs.append(run(text[cursor:end]))
                meta = cited_meta(c)
                if c["placement"] == "body":
                    runs.append(run(inline_marker(meta)))
                elif c["placement"] == "footnote":
                    runs.append(note_ref("footnote", fn_id))
                    footnotes.append((fn_id, format_ref(meta)))
                    note_map[cid] = ("footnote", fn_id)
                    fn_id += 1
                else:
                    runs.append(note_ref("endnote", en_id))
                    endnotes.append((en_id, format_ref(meta)))
                    note_map[cid] = ("endnote", en_id)
                    en_id += 1
                placed.add(cid)
                cursor = end
            runs.append(run(text[cursor:]))
            body.append(para("".join(runs)))

    # 참고문헌 — 본문 인용 출처만(각주·미주 출처는 노트에만 존재해 전수 추출을 시험한다)
    body.append(para(run("참고문헌", bold=True, size=26)))
    rels: list[str] = []
    rid = 100
    seen: set[str] = set()
    for c in spec["citations"]:
        if c["placement"] != "body":
            continue
        meta = cited_meta(c)
        key = format_ref(meta)
        if key in seen:
            continue
        seen.add(key)
        url = meta.get("url")
        if url:
            rid += 1
            rels.append(
                f'<Relationship Id="rId{rid}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
                f'Target="{escape(url)}" TargetMode="External"/>'
            )
            link = f'<w:hyperlink r:id="rId{rid}">{run(url)}</w:hyperlink>'
            body.append(para(run(f"· {key} ") + link))
        else:
            body.append(para(run(f"· {key}")))

    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<w:document {NS}><w:body>{''.join(body)}"
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>'
        "</w:body></w:document>"
    )

    def notes_xml(kind: str, items: list[tuple[int, str]]) -> str:
        root = "footnotes" if kind == "footnote" else "endnotes"
        el = "footnote" if kind == "footnote" else "endnote"
        seps = (
            f'<w:{el} w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:{el}>'
            f'<w:{el} w:type="continuationSeparator" w:id="0"><w:p><w:r><w:continuationSeparator/></w:r></w:p></w:{el}>'
        )
        parts = "".join(f'<w:{el} w:id="{i}">{para(run(t))}</w:{el}>' for i, t in items)
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f"<w:{root} {NS}>{seps}{parts}</w:{root}>"
        )

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/footnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/>'
        '<Override PartName="/word/endnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml"/>'
        '<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    doc_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes" Target="footnotes.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes" Target="endnotes.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>'
        + "".join(rels) +
        "</Relationships>"
    )
    settings = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:settings {NS}><w:footnotePr><w:footnote w:id="-1"/><w:footnote w:id="0"/></w:footnotePr>'
        '<w:endnotePr><w:endnote w:id="-1"/><w:endnote w:id="0"/></w:endnotePr></w:settings>'
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    # zip은 항목마다 현재 시각을 넣는다. 고정하지 않으면 같은 사양에서
    # 매번 다른 바이트가 나와 회귀 게이트가 변경으로 잡는다.
    stamp = (2026, 1, 1, 0, 0, 0)

    def put(z, name, data):
        info = zipfile.ZipInfo(name, date_time=stamp)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o600 << 16
        z.writestr(info, data)

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        put(z, "[Content_Types].xml", content_types)
        put(z, "_rels/.rels", root_rels)
        put(z, "word/document.xml", document)
        put(z, "word/_rels/document.xml.rels", doc_rels)
        put(z, "word/footnotes.xml", notes_xml("footnote", footnotes))
        put(z, "word/endnotes.xml", notes_xml("endnote", endnotes))
        put(z, "word/settings.xml", settings)

    missing = [c["id"] for c in spec["citations"] if c["id"] not in placed]
    for cid in missing:
        fail(f"주장 문장이 문서에 배치되지 않음: {cid}")
    return note_map


HWPX_NS = ('xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
           'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"')


def build_hwpx(spec: dict, doc_prose: dict, out: Path) -> dict:
    """벤치마크 문서를 HWPX(ZIP+OWPML)로 쓴다.

    한글 문서를 검증하겠다면서 벤치마크 문서가 docx뿐이면, HWPX 판독 경로는
    합성 픽스처로만 시험된다. 실제 문서를 만들어 왕복시킨다.
    """
    src_by_id = {s["id"]: s for s in spec["sources"]}
    cit_by_id = {c["id"]: c for c in spec["citations"]}

    def cited_meta(c: dict) -> dict:
        if c.get("fabricated_source"):
            return dict(c["fabricated_source"])
        m = dict(src_by_id[c["cites"]]["meta"])
        m.update(c.get("cited_meta_override") or {})
        return m

    def t(text: str) -> str:
        return f"<hp:run><hp:t>{escape(text)}</hp:t></hp:run>"

    body: list[str] = []
    note_map: dict[str, tuple[str, int]] = {}
    placed: set[str] = set()
    fn_id = en_id = 1

    body.append(f"<hp:p>{t(spec['document']['title'])}</hp:p>")
    body.append(f"<hp:p>{t(spec['document']['author'] + ' · ' + spec['document']['date'])}</hp:p>")

    for sec in doc_prose["sections"]:
        body.append(f"<hp:p>{t(sec['heading'])}</hp:p>")
        for blk in sec["blocks"]:
            text, runs, cursor = blk["text"], [], 0
            for cid in blk.get("citation_ids", []):
                c = cit_by_id.get(cid)
                if c is None:
                    fail(f"문서 산문이 알 수 없는 인용 id를 참조: {cid}")
                    continue
                pos = text.find(c["claim"], cursor)
                if pos == -1:
                    continue
                end = pos + len(c["claim"])
                runs.append(t(text[cursor:end]))
                meta = cited_meta(c)
                if c["placement"] == "body":
                    runs.append(t(inline_marker(meta)))
                else:
                    kind = "footNote" if c["placement"] == "footnote" else "endNote"
                    nid = fn_id if c["placement"] == "footnote" else en_id
                    runs.append(
                        f'<hp:run><hp:{kind} number="{nid}"><hp:subList>'
                        f"<hp:p>{t(format_ref(meta))}</hp:p>"
                        f"</hp:subList></hp:{kind}></hp:run>")
                    note_map[cid] = (c["placement"], nid)
                    if c["placement"] == "footnote":
                        fn_id += 1
                    else:
                        en_id += 1
                placed.add(cid)
                cursor = end
            runs.append(t(text[cursor:]))
            body.append("<hp:p>" + "".join(runs) + "</hp:p>")

    body.append(f"<hp:p>{t('참고문헌')}</hp:p>")
    seen: set[str] = set()
    for c in spec["citations"]:
        if c["placement"] != "body":
            continue
        meta = cited_meta(c)
        ref = format_ref(meta)
        if ref in seen:
            continue
        seen.add(ref)
        url = meta.get("url")
        body.append(f"<hp:p>{t('· ' + ref + (' ' + url if url else ''))}</hp:p>")

    section = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               f'<hs:sec {HWPX_NS}>' + "".join(body) + "</hs:sec>")

    out.parent.mkdir(parents=True, exist_ok=True)
    stamp = (2026, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        def put(name: str, data: str) -> None:
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
        put("mimetype", "application/hwp+zip")
        put("META-INF/container.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<container xmlns="urn:hancom:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="Contents/content.hpf"/></rootfiles></container>')
        put("Contents/content.hpf",
            '<?xml version="1.0" encoding="UTF-8"?><opf:package '
            'xmlns:opf="http://www.idpf.org/2007/opf/"><opf:spine>'
            '<opf:itemref idref="section0"/></opf:spine></opf:package>')
        put("Contents/header.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" version="1.31"/>')
        put("Contents/section0.xml", section)

    missing = [c["id"] for c in spec["citations"] if c["id"] not in placed]
    for cid in missing:
        fail(f"주장 문장이 문서에 배치되지 않음: {cid}")
    return note_map


def hwpx_text(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as z:
        raw = z.read("Contents/section0.xml").decode("utf-8")
    return {"Contents/section0.xml": re.sub(r"<[^>]+>", "", raw)}


def docx_text(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as z:
        parts = {}
        for name in ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml"):
            try:
                raw = z.read(name).decode("utf-8")
            except KeyError:
                raw = ""
            txt = re.sub(r"<[^>]+>", "", raw)
            parts[name] = txt
    return parts


# ─────────────────────────────────────────────────────────── 반칙 방지 점검

def overlap_score(claim: str, evidence: str) -> int:
    """주장과 근거 문장의 최장 공통 연속 부분열 길이(숫자·문장부호 제외).

    값이 크면 본문이 출처를 그대로 베낀 것이므로, 문자열 일치만으로
    정답을 맞힐 수 있는 반칙 경로가 생긴다.
    """
    a = re.sub(r"[\d\s.,%()~·\-–—:;]", "", unicodedata.normalize("NFC", claim))
    b = re.sub(r"[\d\s.,%()~·\-–—:;]", "", unicodedata.normalize("NFC", evidence))
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


# ─────────────────────────────────────────────────────────────────── main

def _is_control(c: dict) -> bool:
    """정답이 무결한 인용 — 여기를 지적하면 오탐이다."""
    e = c["expected"]
    return (e["stage1"] == "PASS" and e["stage2"] == "SUPPORTED"
            and not e.get("tier_violation"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", default="bench-01")
    ap.add_argument("--overlap-limit", type=int, default=14,
                    help="주장·근거 최장 공통 연속 부분열 허용 상한(자)")
    args = ap.parse_args()

    spec = json.loads((ROOT / "spec" / f"{args.bench}.spec.json").read_text(encoding="utf-8"))
    prose_dir = ROOT / "spec" / "prose"
    watermark = spec["world"]["watermark"]

    suffix = "" if args.bench == "bench-01" else f".{args.bench}"
    corpus_dir = ROOT / f"corpus{suffix}"
    if corpus_dir.exists():
        shutil.rmtree(corpus_dir)
    corpus_dir.mkdir(parents=True)

    print("── 코퍼스 PDF 렌더링")
    fact_loc: dict[str, dict] = {}
    manifest = {"world": spec["world"]["name"], "closed_world_rule": spec["closed_world_rule"], "sources": []}
    page_cache: dict[str, dict[int, list[str]]] = {}

    for src in spec["sources"]:
        pf = prose_dir / f"{src['id']}.json"
        if not pf.exists():
            fail(f"{src['id']}: 산문 파일 없음 ({pf})")
            continue
        prose = json.loads(pf.read_text(encoding="utf-8"))
        pdf_path = corpus_dir / f"{src['id']}.pdf"
        pages = build_source_pdf(src, prose, watermark, pdf_path)
        page_cache[src["id"]] = pages

        for f in src["facts"]:
            hits = locate(pages, f["sentence"])
            if len(hits) != 1:
                fail(f"{src['id']}/{f['fid']}: 사실 문장이 {len(hits)}회 등장(1회여야 함)")
                continue
            fact_loc[f["fid"]] = {
                "source_id": src["id"], "file": f"{src['id']}.pdf",
                **hits[0], "sentence": f["sentence"],
            }
        for bad in src.get("must_not_contain", []):
            n = count_occurrences(pages, bad)
            if n:
                fail(f"{src['id']}: 금지어 '{bad}'가 {n}회 누출됨")

        manifest["sources"].append({
            "id": src["id"], "file": f"{src['id']}.pdf", "tier": src["tier"],
            "kind": src["kind"], "pages": len(pages), **{"meta": src["meta"]},
        })
        print(f"  {src['id']}  {len(pages)}p  facts={len(src['facts'])}  {pdf_path.name}")

    (corpus_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("── 벤치마크 문서 조립")
    doc_prose = json.loads((prose_dir / f"{args.bench}.doc.json").read_text(encoding="utf-8"))
    fmt = (spec["document"].get("format") or "docx").lower()
    doc_path = ROOT / "docs" / f"{args.bench}.{fmt}"
    if fmt == "hwpx":
        note_map = build_hwpx(spec, doc_prose, doc_path)
        parts = hwpx_text(doc_path)
    else:
        note_map = build_docx(spec, doc_prose, doc_path)
        parts = docx_text(doc_path)
    print(f"  형식 {fmt} → {doc_path.name}")
    whole = norm("".join(parts.values()))
    for c in spec["citations"]:
        n = whole.count(norm(c["claim"]))
        if n != 1:
            fail(f"{c['id']}: 주장 문장이 문서에 {n}회 등장(1회여야 함)")

    print("── 정답이 규칙표에서 도출되는지 확인")
    # 정답표가 스킬이 따르는 규칙표와 어긋나면 벤치마크가 불공정해진다.
    # 규칙대로 답한 리포트가 오답 처리되기 때문이다. 같은 함수로 검사한다.
    import sys as _sys
    _sys.path.insert(0, str(ROOT.parent / "core" / "toolkit"))
    try:
        from refver.judge import derive_verdict
    except ImportError:
        print("  · refver를 불러올 수 없어 건너뜀")
    else:
        checked = 0
        for c in spec["citations"]:
            exp = c["expected"]
            if exp["stage2"] in ("NOT_APPLICABLE", "INSUFFICIENT_EVIDENCE"):
                continue
            wrong = c.get("multi_slots") or (
                [exp["corrupted_slot"]] if exp.get("corrupted_slot") else [])
            if exp["pattern"] == "unsupported" and not wrong:
                wrong = ["what"]
            slots = {k: {"match": k not in wrong}
                     for k in ("who", "when", "what", "value", "dataset", "relation")}
            d = derive_verdict(slots, has_evidence=bool(c.get("evidence_fid")))
            checked += 1
            if d[0] != exp["stage2"]:
                fail(f"{c['id']}: 규칙표대로면 {d[0]}인데 정답표는 {exp['stage2']}다")
            elif d[1] != exp["pattern"] and exp["pattern"] not in (
                    "none", "biblio_mismatch", "tier_violation"):
                fail(f"{c['id']}: 규칙표대로면 유형이 {d[1]}인데 정답표는 {exp['pattern']}다")
        print(f"  {checked}건 확인")

    print("── 근거가 그 주장의 근거가 맞는지 확인")
    # 사실이 코퍼스에 있다는 것만으로는 부족하다. 그 사실이 **그 주장의** 근거여야 한다.
    # 표가 있는 출처에서 인용마다 다른 행을 가리키는데 사실을 하나만 두면,
    # 엉뚱한 행이 근거로 달려도 빌드는 통과한다.
    num_re = re.compile(r"\d[\d,]*\.?\d*")
    year_re = re.compile(r"^(?:19|20)\d{2}$")

    def values(text: str) -> set:
        """연도는 뺀다 — 어느 문장에나 있어서 우연히 겹치고, 그러면 검사가 무력해진다."""
        return {x for x in num_re.findall(text) if not year_re.match(x) and len(x) >= 2}

    checked = 0
    for c in spec["citations"]:
        fid = c.get("evidence_fid")
        if not fid or fid not in fact_loc:
            continue
        corrupted = set(c.get("multi_slots") or
                        ([c["expected"]["corrupted_slot"]] if c["expected"].get("corrupted_slot") else []))
        if "value" in corrupted:
            continue  # 수치를 일부러 틀린 인용은 근거와 숫자가 달라야 정상이다
        want = values(c["claim"])
        have = values(fact_loc[fid]["sentence"])
        missing = want - have
        checked += 1
        if want and missing and not (want & have):
            fail(f"{c['id']}: 주장의 수치 {sorted(missing)}가 근거({fid})에 하나도 없다 "
                 f"— 다른 행·다른 문장을 가리키고 있을 수 있다")
    print(f"  {checked}건 확인")

    print("── 부재 증거가 정말 부재인지 확인")
    for c in spec["citations"]:
        terms = c.get("absence_evidence") or []
        if not terms:
            continue
        sid = c.get("cites")
        pages = page_cache.get(sid)
        if not pages:
            continue
        for t in terms:
            n = count_occurrences(pages, t)
            if n:
                fail(f"{c['id']}: 부재 증거 '{t}'가 {sid}에 {n}회 나온다 — 부재가 아니다")

    print("── 반칙 방지 점검(주장·근거 문자열 겹침)")
    worst = []
    for c in spec["citations"]:
        fid = c.get("evidence_fid")
        if not fid or fid not in fact_loc:
            continue
        ov = overlap_score(c["claim"], fact_loc[fid]["sentence"])
        worst.append((ov, c["id"]))
        if ov > args.overlap_limit:
            fail(f"{c['id']}: 주장이 출처 문장과 {ov}자 연속 일치 — 패러프레이즈 필요(상한 {args.overlap_limit})")
    worst.sort(reverse=True)
    print("  최대 겹침:", ", ".join(f"{cid}={ov}" for ov, cid in worst[:5]))

    print("── 정답표 생성")
    key = {
        "bench_id": spec["bench_id"],
        "spec_version": spec["spec_version"],
        "document": f"docs/{args.bench}.{fmt}",
        "corpus": f"corpus{suffix}/",
        "watermark": watermark,
        "closed_world_rule": spec["closed_world_rule"],
        "planted_taxonomy": spec["planted_taxonomy"],
        "totals": {},
        "citations": [],
    }
    src_by_id = {s["id"]: s for s in spec["sources"]}
    for c in spec["citations"]:
        meta = dict(c["fabricated_source"]) if c.get("fabricated_source") else dict(src_by_id[c["cites"]]["meta"])
        if c.get("cited_meta_override"):
            meta.update(c["cited_meta_override"])
        ev = fact_loc.get(c.get("evidence_fid") or "")
        entry = {
            "id": c["id"],
            "anchor": norm(c["claim"]),
            "claim": c["claim"],
            "placement": c["placement"],
            "note": note_map.get(c["id"]),
            "cited_as": meta,
            "true_source_id": c.get("cites"),
            "planted": c["planted"],
            "slots": c["slots"],
            "expected": c["expected"],
            "evidence": ev,
            "mismatch_fields": c.get("mismatch_fields", []),
            "absence_evidence": c.get("absence_evidence", []),
            "rationale": c.get("rationale", ""),
        }
        key["citations"].append(entry)

    from collections import Counter

    key["totals"] = {
        "citations": len(spec["citations"]),
        # 대조군은 라벨이 아니라 정답이 무결한지로 센다 — 채점기와 같은 기준
        "planted": sum(1 for c in spec["citations"] if not _is_control(c)),
        "control": sum(1 for c in spec["citations"] if _is_control(c)),
        "by_pattern": dict(Counter(c["planted"] for c in spec["citations"])),
        "by_placement": dict(Counter(c["placement"] for c in spec["citations"])),
    }
    (ROOT / f"answer-key{suffix}.json").write_text(
        json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    if FAILURES:
        print(f"빌드 실패 — {len(FAILURES)}건의 위반. 정답표를 신뢰할 수 없다.", file=sys.stderr)
        return 1
    print(f"빌드 성공: 인용 {key['totals']['citations']}건 "
          f"(심은 오류 {key['totals']['planted']} / 대조군 {key['totals']['control']})")
    print(f"  코퍼스 {len(manifest['sources'])}종 → {corpus_dir}")
    print(f"  문서 → {doc_path}")
    print(f"  정답표 → {ROOT / f'answer-key{suffix}.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
