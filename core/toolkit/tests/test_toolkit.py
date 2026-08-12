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
