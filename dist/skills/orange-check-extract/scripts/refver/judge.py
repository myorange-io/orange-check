"""심판의 기계 부분 — 정답표 없이도 확인할 수 있는 것들.

실제 문서에는 정답표가 없다. 그래도 리포트의 상당 부분은 기계로 검사된다.
사람이나 모델의 판단이 필요 없는 것은 전부 여기서 처리하고, 심판 스킬은
남은 판단만 한다. 심판이 판단해야 할 몫이 작을수록 심판은 흔들리지 않는다.

  계약      스키마·필수 항목 위반
  실재      근거로 적은 인용문이 그 출처 그 쪽에 정말 있는가  ← 지어낸 근거를 잡는다
  부재      "0회"라고 주장한 검색어가 정말 0회인가
  도출      슬롯 표에서 그 판정이 규칙대로 나오는가            ← 근거 없는 판정을 잡는다
  전수      문서에서 다시 뽑은 인용 수와 리포트 건수가 맞는가  ← 누락을 잡는다
"""
from __future__ import annotations

import os
import re

from .pdf import find, norm, occurrences, page_lines, repeated_lines
from .report import SLOTS, validate

# 규칙표 — core/methodology/30-slots.md 와 같은 내용이다.
# 어느 칸이 어긋났는지로 판정이 결정된다.
SINGLE_SLOT_PATTERN = {
    "who": ("PARTIAL", "overreach"),
    "when": ("PARTIAL", "time_mismatch"),
    "what": ("PARTIAL", "variable_name"),
    "dataset": ("PARTIAL", "wrong_dataset"),
    "relation": ("PARTIAL", "direction_only"),
}


def derive_verdict(slots: dict | None) -> tuple[str, str] | None:
    """슬롯 표에서 판정을 끌어낸다. 표가 없으면 None."""
    if not isinstance(slots, dict):
        return None
    filled = {k: v for k, v in slots.items()
              if k in SLOTS and isinstance(v, dict) and "match" in v}
    if not filled:
        return None
    bad = [k for k, v in filled.items() if not v.get("match")]
    if not bad:
        return ("SUPPORTED", "none")
    if "value" in bad:
        return ("NOT_SUPPORTED", "number_error")
    if len(bad) == 1:
        return SINGLE_SLOT_PATTERN.get(bad[0], ("PARTIAL", "unsupported"))
    return ("NOT_SUPPORTED", "unsupported")


def _sources(corpus: str | None, sid: str) -> str | None:
    if not corpus or not sid:
        return None
    for ext in (".pdf", ".PDF"):
        p = os.path.join(corpus, f"{sid}{ext}")
        if os.path.exists(p):
            return p
    p = os.path.join(corpus, str(sid))
    return p if os.path.exists(p) else None


def mechanical_audit(report: dict, corpus: str | None = None,
                     document: str | None = None) -> dict:
    """기계로 확인 가능한 모든 것을 확인한다. 판단은 하지 않는다."""
    cits = report.get("citations") or []
    findings: list[dict] = []

    def flag(cid, kind, detail, severity="major"):
        findings.append({"citation_id": cid, "kind": kind,
                         "detail": detail, "severity": severity})

    for e in validate(report):
        flag(None, "contract", e, "blocker")

    # ── 실재: 적어 낸 근거가 정말 그 자리에 있는가
    pin_total = pin_ok = 0
    cache: dict[str, dict] = {}
    for c in cits:
        s2 = c.get("stage2") or {}
        for ev in (s2.get("evidence") or []):
            if not isinstance(ev, dict):
                continue
            pin_total += 1
            sid, page, quote = ev.get("source_id"), ev.get("page"), ev.get("quote")
            path = _sources(corpus, str(sid or ""))
            if not path:
                flag(c.get("id"), "pinpoint_unchecked",
                     f"출처 원문 {sid}을 찾을 수 없어 근거를 확인하지 못함", "minor")
                continue
            if path not in cache:
                cache[path] = page_lines(path)
            pages = cache[path]
            hits = find(pages, str(quote or ""), repeated_lines(pages))
            if not hits:
                flag(c.get("id"), "fabricated_evidence",
                     f"인용문이 {sid} 어디에도 없다: “{str(quote)[:40]}…”", "blocker")
            elif not any(h["page"] == page for h in hits):
                flag(c.get("id"), "wrong_page",
                     f"인용문은 {sid} p{hits[0]['page']}에 있는데 p{page}라고 적었다", "major")
            else:
                pin_ok += 1

    # ── 부재: 0회라고 한 검색어가 정말 0회인가
    for c in cits:
        s2 = c.get("stage2") or {}
        terms = s2.get("absence_checked") or []
        if not terms:
            continue
        sid = next((ev.get("source_id") for ev in (s2.get("evidence") or [])
                    if isinstance(ev, dict) and ev.get("source_id")), None)
        sid = sid or (c.get("stage1") or {}).get("matched_source_id")
        path = _sources(corpus, str(sid or ""))
        if not path:
            continue
        if path not in cache:
            cache[path] = page_lines(path)
        for t in terms:
            n = occurrences(cache[path], str(t))
            if n:
                flag(c.get("id"), "false_absence",
                     f"'{t}'가 0회라고 했으나 {sid}에 {n}회 나온다", "blocker")

    # ── 도출: 슬롯 표에서 그 판정이 나오는가
    derivable = agree = 0
    for c in cits:
        s2 = c.get("stage2") or {}
        got = s2.get("verdict")
        if got in ("NOT_APPLICABLE", "INSUFFICIENT_EVIDENCE"):
            continue
        d = derive_verdict(s2.get("slots"))
        if d is None:
            if got in ("PARTIAL", "NOT_SUPPORTED"):
                flag(c.get("id"), "no_slot_table",
                     f"{got} 판정인데 슬롯 표가 없다 — 무엇이 어긋났는지 알 수 없다", "major")
            continue
        derivable += 1
        if d[0] == got:
            agree += 1
        elif not s2.get("note"):
            flag(c.get("id"), "verdict_not_derived",
                 f"슬롯 표대로면 {d[0]}({d[1]})인데 {got}({s2.get('pattern')})라고 적었고 사유도 없다",
                 "major")

    # ── 전수: 문서에서 다시 뽑아 건수를 맞춘다
    coverage = None
    if document and os.path.exists(document):
        try:
            from .doc import read_document
            units = read_document(document)
            body = "\n".join(u.text for u in units)
            missing = [c.get("id") for c in cits
                       if c.get("claim") and norm(c["claim"]) not in norm(body)]
            for cid in missing:
                flag(cid, "claim_not_in_document",
                     "리포트의 주장 문장이 원문서에 그대로 없다 — 요약했거나 지어냈다", "major")
            notes = sum(1 for u in units if u.part in ("footnote", "endnote"))
            coverage = {"document_units": len(units), "note_units": notes,
                        "report_citations": len(cits),
                        "claims_not_found": len(missing)}
            if notes and not any(
                "footnote" in str(c.get("doc_locator", "")) or
                "endnote" in str(c.get("doc_locator", "")) or
                "각주" in str(c.get("doc_locator", "")) for c in cits
            ):
                flag(None, "notes_ignored",
                     f"문서에 각주·미주가 {notes}건 있는데 리포트에 각주 출처가 하나도 없다", "blocker")
        except Exception as exc:  # 판독 실패는 심판의 문제가 아니다
            coverage = {"error": f"{type(exc).__name__}: {exc}"}

    blockers = sum(1 for f in findings if f["severity"] == "blocker")
    majors = sum(1 for f in findings if f["severity"] == "major")
    return {
        "mechanical": {
            "pinpoint_checked": pin_total,
            "pinpoint_valid": pin_ok,
            "pinpoint_validity": round(pin_ok / pin_total, 4) if pin_total else None,
            "verdict_derivable": derivable,
            "verdict_agrees_with_slots": agree,
            "derivation_agreement": round(agree / derivable, 4) if derivable else None,
            "coverage": coverage,
        },
        "counts": {"blocker": blockers, "major": majors,
                   "minor": len(findings) - blockers - majors},
        "findings": findings,
        "gate": "FAIL" if blockers else ("REVIEW" if majors else "PASS"),
    }


def render_audit(a: dict) -> str:
    m, c = a["mechanical"], a["counts"]
    L = [f"기계 점검: {a['gate']}  (치명 {c['blocker']} · 중대 {c['major']} · 경미 {c['minor']})", ""]
    if m["pinpoint_validity"] is not None:
        L.append(f"  근거 실재율   {m['pinpoint_valid']}/{m['pinpoint_checked']} ({m['pinpoint_validity']:.0%})")
    if m["derivation_agreement"] is not None:
        L.append(f"  판정 도출 일치 {m['verdict_agrees_with_slots']}/{m['verdict_derivable']} ({m['derivation_agreement']:.0%})")
    if isinstance(m.get("coverage"), dict) and "report_citations" in m["coverage"]:
        cov = m["coverage"]
        L.append(f"  전수 대조      리포트 {cov['report_citations']}건 / 문서 각주·미주 {cov['note_units']}건"
                 f" / 원문서에 없는 주장 {cov['claims_not_found']}건")
    if a["findings"]:
        L += ["", "  지적:"]
        for f in a["findings"][:25]:
            tag = {"blocker": "치명", "major": "중대", "minor": "경미"}[f["severity"]]
            L.append(f"    [{tag}] {f['citation_id'] or '-'}: {f['detail']}")
        if len(a["findings"]) > 25:
            L.append(f"    … 외 {len(a['findings']) - 25}건")
    return "\n".join(L)
