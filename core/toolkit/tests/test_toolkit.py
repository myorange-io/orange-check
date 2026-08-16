#!/usr/bin/env python3
"""refver 도구상자 시험. 표준 라이브러리만으로 돌아간다(pytest 불필요).

실행: PYTHONPATH=core/toolkit python3 core/toolkit/tests/test_toolkit.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from refver import report as R           # noqa: E402
from refver.doc import read_docx, read_document, summarize  # noqa: E402
from refver.hwp import read_hwpx         # noqa: E402
from refver.safexml import UnsafeDocument, fromstring, open_zip  # noqa: E402

FAILS: list[str] = []


def check(cond, msg):
    print(("  ✓ " if cond else "  ✗ ") + msg)
    if not cond:
        FAILS.append(msg)


def raises(exc, fn, *a, **kw) -> bool:
    """막아야 할 입력을 정말 막는가. 조용히 통과하는 것이 가장 나쁘다."""
    try:
        fn(*a, **kw)
    except exc:
        return True
    except Exception:
        return False
    return False


# ────────────────────────────────────────────────────────── HWPX 픽스처

HWPX_SECTION = """<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"
        xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">
  <hp:p><hp:run><hp:t>2024년 한부모가족의 월평균 가구소득은 268.5만원이었다.</hp:t></hp:run></hp:p>
  <hp:p>
    <hp:run><hp:t>양육비를 받지 못한 비율은 72.1%였다.</hp:t></hp:run>
    <hp:run>
      <hp:footNote number="1">
        <hp:subList>
          <hp:p><hp:run><hp:t>가족평등부(2025), 한부모가족 실태조사, 보도자료.</hp:t></hp:run></hp:p>
        </hp:subList>
      </hp:footNote>
    </hp:run>
  </hp:p>
  <hp:p><hp:run><hp:t>센터 종사자 1인당 담당 아동은 12.4명이다.</hp:t></hp:run></hp:p>
  <hp:p>
    <hp:run><hp:t>노인 독거 비율은 33.2%다.</hp:t></hp:run>
    <hp:run>
      <hp:endNote number="1">
        <hp:subList>
          <hp:p><hp:run><hp:t>복지부(2024), 노인실태조사, 연구보고서 2024-08.</hp:t></hp:run></hp:p>
        </hp:subList>
      </hp:endNote>
    </hp:run>
  </hp:p>
</hs:sec>
"""


def make_hwpx(path: str) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container><rootfiles/></container>')
        z.writestr("Contents/header.xml", '<?xml version="1.0"?><head/>')
        z.writestr("Contents/section0.xml", HWPX_SECTION)


def test_hwpx():
    print("\nHWPX 판독")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.hwpx")
        make_hwpx(p)
        units = read_document(p)
        parts = summarize(units)
        body = [u.text for u in units if u.part == "body"]
        fn = [u.text for u in units if u.part == "footnote"]
        en = [u.text for u in units if u.part == "endnote"]
        check(parts.get("body") == 4, f"본문 문단 4개 (실제 {parts.get('body')})")
        check(len(fn) == 1, f"각주 1개 (실제 {len(fn)})")
        check(len(en) == 1, f"미주 1개 (실제 {len(en)})")
        check(any("268.5만원" in t for t in body), "본문 수치가 그대로 나온다")
        check(fn and "보도자료" in fn[0], "각주 본문이 각주로 분리된다")
        check(en and "2024-08" in en[0], "미주 본문이 미주로 분리된다")
        check(not any("보도자료" in t for t in body),
              "각주 글자가 본문 문단에 섞이지 않는다")


def test_safexml():
    print("\nXML 안전장치")
    bomb = (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "AAAA">'
            b'<!ENTITY b "&a;&a;&a;">]><x>&b;</x>')
    # 요구사항은 "파싱이 거부된다"이다. defusedxml이 있으면 EntitiesForbidden,
    # 없으면 UnsafeDocument가 나온다 — 어느 쪽이든 값을 돌려주지 않아야 한다.
    raised = None
    try:
        fromstring(bomb)
    except Exception as exc:
        raised = exc
    check(raised is not None,
          f"엔티티 선언이 든 XML을 거부한다 ({type(raised).__name__ if raised else '통과시켜 버림'})")
    check(fromstring(b"<a><b>x</b></a>").tag == "a", "정상 XML은 그대로 읽는다")

    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "evil.zip")
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("../../etc/passwd", "x")
        try:
            open_zip(p)
            ok = False
        except UnsafeDocument:
            ok = True
        check(ok, "경로를 벗어나는 ZIP 항목을 거부한다")


def test_hml():
    """HWPML — 법제처 고시·규정에서 흔한 XML 한글 문서."""
    print("\nHWPML 판독")
    from refver.hwp import read_hangul
    doc = (b'<?xml version="1.0" encoding="utf-8"?>\n'
           b'<!DOCTYPE HWPML [\n\t<!ENTITY nbsp\t"&#160;">\n]>\n'
           b'<HWPML Version="2.1">'
           b'<HEAD><DOCSUMMARY><TITLE>\xea\xb7\x9c\xec\xa0\x95</TITLE></DOCSUMMARY>'
           b'<FOOTNOTESHAPE Type="1"/></HEAD>'
           b'<BODY><SECTION>'
           b'<P><TEXT><CHAR>\xec\xa0\x9c1\xec\xa1\xb0 \xeb\xaa\xa9\xec\xa0\x81&nbsp;\xec\x9d\xb4 \xea\xb7\x9c\xec\xa0\x95\xec\x9d\x80 268.5\xeb\xa7\x8c\xec\x9b\x90\xec\x9d\x84 \xec\xa0\x95\xed\x95\x9c\xeb\x8b\xa4.</CHAR></TEXT></P>'
           b'<P><TEXT><CHAR>\xec\xa0\x9c2\xec\xa1\xb0 \xec\xa0\x81\xec\x9a\xa9</CHAR></TEXT>'
           b'<FOOTNOTE Number="1"><P><TEXT><CHAR>\xea\xb0\x81\xec\xa3\xbc \xeb\x82\xb4\xec\x9a\xa9\xec\x9d\xb4\xeb\x8b\xa4.</CHAR></TEXT></P></FOOTNOTE></P>'
           b'</SECTION></BODY></HWPML>')
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "regulation.hwp")   # .hwp 확장자에 XML 내용 — 실제로 흔하다
        open(p, "wb").write(doc)
        units = read_hangul(p)
        body = [u.text for u in units if u.part == "body"]
        fn = [u.text for u in units if u.part == "footnote"]
        check(len(body) == 2, f"본문 문단 2개 (실제 {len(body)})")
        check(any("268.5만원" in t for t in body), "본문 수치가 나온다")
        check(any(" " in t or "목적" in t for t in body), "&nbsp; 엔티티가 치환된다")
        check(len(fn) == 1 and "각주" in fn[0], f"각주가 분리된다 (실제 {len(fn)}건)")
        check(not any("각주" in t for t in body), "각주 글자가 본문에 섞이지 않는다")
        check(not any("규정" == t for t in body), "HEAD의 제목·스타일은 본문에 들어오지 않는다")


def test_doctype_safety():
    """DTD를 처리하지 않고 제거하되, 문자 참조 엔티티만 받아들인다."""
    print("\nDTD 안전 처리")
    from refver.safexml import UnsafeDocument, defuse_doctype, fromstring

    ok = defuse_doctype(b'<?xml version="1.0"?><!DOCTYPE X [<!ENTITY nbsp "&#160;">]><X>a&nbsp;b</X>')
    check(b"<!DOCTYPE" not in ok, "DOCTYPE 선언이 제거된다")
    check(b"&#160;" in ok and b"&nbsp;" not in ok, "문자 참조 엔티티가 치환된다")
    check(fromstring(ok).text.startswith("a"), "치환 후 정상 파싱된다")

    for name, bad in [
        ("외부 참조(XXE)", b'<!DOCTYPE X SYSTEM "file:///etc/passwd"><X/>'),
        ("중첩 엔티티(폭탄)", b'<!DOCTYPE X [<!ENTITY a "AA"><!ENTITY b "&a;&a;&a;">]><X>&b;</X>'),
        ("외부 엔티티", b'<!DOCTYPE X [<!ENTITY e SYSTEM "http://x/e">]><X>&e;</X>'),
    ]:
        raised = None
        try:
            defuse_doctype(b'<?xml version="1.0"?>' + bad)
        except Exception as exc:
            raised = exc
        check(isinstance(raised, UnsafeDocument), f"{name}를 거부한다")

    plain = b"<a>no doctype</a>"
    check(defuse_doctype(plain) == plain, "DTD가 없으면 그대로 둔다")


def test_hwpx_roundtrip():
    """벤치마크 빌더가 쓴 HWPX를 도구상자가 읽어 내는가.

    한글 문서를 검증하겠다면서 HWPX 경로를 손으로 만든 픽스처로만 시험하면,
    실제로 쓰이는 모양과 어긋나도 모른다. 빌더가 쓴 것을 그대로 읽어 본다.
    """
    print("\nHWPX 쓰기→읽기 왕복")
    root = os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(HERE)), ".."))
    bench = os.path.join(root, "benchmark")
    if not os.path.exists(os.path.join(bench, "build.py")):
        print("  · 빌더가 없어 건너뜀")
        return
    sys.path.insert(0, bench)
    try:
        import build as B
    except Exception as exc:
        print(f"  · 빌더를 불러올 수 없어 건너뜀 ({type(exc).__name__})")
        return

    spec = {
        "document": {"title": "시험 문서", "author": "시험", "date": "2025-01", "format": "hwpx"},
        "sources": [{"id": "E01", "tier": "T2", "meta": {
            "authors": "오렌지환경정책연구원", "year": "2025",
            "title": "2023년 국가 온실가스 인벤토리 보고서", "url": "https://x.example/a"}}],
        "citations": [
            {"id": "D01", "placement": "body", "claim": "총배출량은 전년보다 5.8% 줄었다.", "cites": "E01"},
            {"id": "D02", "placement": "footnote", "claim": "폐기물 부문의 불확도가 가장 크다.", "cites": "E01"},
            {"id": "D03", "placement": "endnote", "claim": "흡수원은 반영하지 않았다.", "cites": "E01"},
        ]}
    prose = {"title": "시험 문서", "sections": [{"heading": "1. 서론", "blocks": [
        {"text": "들어가며. 총배출량은 전년보다 5.8% 줄었다. 뒤 문장.", "citation_ids": ["D01"]},
        {"text": "폐기물 부문의 불확도가 가장 크다. 해석에 주의가 필요하다.", "citation_ids": ["D02"]},
        {"text": "끝으로. 흡수원은 반영하지 않았다.", "citation_ids": ["D03"]}]}]}

    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "t.hwpx")
        B.FAILURES.clear()
        B.build_hwpx(spec, prose, __import__("pathlib").Path(out))
        check(not B.FAILURES, f"빌드에 위반이 없다 ({B.FAILURES[:1]})")
        units = read_document(out)
        body = [u.text for u in units if u.part == "body"]
        fn = [u.text for u in units if u.part == "footnote"]
        en = [u.text for u in units if u.part == "endnote"]
        check(all(any(c["claim"] in b for b in body) for c in spec["citations"]),
              "주장 세 건이 모두 본문에서 축자로 나온다")
        check(len(fn) == 1 and "인벤토리" in fn[0], f"각주가 분리된다 ({len(fn)}건)")
        check(len(en) == 1 and "인벤토리" in en[0], f"미주가 분리된다 ({len(en)}건)")
        check(not any("오렌지환경정책연구원" in b for b in body[:3]),
              "각주 글자가 본문 문단에 섞이지 않는다")
        check(any("(오렌지환경정책연구원, 2025)" in b for b in body),
              "본문 인용 표시가 삽입된다")


def test_docx():
    print("\ndocx 판독 (벤치마크 문서)")
    path = os.path.join(os.path.dirname(os.path.dirname(HERE)), "..",
                        "benchmark", "docs", "bench-01.docx")
    path = os.path.normpath(path)
    if not os.path.exists(path):
        print("  · 벤치마크 문서가 없어 건너뜀")
        return
    units = read_docx(path)
    parts = summarize(units)
    check(parts.get("footnote") == 4, f"각주 4건 (실제 {parts.get('footnote')})")
    check(parts.get("endnote") == 4, f"미주 4건 (실제 {parts.get('endnote')})")
    links = [l for u in units for l in u.meta.get("hyperlinks", [])]
    check(len(links) >= 5, f"외부 하이퍼링크 추출 {len(links)}건")

    # 각주가 문단의 어느 위치에 달렸는지 — 이게 없으면 문단 첫 문장의 각주를 놓친다
    anchored = [(u, n) for u in units if u.part == "body"
                for n in u.meta.get("notes", [])]
    check(len(anchored) >= 4, f"각주 부착 위치를 찾는다 ({len(anchored)}건)")
    mid = [(u, n) for u, n in anchored if 0 < n["after_chars"] < len(u.text) - 5]
    check(bool(mid), f"문단 끝이 아닌 곳에 달린 각주도 잡는다 ({len(mid)}건)")
    if mid:
        u, n = mid[0]
        check(n["kind"] in ("footnote", "endnote") and n["id"],
              f"종류와 번호가 함께 나온다 ({n['kind']}#{n['id']})")


def test_pdf():
    print("\nPDF 핀포인트")
    corpus = os.path.normpath(os.path.join(
        os.path.dirname(os.path.dirname(HERE)), "..", "benchmark", "corpus"))
    if not os.path.isdir(corpus):
        print("  · 코퍼스가 없어 건너뜀")
        return
    from refver.pdf import find, occurrences, page_lines, repeated_lines
    pages = page_lines(os.path.join(corpus, "S05.pdf"))
    skip = repeated_lines(pages)
    q = ("In 2022, the child income poverty rate in Orangeland was 9.8%, "
         "below the GECD average of 12.6%.")
    hits = find(pages, q, skip)
    check(len(hits) == 1, f"쪽 경계를 걸친 문장을 찾는다 (실제 {len(hits)}건)")
    check(hits and hits[0]["page"] != hits[0]["page_end"],
          "그 문장이 실제로 두 쪽에 걸쳐 있다")
    p1 = page_lines(os.path.join(corpus, "S01.pdf"))
    check(occurrences(p1, "저소득") == 0, "부재 확인: '저소득' 0회")
    check(occurrences(p1, "월평균 가구소득") == 1, "존재 확인: '월평균 가구소득' 1회")


def test_resolve():
    """왕복을 줄이는 일괄 조회. 잘못된 신호를 주지 않는 것이 핵심이다."""
    print("\n일괄 조회(resolve)")
    corpus = os.path.normpath(os.path.join(
        os.path.dirname(os.path.dirname(HERE)), "..", "benchmark", "corpus.bench-02"))
    doc = os.path.normpath(os.path.join(
        os.path.dirname(os.path.dirname(HERE)), "..", "benchmark", "docs", "bench-02.hwpx"))
    if not os.path.isdir(corpus):
        print("  · bench-02 코퍼스가 없어 건너뜀")
        return
    from refver.resolve import batch_lookup, key_tokens, resolve
    from refver.pdf import count, count_number, page_lines

    nums, terms = key_tokens("2023년 총배출량은 전년 대비 5.8% 감소하였다.")
    check("5.8%" in nums, f"수치를 뽑는다 {nums}")
    check(not any(t.startswith("202") for t in nums if len(t) == 4),
          "연도는 단서에서 뺀다 — 어디에나 있어 변별력이 없다")

    # % 유무를 함께 세지 않으면 표에서 온 정상 인용을 '없는 수치'로 몬다
    pg = page_lines(os.path.join(corpus, "E02.pdf"))
    check(count_number(pg, "8.1%") > 0,
          "본문의 '8.1%'를 표의 '8.1'과 이어 센다")

    # 58.1%는 8.1%가 아니다. 경계를 안 보면 "다른 출처에도 이 수치가 있다"는
    # 거짓 신호가 나가고 멀쩡한 인용이 자료원 조작으로 뒤집힌다 — 실제로 그럴 뻔했다.
    e06 = page_lines(os.path.join(corpus, "E06.pdf"))
    check(count_number(e06, "8.1%") == 0,
          "58.1% 안의 8.1%를 세지 않는다 — 자릿수 경계를 지킨다")
    check(count_number(e06, "9.6%") == 0, "29.6% 안의 9.6%도 세지 않는다")
    check(count_number(e06, "58.1%") > 0, "제 값은 그대로 센다")

    # 표는 공백을 지우면 24.1 26.0 이 24.126.0 으로 붙는다. 원래 줄에서 세야 한다.
    e05 = page_lines(os.path.join(corpus, "E05.pdf"))   # 'Nuclear 24.1 26.0'
    check(count_number(e05, "24.1") == 1, "표에서 옆 칸에 붙은 수치도 찾아낸다")

    # 심판의 부재 검사도 같은 경계를 쓴다. 말은 부분일치, 수치는 경계.
    check(count(e06, "8.1%") == 0 and count(e06, "renewable") > 0,
          "count 가 수치와 말을 알맞게 가른다")

    cits = [
        {"id": "A", "claim": "2023년 총배출량은 전년보다 5.8% 줄었다.", "source_id": "E01"},
        {"id": "B", "claim": "발전 부문 배출량은 2023년 181.4백만 톤까지 떨어졌다.",
         "source_id": "E01"},
        {"id": "C", "claim": "무언가 주장한다.", "source_id": "없는출처"},
    ]
    r = resolve(cits, corpus, doc)
    by = {x["id"]: x for x in r["citations"]}
    check(by["A"]["probe"]["numbers_in_claim"]["5.8%"]["count"] > 0,
          "출처에 있는 수치는 찾아낸다")
    check(by["B"]["probe"]["numbers_in_claim"]["181.4"]["count"] == 0,
          "출처에 없는 수치는 0으로 알린다 — 수치 오류 후보")
    check(by["C"]["source_in_corpus"] is False, "코퍼스에 없는 출처를 알린다")
    # macOS 가 만든 사본을 별개 출처로 세면, 바이트가 같은 복사본이 "다른 출처에도
    # 이 수치가 있다"는 근거로 나간다. 실측에서 출처 8개가 22개로 세어졌다.
    check(len(r["sources"]) == 8 and "E01 2" not in r["sources"],
          f"매니페스트를 정본으로 삼아 사본을 걸러낸다 — 출처 {len(r['sources'])}개")

    check("terms_absent" not in by["A"]["probe"],
          "부재 낱말 목록은 주지 않는다 — 활용형 조각을 그대로 옮기면 "
          "없는 문제를 지어내게 된다")
    check("candidates" not in by["A"]["probe"],
          "낱말로 추린 근거 후보도 주지 않는다 — 조사 조각이 엉뚱한 줄을 물어 온다")

    # 횟수만 주면 표의 옆 행에 걸린다. 수치가 놓인 줄을 함께 보여준다.
    where = by["A"]["probe"]["numbers_in_claim"]["5.8%"]["where"]
    check(bool(where) and "5.8" in where[0]["text"],
          f"수치가 놓인 줄을 그대로 보여준다 — {where[0]['text'][:40]!r}")

    # source_id 를 빠뜨리면 조용히 빈 결과를 주지 말고 그렇다고 말해야 한다
    r2 = resolve([{"id": "X", "claim": "무언가 5.8% 줄었다."}], corpus)
    check("warning" in r2 and "source_id" in r2["warning"],
          "source_id 가 없으면 조용히 넘어가지 않고 알린다")

    got = batch_lookup([{"source_id": "E03", "terms": ["전기요금", "예비력"]}], corpus)
    check(got and got[0]["counts"]["전기요금"] == 0 and got[0]["counts"]["예비력"] > 0,
          "일괄 검색이 있는 말과 없는 말을 가른다")


def test_resolve_no_text():
    """매니페스트에는 있는데 원문이 없는 출처 — 실재하지만 전문을 못 구한 경우다.

    이 자리에서 `resolve` 가 통째로 죽었다. 원문 없는 출처의 `pages` 가 None 인데
    그대로 교차확인에 넘겼다. 우회하려고 `--no-cross-check` 를 쓰면 자료원을 잘못
    붙인 인용을 잡는 장치가 함께 꺼진다 — 검증이 조용히 약해진다.

    **죽지 않는 것만으로는 모자라다.** 건너뛴 출처를 말하지 않으면 읽는 쪽은 출처
    전부를 대조한 줄 안다. 신호가 안 나온 것과 충돌이 없는 것은 다르다.
    """
    print("\n원문 없는 출처(resolve)")
    corpus = os.path.normpath(os.path.join(
        os.path.dirname(os.path.dirname(HERE)), "..", "benchmark", "corpus.bench-03"))
    if not os.path.isdir(corpus):
        print("  · bench-03 코퍼스가 없어 건너뜀")
        return
    from refver.resolve import resolve

    # F07 은 매니페스트에 "file": null 로 있다. F06 은 원문이 있고 수치가 둘이라
    # 교차확인 루프가 실제로 돌면서 F07 을 만난다 — 죽던 경로가 바로 여기다.
    cits = [
        {"id": "A", "claim": "인력을 20% 늘리면 통증 호소율이 48.7%까지 낮아진다.",
         "source_id": "F06"},
        {"id": "B", "claim": "무언가 12.3% 늘고 45.6% 줄었다.", "source_id": "F07"},
    ]
    r = resolve(cits, corpus)              # 죽지 않는 것이 첫째 조건
    by = {x["id"]: x for x in r["citations"]}

    check("F07" in r["sources"], "매니페스트에 있으면 출처로 센다 — 원문이 없을 뿐이다")
    check(r["sources_without_text"] == ["F07"],
          f"원문 없는 출처를 적어 둔다 — {r['sources_without_text']}")
    check(by["B"]["source_in_corpus"] is True,
          "실재하는데 못 읽는 것은 코퍼스에 없는 것과 다르다 — 1단계 FAIL 이 아니다")
    check(by["B"]["probe"].get("text_available") is False,
          "못 읽는다는 것을 인용마다도 알린다")
    check("warning" in r and "교차확인에서 빠졌다" in r["warning"],
          "교차확인 범위가 좁아진 것을 말한다 — 안 나온 신호를 '충돌 없음'으로 "
          "읽으면 자료원 오류를 놓친다")
    check("degraded_reasons" in (r.get("warning") or ""),
          "사람이 읽는 리포트까지 옮기라고 짚어 준다")

    # 끈 줄 알고 껐으면 좁아졌다고 다시 말할 일이 아니다. 목록은 그대로 남긴다.
    r2 = resolve(cits, corpus, cross_check=False)
    check(r2["sources_without_text"] == ["F07"]
          and "교차확인에서 빠졌다" not in (r2.get("warning") or ""),
          "교차확인을 꺼 두면 좁아졌다는 경고는 안 낸다")

    # 원문이 다 있으면 빈 목록이어야 한다. 키가 사라지면 읽는 쪽이 넘겨짚는다.
    full = os.path.normpath(os.path.join(
        os.path.dirname(os.path.dirname(HERE)), "..", "benchmark", "corpus.bench-02"))
    if os.path.isdir(full):
        r3 = resolve([{"id": "A", "claim": "총배출량이 5.8% 줄었다.", "source_id": "E01"}], full)
        check(r3["sources_without_text"] == [] and "warning" not in r3,
              "원문이 다 있으면 빈 목록으로 '다 봤다'를 분명히 한다")


def test_assemble():
    """판단만 받아 리포트를 조립한다. 막아야 할 것을 정말 막는지 본다."""
    print("\n조립(assemble)")
    root = os.path.dirname(os.path.dirname(HERE))
    corpus = os.path.normpath(os.path.join(root, "..", "benchmark", "corpus.bench-02"))
    if not os.path.isdir(corpus):
        print("  · bench-02 코퍼스가 없어 건너뜀")
        return
    from refver.assemble import AssembleError, assemble, to_judgment

    cits = {"citations": [{"id": "C01", "claim": "2023년 총배출량은 전년 대비 5.8% 감소하였다.",
                           "doc_locator": "body:4",
                           "cited_source": {"authors": "기후에너지부", "year": "2025"}}]}
    ok = {"citations": [{"id": "C01", "source": "E01", "tier": "T1", "biblio": "PASS",
                         "slots": {"who": ["오렌지국", "오렌지국", True],
                                   "value": ["5.8%", "5.8%", True]},
                         "at": ["E01:1:12"]}]}
    rep = assemble(ok, cits, corpus)
    c = rep["citations"][0]
    check(c["stage2"]["verdict"] == "SUPPORTED" and c["stage2"]["pattern"] == "none",
          "슬롯이 다 맞으면 판정을 도출한다 — 모델이 적을 자리가 없다")
    check(bool(c["stage2"]["evidence"][0]["quote"]),
          f"근거 인용문을 원문에서 뽑는다 — {c['stage2']['evidence'][0]['quote'][:28]!r}")
    check(c["claim"] == cits["citations"][0]["claim"],
          "주장 원문은 인용 목록에서 가져온다 — 다시 옮겨 적지 않는다")

    bad = json.loads(json.dumps(ok))
    bad["citations"][0]["slots"]["value"] = ["6.2%", "5.8%", False]
    check(assemble(bad, cits, corpus)["citations"][0]["stage2"]["verdict"] == "NOT_SUPPORTED",
          "VALUE가 어긋나면 뒷받침 안 됨이 저절로 나온다")

    # 여기부터가 이 모듈의 존재 이유다 — 막아야 할 것들
    forged = json.loads(json.dumps(ok))
    forged["citations"][0]["at"] = [{"at": "E01:1:12", "q": "출처에 없는 문장을 지어낸다"}]
    check(raises(AssembleError, assemble, forged, cits, corpus),
          "그 자리에 없는 인용문은 거부한다 — 근거 조작이 불가능해진다")

    ghost = json.loads(json.dumps(ok))
    ghost["citations"][0]["at"] = ["E01:9:1"]
    check(raises(AssembleError, assemble, ghost, cits, corpus),
          "없는 쪽을 짚으면 거부한다")

    lie = json.loads(json.dumps(ok))
    lie["citations"][0]["absent"] = ["배출량"]      # E01에 분명히 나오는 말
    check(raises(AssembleError, assemble, lie, cits, corpus),
          "0회가 아닌 말을 부재 증거로 적으면 거부한다 — 없는 문제를 못 지어낸다")

    strange = json.loads(json.dumps(ok))
    strange["citations"][0]["id"] = "C99"
    check(raises(AssembleError, assemble, strange, cits, corpus),
          "인용 목록에 없는 번호는 거부한다 — 유령 인용이 못 생긴다")

    # 되돌리기: 리포트 → 판단 파일 → 리포트가 같은 판정을 내야 한다
    back = assemble(to_judgment(rep), cits, corpus)
    check(back["citations"][0]["stage2"]["verdict"] == c["stage2"]["verdict"],
          "판단 파일로 접었다 펴도 판정이 같다")


def test_render_actions():
    """조치 이름이 계약과 어긋나면 사람이 읽는 리포트에 정반대 지시가 찍힌다."""
    print("\n리포트 조치 이름")
    rep = R.new_report("x.docx", "test")
    acts = ("replace", "fix_claim", "fix_biblio", "add_primary", "delete", "none_found")
    rep["citations"] = [{
        "id": f"C{i:02d}", "claim": "어떤 주장이다.", "doc_locator": "body:1",
        "cited_source": {"authors": "가", "year": "2025"},
        "stage1": {"verdict": "PASS", "tier": "T1"},
        "stage2": {"verdict": "PARTIAL", "pattern": "overreach",
                   "slots": {"who": {"claimed": "가", "source": "나", "match": False}},
                   "evidence": [{"source_id": "S01", "page": 1, "line": 1, "quote": "문장"}]},
        "tier_violation": False,
        "replacement": {"action": a, "citation": "기관, 2025, 제목", "supports": "근거"},
    } for i, a in enumerate(acts, 1)]
    md = R.render(rep)
    check("서지를 고칠 것" in md, "fix_biblio 를 '서지를 고칠 것'으로 적는다")
    check("1차 근거를 더할 것" in md, "add_primary 를 '1차 근거를 더할 것'으로 적는다")
    check(md.count("대체 출처 제안") == 1,
          "replace 하나에만 '대체 출처 제안'이 붙는다 — 모르는 조치를 그것으로 뭉뚱그리지 않는다")


def test_judge_replacement_scope():
    """근거 부족·확인 불가도 문제 인용이다 — 대체 출처가 가장 필요한 자리다."""
    print("\n대체 출처 의무 범위")
    from refver.judge import mechanical_audit

    def one(s1, s2):
        return {"schema_version": "refver-report/1.0", "run": {}, "document": {},
                "citations": [{"id": "C01", "claim": "어떤 주장이다.",
                               "doc_locator": "body:3",
                               "cited_source": {"authors": "가", "year": "2025"},
                               "stage1": {"verdict": s1, "tier": "T1"},
                               "stage2": {"verdict": s2, "pattern": "none"},
                               "tier_violation": False}]}

    def flagged(rep):
        return any(f["kind"] == "no_replacement"
                   for f in mechanical_audit(rep)["findings"])

    check(flagged(one("UNVERIFIABLE", "INSUFFICIENT_EVIDENCE")),
          "원문을 못 구했으면 대체 출처를 요구한다 — 확인 못 했다는 말만으로는 "
          "글쓴이가 할 수 있는 일이 없다")
    check(flagged(one("PASS", "NOT_SUPPORTED")), "뒷받침 안 됨도 여전히 요구한다")
    check(not flagged(one("PASS", "SUPPORTED")),
          "멀쩡한 인용에는 요구하지 않는다 — 없는 일을 시키지 않는다")


def test_report():
    print("\n리포트 계약")
    rep = R.new_report("bench-01.docx", "test")
    rep["citations"] = [{
        "id": "C01", "claim": "어떤 주장이다.", "doc_locator": "body:3",
        "cited_source": {"authors": "가족평등부", "year": "2025", "title": "실태조사"},
        "stage1": {"verdict": "PASS", "tier": "T1"},
        "stage2": {"verdict": "SUPPORTED", "pattern": "none",
                   "evidence": [{"source_id": "S01", "page": 2, "line": 5, "quote": "원문 문장"}]},
        "tier_violation": False,
    }]
    check(R.validate(rep) == [], "정상 리포트는 통과한다")

    bad = json.loads(json.dumps(rep))
    bad["citations"][0]["stage2"]["evidence"] = []
    check(any("근거" in e for e in R.validate(bad)),
          "SUPPORTED인데 근거가 없으면 잡아낸다")

    bad2 = json.loads(json.dumps(rep))
    bad2["citations"][0]["stage1"] = {"verdict": "MISMATCH", "tier": "T1"}
    check(any("mismatch_fields" in e for e in R.validate(bad2)),
          "MISMATCH인데 불일치 항목이 없으면 잡아낸다")

    bad3 = json.loads(json.dumps(rep))
    bad3["citations"].append(json.loads(json.dumps(bad3["citations"][0])))
    check(any("중복" in e for e in R.validate(bad3)), "id 중복을 잡아낸다")

    md = R.render(rep)
    check("참고문헌 검증 리포트" in md and "C01" in md, "마크다운이 생성된다")
    check("report.json에서 만들어졌다" in md, "손으로 고치지 말라는 안내가 들어간다")


def test_judge():
    """심판의 기계 점검이 흠을 실제로 잡는지 — 흠을 심어 확인한다."""
    print("\n심판 기계 점검")
    base = os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(HERE)), ".."))
    corpus = os.path.join(base, "benchmark", "corpus")
    doc = os.path.join(base, "benchmark", "docs", "bench-01.docx")
    if not os.path.isdir(corpus):
        print("  · 코퍼스가 없어 건너뜀")
        return
    from refver.judge import derive_verdict, mechanical_audit

    check(derive_verdict({"who": {"match": True}, "value": {"match": True}}) == ("SUPPORTED", "none"),
          "슬롯이 전부 일치하면 SUPPORTED가 도출된다")
    check(derive_verdict({"value": {"match": False}, "who": {"match": True}})[0] == "NOT_SUPPORTED",
          "VALUE가 어긋나면 NOT_SUPPORTED가 도출된다")
    check(derive_verdict({"who": {"match": False}, "value": {"match": True}}) == ("PARTIAL", "overreach"),
          "WHO만 어긋나면 PARTIAL/과확장이 도출된다")
    check(derive_verdict({"what": {"match": False}, "value": {"match": True}}) == ("PARTIAL", "variable_name"),
          "WHAT만 어긋나면 PARTIAL/지표명 오기가 도출된다")

    def cit(cid, **kw):
        d = {"id": cid, "claim": kw.get("claim", "어떤 주장이다."), "doc_locator": "body:1",
             "cited_source": {"authors": "오렌지국 복지부", "year": "2024", "title": "노인실태조사"},
             "stage1": {"verdict": "PASS", "tier": "T2", "matched_source_id": kw.get("sid", "S03")},
             "stage2": {"verdict": kw.get("v2", "SUPPORTED"), "pattern": kw.get("pat", "none"),
                        "evidence": kw.get("ev", []), "slots": kw.get("slots")},
             "tier_violation": False}
        if kw.get("absence"):
            d["stage2"]["absence_checked"] = kw["absence"]
        return d

    real = "단축형 노인우울척도(SGDS-K) 기준 우울증상을 보이는 노인의 비율은 11.3%였다."
    rep = {"schema_version": "refver-report/1.0", "document": {"filename": "bench-01.docx"},
           "citations": [
               cit("F1", ev=[{"source_id": "S03", "page": 1, "line": 9,
                              "quote": "이 문장은 어떤 출처에도 없다."}]),
               cit("F2", ev=[{"source_id": "S03", "page": 9, "line": 1, "quote": real}]),
               cit("F3", sid="S01", absence=["양육비"],
                   ev=[{"source_id": "S01", "page": 2, "line": 20,
                        "quote": "양육비를 한 번도 받지 못했다고 응답한 비율은 72.1%였다."}]),
               cit("F4", v2="PARTIAL", pat="overreach",
                   slots={"who": {"claimed": "노인", "source": "노인", "match": True},
                          "value": {"claimed": "11.3%", "source": "11.3%", "match": True}},
                   ev=[{"source_id": "S03", "page": 2, "line": 5, "quote": real}]),
           ]}
    a = mechanical_audit(rep, corpus=corpus, document=doc)
    kinds = {f["kind"] for f in a["findings"]}
    check("fabricated_evidence" in kinds, "지어낸 근거를 잡는다")
    check("wrong_page" in kinds, "틀린 쪽 번호를 잡는다")
    check("false_absence" in kinds, "거짓 부재 주장을 잡는다")
    check("verdict_not_derived" in kinds, "슬롯 표에서 도출되지 않는 판정을 잡는다")
    check("notes_ignored" in kinds, "각주·미주를 통째로 빠뜨린 것을 잡는다")
    check(a["gate"] == "FAIL", f"치명 지적이 있으면 게이트가 FAIL이다 (실제 {a['gate']})")

    # 판정은 맞는데 유형이 어긋난 경우 — 예전 심판은 이걸 보지 못했다
    rep2 = {"schema_version": "refver-report/1.0", "document": {"filename": "x"},
            "citations": [cit("G1", v2="SUPPORTED", pat="number_error",
                              slots={"who": {"claimed": "노인", "source": "노인", "match": True}},
                              ev=[{"source_id": "S03", "page": 2, "line": 5, "quote": real}])]}
    k2 = {f["kind"] for f in mechanical_audit(rep2, corpus=corpus)["findings"]}
    check("pattern_contradicts_verdict" in k2, "SUPPORTED에 오류 유형이 붙으면 잡는다")

    # 심판의 헛다리 방지 — 설명이 붙은 검색어를 '0회라 주장했다'고 뒤집어씌우지 않는다
    rep3 = {"schema_version": "refver-report/1.0", "document": {"filename": "x"},
            "citations": [cit("G2", absence=["독거 (S03 전문 여러 번 등장)"],
                              ev=[{"source_id": "S03", "page": 2, "line": 5, "quote": real}])]}
    k3 = {f["kind"] for f in mechanical_audit(rep3, corpus=corpus)["findings"]}
    check("false_absence" not in k3, "설명이 붙은 검색어를 거짓 부재로 몰지 않는다")
    check("annotated_absence_term" in k3, "대신 형식만 지적한다")

    # 동의어를 함께 훑는 것은 벌하지 않는다
    rep4 = {"schema_version": "refver-report/1.0", "document": {"filename": "x"},
            "citations": [cit("G3", claim="노인 우울증상 비율은 11.3%다.",
                              absence=["우울증상", "우울감", "정신건강"],
                              ev=[{"source_id": "S03", "page": 2, "line": 5, "quote": real}])]}
    k4 = {f["kind"] for f in mechanical_audit(rep4, corpus=corpus)["findings"]}
    check("irrelevant_absence" not in k4, "동의어를 함께 확인한 것은 벌하지 않는다")


def main() -> int:
    print("refver 도구상자 시험")
    test_hwpx()
    test_hml()
    test_safexml()
    test_doctype_safety()
    test_hwpx_roundtrip()
    test_docx()
    test_resolve()
    test_resolve_no_text()
    test_assemble()
    test_render_actions()
    test_judge_replacement_scope()
    test_pdf()
    test_report()
    test_judge()
    print()
    if FAILS:
        print(f"실패 {len(FAILS)}건")
        return 1
    print("전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
