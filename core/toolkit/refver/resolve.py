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

from .pdf import count, count_number, find, norm, page_lines, repeated_lines

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
        """코퍼스의 출처 목록. 매니페스트가 있으면 그것이 정본이다.

        폴더를 훑기만 하면 `E01 2.pdf` 같은 복사본이 별개 출처로 잡힌다. 내려받기를
        두 번 하면 생기는 파일인데, 그대로 두면 **바이트가 똑같은 사본이 "다른 출처에도
        이 수치가 있다"는 근거로 나간다.** 실측에서 출처 8개짜리 코퍼스가 22개로 세어졌다.
        """
        mf = self.root / "manifest.json"
        if mf.is_file():
            try:
                import json
                data = json.loads(mf.read_text(encoding="utf-8"))
                rows = data.get("sources") if isinstance(data, dict) else data
                ids = sorted({str(r.get("id")) for r in (rows or []) if r.get("id")})
                if ids:
                    return ids
            except Exception:
                pass
        # 매니페스트가 없으면 사본으로 보이는 이름을 걸러낸다.
        # "E01 2.pdf" 는 "E01.pdf" 가 함께 있을 때만 사본으로 본다.
        stems = {p.stem for p in self.root.glob("*.pdf")}
        return sorted(s for s in stems
                      if not (re.fullmatch(r"(.+) \d+", s)
                              and re.fullmatch(r"(.+) \d+", s).group(1) in stems))


def probe_source(corpus: Corpus, sid: str, claim: str, max_lines: int = 4) -> dict:
    """주장의 수치가 출처 어디에 어떤 모습으로 있는지 돌려준다.

    **횟수만 주면 안 된다.** "24.1이 1회 나온다"는 맞는 말이지만, 그게 탄소가격이
    아니라 같은 표의 원자력 행이면 정반대의 결론이 나온다. 실측에서 이 함정에 두 번
    걸렸다. 그래서 횟수와 함께 **그 수치가 놓인 줄을 그대로** 보여준다.
    `Nuclear 24.1 26.0`을 보면 원자력 행이라는 것이 바로 보인다.

    낱말로 근거 줄을 추려 주는 일은 하지 않는다. 한국어 주장을 기계로 자르면 "부문"
    "에서" 같은 조각이 나와 엉뚱한 줄을 물어 온다. 실측에서 묶음 담당들이 그 목록을
    죄다 무시하고 PDF를 통째로 열었다 — 출처가 1~5쪽이면 그게 낫다.

    부재 증거도 여기서 주지 않는다. 활용형 조각을 부재 증거로 옮겨 적으면 없는 문제를
    지어내게 된다. 부재는 골라서 물어야 한다: `lookup`의 `terms`를 써라.
    """
    pages = corpus.pages(sid)
    if pages is None:
        # 실재하는데 읽을 수 없는 것과 아예 없는 것은 다르다. 앞은 근거 부족이고
        # 뒤는 1단계 FAIL 이다. 같은 말로 알리면 판정이 흔들린다.
        return {"source_id": sid, "text_available": False,
                "error": "매니페스트에는 있으나 원문을 읽을 수 없다 — 판정을 지어내지 "
                         "말고 INSUFFICIENT_EVIDENCE 로 남기고 대체 출처를 찾아라"}

    nums, _ = key_tokens(claim)
    skip = corpus.skip(sid)
    found: dict[str, dict] = {}
    for n in nums:
        bare = n.rstrip("%")
        where = []
        for pno in sorted(pages):
            for i, line in enumerate(pages[pno], 1):
                if line.strip() in skip:
                    continue
                if count_number({pno: [line]}, bare):
                    where.append({"page": pno, "line": i, "text": line.strip()[:120]})
                    if len(where) >= max_lines:
                        break
            if len(where) >= max_lines:
                break
        found[n] = {"count": count_number(pages, bare), "where": where}

    return {"source_id": sid, "pages": len(pages), "numbers_in_claim": found}


def resolve(citations: list[dict], corpus_dir: str, document: str | None = None,
            cross_check: bool = True) -> dict:
    """인용 목록을 받아 기계로 확인 가능한 모든 것을 한 번에 돌려준다.

    받는 것: `[{"id": ..., "claim": "본문이 쓴 문장", "source_id": "E01"}, ...]`
    `source_id`가 없으면 아무것도 조회할 수 없다. `cites` 나 `stage1.matched_source_id`
    로 적어도 된다. 셋 다 없으면 그 사실을 `warning`에 담아 알린다 — 조용히 빈 결과를
    돌려주면 왕복을 한 번 통째로 버리게 된다. 실제로 그런 일이 있었다.
    """
    corpus = Corpus(corpus_dir)
    known = set(corpus.ids())
    # 매니페스트에는 있으나 원문이 없는 출처. 교차확인에서 통째로 빠지므로 그 사실을
    # 밝혀야 한다. `path` 로 보면 PDF를 열지 않고도 안다.
    no_text = sorted(s for s in known if corpus.path(s) is None)

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
                        if pg is None:
                            continue    # 매니페스트에는 있으나 원문이 없는 출처
                        got = [n for n in nums if count_number(pg, n)]
                        if len(got) >= 2:
                            elsewhere[other] = got
                if elsewhere:
                    row["same_numbers_in_other_sources"] = elsewhere
        rows.append(row)

    out = {
        "corpus": str(corpus_dir),
        "sources": sorted(known),
        # 빈 목록도 적는다. 키가 없으면 읽는 쪽이 '다 봤다'로 넘겨짚는다.
        "sources_without_text": no_text,
        "document": document,
        "citations": rows,
        "note": ("기계는 그 수치가 출처에 있다는 것까지만 안다. 그게 같은 것을 가리키는지는 "
                 "where 의 줄을 읽어 확인하라 — 표에서 옆 행의 값이 우연히 같을 수 있다. "
                 "same_numbers_in_other_sources 가 있으면 자료원을 잘못 붙였거나 2차 출처를 "
                 "인용한 것일 수 있으니 1차를 확인하라."),
    }
    warn = []
    missing = [r["id"] for r in rows if not r["source_id"]]
    if missing:
        warn.append(
            f"{len(missing)}건에 source_id 가 없어 아무것도 조회하지 못했다: "
            f"{missing[:8]}. 인용마다 source_id 를 넣어 다시 부르라."
        )
    if no_text and cross_check:
        # 신호가 안 나온 것과 충돌이 없는 것은 다르다. 좁아진 범위를 말하지 않으면
        # 읽는 쪽은 출처 전부를 대조한 줄 안다.
        warn.append(
            f"출처 {len(no_text)}개는 원문이 없어 교차확인에서 빠졌다: {no_text[:8]}. "
            f"이 출처들에 같은 수치가 있어도 same_numbers_in_other_sources 에 나오지 "
            f"않는다 — 안 나온 것을 '충돌 없음'으로 읽지 마라. 리포트의 "
            f"run.degraded_reasons 에 이 사실을 남겨라."
        )
    if warn:
        out["warning"] = "\n".join(warn)
    return out


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
            r["counts"] = {t: count(pages, t) for t in q["terms"]}
            r["absent"] = [t for t, n in r["counts"].items() if n == 0]
        out.append(r)
    return out
