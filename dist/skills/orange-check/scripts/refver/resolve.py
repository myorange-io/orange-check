"""기계로 할 수 있는 조회를 한 번에 끝낸다.

왜 이게 필요한가. 실제 검증 실행을 재 보니 **시간의 99.7%가 모델의 사고와 왕복이었고
도구 실행은 0.3%**였다. 인용 30건 검증에 16분이 걸렸는데 그중 도구가 쓴 시간은 3초다.
호출 한 번에 30초씩 드는 왕복이 31회 있었던 것이다.

그러니 도구를 빠르게 만드는 것은 의미가 없다. 줄여야 할 것은 **왕복 횟수**다.
인용마다 찾고-생각하고-또 찾는 대신, 찾을 수 있는 것을 여기서 전부 찾아 한 번에 돌려준다.
모델은 그 결과를 놓고 판단만 하면 된다.

  python3 -m refver resolve citations.json --corpus 출처폴더 --document 원문서
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .pdf import count_number, find, norm, occurrences, page_lines, repeated_lines

# 숫자는 슬롯 대조의 핵심 단서다. 연도는 어느 문장에나 있어 변별력이 없으므로 뺀다.
NUM = re.compile(r"\d[\d,]*\.?\d*%?")
YEAR = re.compile(r"^(?:19|20)\d{2}년?$")
# 2글자 이상 한글 낱말, 또는 3글자 이상 영문 낱말
TERM = re.compile(r"[가-힣]{2,}|[A-Za-z][A-Za-z-]{2,}")
# 조사·접속어처럼 어디에나 나오는 말은 단서가 못 된다
STOP = {
    "그리고", "그러나", "따라서", "하지만", "이는", "있다", "없다", "했다", "한다",
    "대비", "기준", "경우", "다음", "이상", "이하", "정도", "가운데", "따르면",
    "the", "and", "for", "with", "that", "this", "from", "per", "cent", "was", "were",
}


def key_tokens(text: str) -> tuple[list[str], list[str]]:
    """주장에서 대조에 쓸 만한 단서만 골라낸다. (숫자, 낱말)"""
    nums = [n for n in NUM.findall(text) if not YEAR.match(n) and len(n.strip("%")) >= 2]
    terms = [t for t in TERM.findall(text) if t not in STOP and len(t) >= 2]
    seen, uniq = set(), []
    for t in terms:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return nums, uniq


class Corpus:
    """출처 PDF를 한 번만 열어 두고 재사용한다."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._pages: dict[str, dict] = {}
        self._skip: dict[str, set] = {}

    def path(self, sid: str) -> Path | None:
        for ext in (".pdf", ".PDF", ""):
            p = self.root / f"{sid}{ext}"
            if p.is_file():
                return p
        return None

    def pages(self, sid: str) -> dict | None:
        if sid in self._pages:
            return self._pages[sid]
        p = self.path(sid)
        if p is None:
            return None
        pg = page_lines(str(p))
        self._pages[sid] = pg
        self._skip[sid] = repeated_lines(pg)
        return pg

    def skip(self, sid: str) -> set:
        self.pages(sid)
        return self._skip.get(sid, set())

    def ids(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.pdf"))


def probe_source(corpus: Corpus, sid: str, claim: str, max_hits: int = 6) -> dict:
    """주장의 단서를 출처에서 찾아 후보 근거 줄을 돌려준다.

    슬롯을 채우려면 결국 "이 수치가 출처 어디에 있나"와 "출처는 그걸 뭐라 부르나"를
    알아야 한다. 그 두 가지를 여기서 미리 뽑아 둔다.
    """
    pages = corpus.pages(sid)
    if pages is None:
        return {"source_id": sid, "error": "출처 원문을 찾을 수 없다"}

    nums, terms = key_tokens(claim)
    skip = corpus.skip(sid)
    hits: list[dict] = []
    seen: set[tuple[int, int]] = set()

    for token in [n.rstrip("%") for n in nums] + terms[:12]:
        for h in find(pages, token, skip)[:3]:
            key = (h["page"], h["line"])
            if key in seen:
                continue
            seen.add(key)
            line = pages[h["page"]][h["line"] - 1].strip()
            hits.append({"token": token, "page": h["page"], "line": h["line"], "text": line})
            if len(hits) >= max_hits * 3:
                break

    # 여러 단서가 함께 걸린 줄이 진짜 근거일 가능성이 높다
    weight: dict[tuple[int, int], int] = {}
    for h in hits:
        weight[(h["page"], h["line"])] = weight.get((h["page"], h["line"]), 0) + 1
    best = sorted(hits, key=lambda h: (-weight[(h["page"], h["line"])], h["page"], h["line"]))

    out, taken = [], set()
    for h in best:
        k = (h["page"], h["line"])
        if k in taken:
            continue
        taken.add(k)
        out.append({"page": h["page"], "line": h["line"], "text": h["text"],
                    "matched": sorted({x["token"] for x in hits
                                       if (x["page"], x["line"]) == k})})
        if len(out) >= max_hits:
            break

    # 부재 증거는 여기서 주지 않는다. 낱말을 기계로 자르면 "모자랐다" "쌓인"
    # 같은 활용형 조각이 나오는데, 그런 것은 출처에 당연히 없다. 그 목록을 그대로
    # 부재 증거로 옮겨 적으면 없는 문제를 지어내게 된다 — 실제로 그래서 치명
    # 지적이 8건 났다. 부재는 골라서 물어야 한다: lookup 의 terms 를 써라.
    return {
        "source_id": sid,
        "pages": len(pages),
        "numbers_in_claim": {n: count_number(pages, n) for n in nums},
        "candidates": out,
    }


def resolve(citations: list[dict], corpus_dir: str, document: str | None = None,
            cross_check: bool = True) -> dict:
    """인용 목록을 받아 기계로 확인 가능한 모든 것을 한 번에 돌려준다."""
    corpus = Corpus(corpus_dir)
    known = set(corpus.ids())

    doc_norm = ""
    if document and Path(document).is_file():
        from .doc import read_document
        try:
            doc_norm = norm("\n".join(u.text for u in read_document(document)))
        except Exception:
            doc_norm = ""

    rows = []
    for c in citations:
        cid = c.get("id")
        claim = c.get("claim") or ""
        sid = c.get("source_id") or c.get("cites") or (c.get("stage1") or {}).get("matched_source_id")
        row: dict = {
            "id": cid,
            "claim": claim,
            "source_id": sid,
            "claim_verbatim_in_document": (norm(claim) in doc_norm) if doc_norm else None,
            "source_in_corpus": (sid in known) if sid else None,
        }
        if sid and sid in known:
            row["probe"] = probe_source(corpus, sid, claim)
            if cross_check:
                # 이 수치가 **다른** 출처에도 있으면 자료원을 잘못 붙였을 수 있다.
                # 다만 6.2% 같은 흔한 값은 아무 데나 우연히 나온다. 단서가 둘 이상
                # 겹칠 때만 알린다 — 한 개짜리 우연을 신호로 내보내면 헛다리를 짚게 한다.
                nums, _ = key_tokens(claim)
                elsewhere = {}
                if len(nums) >= 2:
                    for other in known:
                        if other == sid:
                            continue
                        pg = corpus.pages(other)
                        got = [n for n in nums if count_number(pg, n)]
                        if len(got) >= 2:
                            elsewhere[other] = got
                if elsewhere:
                    row["same_numbers_in_other_sources"] = elsewhere
        rows.append(row)

    return {
        "corpus": str(corpus_dir),
        "sources": sorted(known),
        "document": document,
        "citations": rows,
        "note": ("여기까지는 기계가 찾은 것이다. 어느 후보가 진짜 근거인지, 슬롯이 맞는지는 "
                 "읽고 판단해야 한다. same_numbers_in_other_sources 가 있으면 자료원을 "
                 "잘못 붙였거나 2차 출처를 인용한 것일 수 있으니 1차를 확인하라."),
    }


def batch_lookup(queries: list[dict], corpus_dir: str) -> list[dict]:
    """검색 여러 건을 한 번에. [{source_id, quote?, terms?}] 를 받는다."""
    corpus = Corpus(corpus_dir)
    out = []
    for q in queries:
        sid = str(q.get("source_id") or "")
        pages = corpus.pages(sid)
        if pages is None:
            out.append({**q, "error": f"출처 {sid}을 찾을 수 없다"})
            continue
        r: dict = {"source_id": sid}
        if q.get("quote"):
            r["hits"] = find(pages, q["quote"], corpus.skip(sid))
            r["quote"] = q["quote"]
        if q.get("terms"):
            from .pdf import count
            r["counts"] = {t: count(pages, t) for t in q["terms"]}
            r["absent"] = [t for t, n in r["counts"].items() if n == 0]
        out.append(r)
    return out
