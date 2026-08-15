"""판단만 받아 계약 리포트를 조립한다.

왜 이게 필요한가. 리포트 60,578자를 뜯어 보니 모델이 새로 만든 것은 59%뿐이고
나머지는 **이미 있는 것을 다시 옮겨 적은 것**이었다. 주장 원문과 서지는 추출 단계가
가지고 있고, 판정과 오류 유형은 슬롯 표에서 규칙대로 도출되며, 근거 인용문은 쪽·행만
알면 원문에서 뽑아낼 수 있다. 그것들을 모델이 받아쓰게 두면 시간만 쓰는 것이 아니라
틀릴 자리를 만든다.

그래서 모델은 **판단 파일**만 쓴다. 인용마다 슬롯 여섯 칸, 근거 위치, 부재 검색어,
메모. 나머지는 여기서 만든다. 덕분에 세 가지가 구조적으로 불가능해진다.

- **근거 조작** — 인용문을 기계가 원문에서 뽑는다. 지어낼 자리가 없다.
- **판정과 슬롯의 불일치** — 판정을 기계가 도출한다. 어긋날 자리가 없다.
- **없는 부재** — 0회인지 여기서 세어 확인한다. 아니면 조립이 멈춘다.

  python3 -m refver assemble judgment.json --citations citations.json \
      --corpus 출처폴더 -o report.json
"""
from __future__ import annotations

import json
from pathlib import Path

from .judge import derive_verdict
from .pdf import count, norm, page_lines

SLOT_KEYS = ("who", "when", "what", "value", "dataset", "relation")


class AssembleError(Exception):
    """조립을 멈춘다. 조용히 넘어가면 틀린 리포트가 나간다."""


def _pin(at: str) -> tuple[str, int, int, int]:
    """'E01:2:14' 또는 'E01:2:14-16' 을 (출처, 쪽, 시작행, 끝행)으로."""
    parts = str(at).split(":")
    if len(parts) != 3:
        raise AssembleError(f"근거 위치 형식이 틀렸다: {at!r} — 'E01:2:14' 처럼 적는다")
    sid, page, lines = parts[0].strip(), parts[1].strip(), parts[2].strip()
    if "-" in lines:
        a, b = lines.split("-", 1)
    else:
        a = b = lines
    try:
        return sid, int(page), int(a), int(b)
    except ValueError:
        raise AssembleError(f"근거 위치에 숫자가 아닌 값이 있다: {at!r}") from None


class Sources:
    def __init__(self, corpus: str | Path) -> None:
        self.root = Path(corpus)
        self._c: dict[str, dict] = {}

    def pages(self, sid: str) -> dict | None:
        if sid not in self._c:
            for ext in (".pdf", ".PDF"):
                p = self.root / f"{sid}{ext}"
                if p.is_file():
                    self._c[sid] = page_lines(str(p))
                    break
            else:
                self._c[sid] = None
        return self._c[sid]


def _quote(src: Sources, at: str, override: str | None = None) -> dict:
    """쪽·행에서 원문을 뽑는다. 모델이 인용문을 직접 적었으면 거기 있는지 확인한다."""
    sid, page, a, b = _pin(at)
    pages = src.pages(sid)
    if pages is None:
        raise AssembleError(f"출처 원문을 찾을 수 없다: {sid}")
    if page not in pages:
        raise AssembleError(f"{sid}에 {page}쪽이 없다 (전체 {len(pages)}쪽)")
    lines = pages[page]
    if a < 1 or b > len(lines):
        raise AssembleError(f"{sid} {page}쪽은 {len(lines)}행까지다 — {a}-{b}행을 짚었다")
    text = " ".join(l.strip() for l in lines[a - 1:b] if l.strip())
    if override:
        # 직접 적은 인용문도 받되, 그 자리에 실제로 있는지 확인한다.
        # 확인 없이 받으면 조작을 막는다는 이 모듈의 존재 이유가 사라진다.
        if norm(override) not in norm(text):
            raise AssembleError(
                f"적어 낸 인용문이 {sid} {page}쪽 {a}-{b}행에 없다.\n"
                f"  적은 것: {override[:60]}\n  그 자리: {text[:60]}"
            )
        text = override
    return {"source_id": sid, "page": page, "line": a, "quote": text}


def _slots(raw) -> dict | None:
    """판단 파일의 짧은 슬롯 표기를 계약 형태로 편다.

    받는 것: {"who": ["본문이 쓴 말", "출처가 쓴 말", false], "when": null}
    셋째 칸이 일치 여부다. 같은 것을 다르게 부르는 경우(우식경험률/충치경험률)가 있어
    기계가 문자열로 판단할 수 없다. 그것만은 모델이 정한다.
    """
    if not isinstance(raw, dict):
        return None
    out = {}
    for k in SLOT_KEYS:
        v = raw.get(k)
        if v is None:
            out[k] = None
            continue
        if not isinstance(v, (list, tuple)) or len(v) != 3:
            raise AssembleError(
                f"슬롯 {k}: [본문, 출처, 일치여부] 세 칸으로 적는다 — 받은 것 {v!r}")
        out[k] = {"claimed": v[0], "source": v[1], "match": bool(v[2])}
    return out


def assemble(judgment: dict, citations: dict, corpus: str,
             document: str | None = None, run: dict | None = None) -> dict:
    """판단 파일 + 인용 목록 → 계약 리포트."""
    from .report import new_report

    cit_rows = citations.get("citations") if isinstance(citations, dict) else citations
    by_id = {c.get("id"): c for c in (cit_rows or [])}
    src = Sources(corpus)

    judged = judgment.get("citations") if isinstance(judgment, dict) else judgment
    if not judged:
        raise AssembleError("판단 파일에 citations 가 없다")

    doc = document or (citations.get("document") if isinstance(citations, dict) else None)
    rep = new_report(doc or "", (run or {}).get("platform_profile", ""),
                     (run or {}).get("capabilities_observed"))
    if run:
        rep["run"].update({k: v for k, v in run.items() if k in rep["run"]})

    out = []
    for j in judged:
        cid = j.get("id")
        base = by_id.get(cid)
        if base is None:
            raise AssembleError(f"{cid}: 인용 목록에 없는 번호다")

        sid = j.get("source")
        biblio = str(j.get("biblio") or "PASS")
        mism = []
        if biblio.startswith("MISMATCH"):
            mism = [x.strip() for x in biblio.partition(":")[2].split(",") if x.strip()]
            biblio = "MISMATCH"
            if not mism:
                raise AssembleError(f"{cid}: MISMATCH 인데 어느 항목이 다른지 없다 "
                                    f"— 'MISMATCH:year,date' 처럼 적는다")

        ev = []
        for at in (j.get("at") or []):
            if isinstance(at, dict):
                ev.append(_quote(src, at.get("at", ""), at.get("q")))
            else:
                ev.append(_quote(src, at))

        # 부재는 여기서 세어 확인한다. 0회가 아니면 멈춘다 — 심판이 나중에
        # 치명으로 잡을 것을 쓰는 자리에서 막는 편이 왕복 하나를 아낀다.
        absent = []
        for t in (j.get("absent") or []):
            t = str(t).strip()
            if not t:
                continue
            pages = src.pages(sid) if sid else None
            if pages is None:
                raise AssembleError(f"{cid}: 부재를 확인할 출처 원문이 없다 ({sid})")
            n = count(pages, t)
            if n:
                raise AssembleError(
                    f"{cid}: 부재 증거로 적은 '{t}' 가 {sid}에 {n}회 나온다. "
                    f"없는 문제를 지어내는 셈이니 빼거나 다른 말로 확인하라.")
            absent.append(t)

        slots = _slots(j.get("slots"))
        if biblio == "FAIL":
            verdict, pattern = "NOT_APPLICABLE", "hallucinated"
        elif j.get("verdict") == "INSUFFICIENT_EVIDENCE":
            verdict, pattern = "INSUFFICIENT_EVIDENCE", "none"
        else:
            d = derive_verdict(slots, bool(ev))
            if d is None:
                raise AssembleError(f"{cid}: 슬롯 표가 없어 판정을 끌어낼 수 없다")
            verdict, pattern = d
            # 슬롯이 다 맞아도 흠이 없다는 뜻은 아니다. 슬롯 표는 주장과 출처가
            # 맞는지만 보므로, 출처 자체의 흠은 여기서 얹는다.
            if verdict == "SUPPORTED":
                if j.get("tier_violation"):
                    pattern = "tier_violation"      # 그 등급으로 댈 주장이 아니다
                elif biblio == "MISMATCH":
                    pattern = "biblio_mismatch"     # 주장은 맞고 서지가 틀렸다

        row = {
            "id": cid,
            "claim": base.get("claim"),
            "doc_locator": base.get("doc_locator"),
            "cited_source": base.get("cited_source") or {},
            "stage1": {"verdict": biblio, "tier": j.get("tier"),
                       "matched_source_id": sid, "mismatch_fields": mism,
                       "note": j.get("biblio_note") or ""},
            "stage2": {"verdict": verdict, "pattern": pattern, "slots": slots,
                       "evidence": ev, "absence_checked": absent,
                       "note": j.get("note") or ""},
            "tier_violation": bool(j.get("tier_violation")),
        }
        if j.get("fix"):
            row["replacement"] = {
                "action": j["fix"], "citation": j.get("fix_cite") or "",
                "tier": j.get("fix_tier") or "", "url": j.get("fix_url") or "",
                "supports": j.get("fix_supports") or "",
            }
        out.append(row)

    rep["citations"] = out
    return rep


def to_judgment(report: dict) -> dict:
    """계약 리포트를 판단 파일로 되돌린다. 크기를 재고 시험하는 데 쓴다."""
    rows = []
    for c in report.get("citations") or []:
        s1, s2 = c.get("stage1") or {}, c.get("stage2") or {}
        j = {"id": c.get("id"), "source": s1.get("matched_source_id"),
             "tier": s1.get("tier")}
        v = s1.get("verdict") or "PASS"
        j["biblio"] = (f"MISMATCH:{','.join(s1.get('mismatch_fields') or [])}"
                       if v == "MISMATCH" else v)
        sl = s2.get("slots") or {}
        j["slots"] = {k: ([sl[k].get("claimed"), sl[k].get("source"), sl[k].get("match")]
                          if isinstance(sl.get(k), dict) else None) for k in SLOT_KEYS}
        j["at"] = [f"{e.get('source_id')}:{e.get('page')}:{e.get('line')}"
                   for e in (s2.get("evidence") or [])]
        if s2.get("absence_checked"):
            j["absent"] = s2["absence_checked"]
        if s2.get("note"):
            j["note"] = s2["note"]
        if c.get("tier_violation"):
            j["tier_violation"] = True
        r = c.get("replacement") or {}
        if r.get("action"):
            j["fix"] = r["action"]
            for a, b in (("citation", "fix_cite"), ("tier", "fix_tier"),
                         ("url", "fix_url"), ("supports", "fix_supports")):
                if r.get(a):
                    j[b] = r[a]
        rows.append(j)
    return {"citations": rows}
