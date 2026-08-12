"""refver — 참고문헌 검증 도구상자.

  python3 -m refver probe                     실행 환경에서 무엇이 되는지 확인
  python3 -m refver read  <문서>               본문·각주·미주 전수 추출
  python3 -m refver find  <pdf> <문구>          쪽·행 핀포인트(쪽 경계도 넘어 찾음)
  python3 -m refver count <pdf> <문구>...       전수 검색 — 0회도 증거다
  python3 -m refver grep  <pdf> <정규식>        수치·표현 훑기
  python3 -m refver audit <report.json>        심판의 기계 점검
  python3 -m refver validate <report.json>     리포트 계약 위반 확인
  python3 -m refver render   <report.json>     사람이 읽는 마크다운 생성
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

from . import report as R
from .doc import read_document, summarize
from .hwp import rhwp_capabilities, rhwp_path, rhwp_to_pdf
from .pdf import available_backend, find, grep, occurrences, page_lines, repeated_lines


def _dump(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_probe(a) -> int:
    caps = {
        "python": sys.version.split()[0],
        "pdf_backend": available_backend(),
        "pdftotext": bool(shutil.which("pdftotext")),
        "rhwp": rhwp_path(),
        "network_hint": "확인 불가 — 실제로 받아 보기 전에는 알 수 없다",
    }
    if caps["rhwp"]:
        c = rhwp_capabilities()
        caps["rhwp_capabilities"] = "확인됨" if c else "capabilities 호출 실패"
    for mod in ("fitz", "pdfminer", "pypdf", "docx", "requests", "defusedxml"):
        try:
            __import__(mod)
            caps[f"has_{mod}"] = True
        except Exception:
            caps[f"has_{mod}"] = False
    _dump(caps)
    if not caps["pdf_backend"]:
        print("\n경고: PDF 판독기가 없다. 2단계(인용 적절성)를 원문으로 확인할 수 없다.",
              file=sys.stderr)
    return 0


def cmd_read(a) -> int:
    path = a.path
    if a.via_pdf and path.lower().endswith((".hwp", ".hwpx")):
        dest = os.path.splitext(path)[0] + ".rhwp.pdf"
        got = rhwp_to_pdf(path, dest)
        if got:
            print(f"rhwp로 PDF 변환: {got}", file=sys.stderr)
            path = got
        else:
            print("rhwp 변환 실패 — 순수 파이썬 판독으로 진행한다.", file=sys.stderr)
    units = read_document(path)
    if a.summary:
        _dump({"file": path, "units": len(units), "parts": summarize(units)})
        return 0
    _dump([{"text": u.text, "part": u.part, "index": u.index, "note_id": u.note_id,
            "page": u.page, "line": u.line, **({"meta": u.meta} if u.meta else {})}
           for u in units])
    return 0


def cmd_find(a) -> int:
    pages = page_lines(a.pdf)
    skip = repeated_lines(pages) if a.skip_repeated else set()
    hits = find(pages, a.quote, skip)
    _dump({"pdf": a.pdf, "quote": a.quote, "hits": hits,
           "found": len(hits), "pages": len(pages)})
    return 0 if hits else 1


def cmd_count(a) -> int:
    pages = page_lines(a.pdf)
    out = {t: occurrences(pages, t) for t in a.terms}
    _dump({"pdf": a.pdf, "pages": len(pages), "counts": out,
           "absent": [t for t, n in out.items() if n == 0]})
    return 0


def cmd_grep(a) -> int:
    _dump(grep(page_lines(a.pdf), a.pattern, a.context))
    return 0


def cmd_audit(a) -> int:
    from .judge import mechanical_audit, render_audit
    res = mechanical_audit(R.load(a.report), corpus=a.corpus, document=a.document)
    if a.json:
        _dump(res)
    else:
        print(render_audit(res))
    return {"PASS": 0, "REVIEW": 0, "FAIL": 1}[res["gate"]]


def cmd_validate(a) -> int:
    errs = R.validate(R.load(a.report))
    if errs:
        print(f"리포트 계약 위반 {len(errs)}건:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("리포트 계약 통과")
    return 0


def cmd_render(a) -> int:
    rep = R.load(a.report)
    errs = R.validate(rep)
    if errs and not a.force:
        print(f"계약 위반 {len(errs)}건 — 먼저 고치라(무시하려면 --force):", file=sys.stderr)
        for e in errs[:10]:
            print(f"  - {e}", file=sys.stderr)
        return 1
    md = R.render(rep)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(md)
        print(f"작성: {a.out}")
    else:
        print(md)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="refver", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe", help="실행 환경 확인").set_defaults(fn=cmd_probe)

    s = sub.add_parser("read", help="문서에서 본문·각주·미주 전수 추출")
    s.add_argument("path")
    s.add_argument("--summary", action="store_true")
    s.add_argument("--via-pdf", action="store_true",
                   help="한글 문서를 rhwp로 PDF 변환해 쪽·행을 얻는다")
    s.set_defaults(fn=cmd_read)

    s = sub.add_parser("find", help="PDF에서 문구의 쪽·행 찾기")
    s.add_argument("pdf")
    s.add_argument("quote")
    s.add_argument("--skip-repeated", action="store_true",
                   help="매 쪽 반복되는 머리말·꼬리말을 건너뛴다")
    s.set_defaults(fn=cmd_find)

    s = sub.add_parser("count", help="PDF 전수 검색 — 0회는 부재의 증거")
    s.add_argument("pdf")
    s.add_argument("terms", nargs="+")
    s.set_defaults(fn=cmd_count)

    s = sub.add_parser("grep", help="PDF 정규식 검색")
    s.add_argument("pdf")
    s.add_argument("pattern")
    s.add_argument("-C", "--context", type=int, default=0)
    s.set_defaults(fn=cmd_grep)

    s = sub.add_parser("audit", help="심판의 기계 점검 — 지어낸 근거·근거 없는 판정·누락")
    s.add_argument("report")
    s.add_argument("--corpus", help="출처 원문 PDF가 있는 폴더")
    s.add_argument("--document", help="검증 대상 원문서 — 전수 대조에 쓴다")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_audit)

    s = sub.add_parser("validate", help="리포트 계약 검사")
    s.add_argument("report")
    s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("render", help="report.json → 마크다운 리포트")
    s.add_argument("report")
    s.add_argument("-o", "--out")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_render)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
