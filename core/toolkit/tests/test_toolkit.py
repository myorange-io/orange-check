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


def main() -> int:
    print("refver 도구상자 시험")
    test_hwpx()
    test_safexml()
    test_docx()
    test_pdf()
    test_report()
    print()
    if FAILS:
        print(f"실패 {len(FAILS)}건")
        return 1
    print("전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
