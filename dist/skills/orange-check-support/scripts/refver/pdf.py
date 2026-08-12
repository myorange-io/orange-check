"""출처 PDF 판독과 페이지·행 핀포인트.

2단계(인용 적절성)의 전부가 여기에 달려 있다. "출처가 그렇게 말한다"가
아니라 "몇 쪽 몇 줄에 이렇게 적혀 있다"를 대야 하기 때문이다.

중요 — 행 번호는 판독기마다 다르다. PyMuPDF·pdfminer·pypdf·pdftotext는
같은 PDF를 서로 다르게 줄 나눈다. 그래서 리포트 계약에서 **인용문(quote)이
규범이고 line은 참고값**이다. 채점도 인용문이 그 페이지에서 시작하는지로 한다.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import unicodedata

BACKENDS = ("pymupdf", "pdfminer", "pypdf", "pdftotext")


def norm(s: str) -> str:
    """공백을 전부 지운 비교용 문자열. 줄바꿈 위치에 흔들리지 않게 한다."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", s or ""))


def available_backend() -> str | None:
    try:
        import fitz  # noqa: F401
        return "pymupdf"
    except ImportError:
        pass
    try:
        import pdfminer  # noqa: F401
        return "pdfminer"
    except ImportError:
        pass
    try:
        import pypdf  # noqa: F401
        return "pypdf"
    except ImportError:
        pass
    if shutil.which("pdftotext"):
        return "pdftotext"
    return None


def page_lines(path: str, backend: str | None = None) -> dict[int, list[str]]:
    """{페이지 번호: [줄, ...]}. 페이지는 1부터 센다."""
    backend = backend or available_backend()
    if backend is None:
        raise RuntimeError(
            "PDF 판독기가 없다. pymupdf/pdfminer.six/pypdf 중 하나를 설치하거나 "
            "poppler의 pdftotext를 쓸 수 있게 하라."
        )
    if backend == "pymupdf":
        import fitz
        d = fitz.open(path)
        return {i + 1: d[i].get_text().split("\n") for i in range(d.page_count)}
    if backend == "pdfminer":
        from pdfminer.high_level import extract_text
        out = {}
        for i, pg in enumerate(extract_text(path).split("\f"), 1):
            out[i] = pg.split("\n")
        return out
    if backend == "pypdf":
        from pypdf import PdfReader
        r = PdfReader(path)
        return {i + 1: (p.extract_text() or "").split("\n") for i, p in enumerate(r.pages)}
    txt = subprocess.run(["pdftotext", "-layout", path, "-"],
                         capture_output=True, timeout=300).stdout.decode("utf-8", "ignore")
    return {i: pg.split("\n") for i, pg in enumerate(txt.split("\f"), 1) if pg.strip() or i == 1}


def flat_index(pages: dict[int, list[str]], skip_lines: set[str] | None = None):
    """문서 전체를 공백 없는 한 줄로 잇고 각 글자의 (페이지, 줄)을 기록한다.

    문장은 줄과 쪽을 넘나든다. 페이지 단위로만 찾으면 경계에 걸친 문장을 놓친다.
    머리말·꼬리말처럼 매 쪽 반복되는 줄은 skip_lines로 빼면 경계 문장이 이어진다.
    """
    skip = {norm(s) for s in (skip_lines or set())}
    flat, idx = [], []
    for pno in sorted(pages):
        for lno, line in enumerate(pages[pno], 1):
            n = norm(line)
            if not n or n in skip:
                continue
            flat.append(n)
            idx.extend([(pno, lno)] * len(n))
    return "".join(flat), idx


def find(pages: dict[int, list[str]], needle: str,
         skip_lines: set[str] | None = None) -> list[dict]:
    """문구가 나오는 위치를 전부 찾는다. 쪽 경계를 넘어도 찾는다."""
    flat, idx = flat_index(pages, skip_lines)
    t = norm(needle)
    if not t:
        return []
    hits, start = [], flat.find(t)
    while start != -1:
        p0, l0 = idx[start]
        p1, l1 = idx[start + len(t) - 1]
        hits.append({"page": p0, "line": l0, "page_end": p1, "line_end": l1,
                     "quote": needle})
        start = flat.find(t, start + 1)
    return hits


def occurrences(pages: dict[int, list[str]], needle: str) -> int:
    """전수 검색. 0회라는 사실도 증거가 된다 — 과확장 판정의 근거."""
    flat, _ = flat_index(pages)
    return flat.count(norm(needle))


def grep(pages: dict[int, list[str]], pattern: str, context: int = 0) -> list[dict]:
    """정규식으로 줄 단위 검색. 어떤 수치가 어디 있는지 훑을 때 쓴다."""
    rx = re.compile(pattern)
    out = []
    for pno in sorted(pages):
        lines = pages[pno]
        for i, line in enumerate(lines):
            if rx.search(line):
                lo, hi = max(0, i - context), min(len(lines), i + context + 1)
                out.append({"page": pno, "line": i + 1, "text": line.strip(),
                            "context": [l.strip() for l in lines[lo:hi]] if context else []})
    return out


def repeated_lines(pages: dict[int, list[str]], min_pages: int = 3) -> set[str]:
    """모든 쪽에 반복되는 줄(머리말·꼬리말·워터마크)을 찾아낸다."""
    if len(pages) < min_pages:
        return set()
    seen: dict[str, int] = {}
    for lines in pages.values():
        for s in {l.strip() for l in lines if l.strip()}:
            seen[s] = seen.get(s, 0) + 1
    need = max(min_pages, int(len(pages) * 0.8))
    return {s for s, n in seen.items() if n >= need}
