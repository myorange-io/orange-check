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

from .pdf import count, find, norm, occurrences, page_lines, repeated_lines
from .report import SLOTS, validate

# 규칙표 — core/methodology/30-slots.md 와 같은 내용이다.
# 어느 칸이 어긋났는지로 판정이 결정된다.
# 2단계 판정과 다른 축에서 붙는 유형 — 판정과 어긋나도 모순이 아니다.
CROSS_STAGE = ("biblio_mismatch", "tier_violation", "hallucinated")

SINGLE_SLOT_PATTERN = {
    "who": ("PARTIAL", "overreach"),
    "when": ("PARTIAL", "time_mismatch"),
    "what": ("PARTIAL", "variable_name"),
    "dataset": ("PARTIAL", "wrong_dataset"),
    "relation": ("PARTIAL", "direction_only"),
}


def derive_verdict(slots: dict | None, has_evidence: bool = True) -> tuple[str, str] | None:
    """슬롯 표에서 판정을 끌어낸다. 표가 없으면 None.

    `has_evidence`는 "지표명이 다르다"와 "출처가 그 주제를 아예 다루지 않는다"를
    가른다. 둘 다 WHAT이 어긋난 것으로 적히지만 전혀 다른 상황이다.
    출처에 견줄 지표가 있어서 이름만 다르면 부분적이고, 출처가 그 주제를
    다루지 않아 댈 근거 자체가 없으면 뒷받침 안 됨이다.
    """
    if not isinstance(slots, dict):
        return None
    filled = {k: v for k, v in slots.items()
              if k in SLOTS and isinstance(v, dict) and "match" in v}
    if not filled:
        return None
    bad = [k for k, v in filled.items() if not v.get("match")]
    if not bad:
        return ("SUPPORTED", "none") if has_evidence else ("NOT_SUPPORTED", "unsupported")
    if not has_evidence:
        return ("NOT_SUPPORTED", "unsupported")
    if "value" in bad:
        return ("NOT_SUPPORTED", "number_error")
    if len(bad) == 1:
        return SINGLE_SLOT_PATTERN.get(bad[0], ("PARTIAL", "unsupported"))
    return ("NOT_SUPPORTED", "unsupported")


def _term(t) -> str:
    """검색어에 붙은 주석을 떼어 낸다.

    계약은 검색어만 적으라고 하지만, 실제로는 "치주질환 (S04 전문 0회)"처럼
    설명을 붙여 오는 경우가 있다. 괄호 앞까지를 검색어로 본다.
    """
    s = str(t).strip()
    for sep in (" (", "(", " —", " -", ":"):
        i = s.find(sep)
        if i > 0:
            s = s[:i]
            break
    return s.strip()


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

    # ── 부재: 0회라고 한 검색어가 정말 0회인가, 그리고 그 0회가 의미가 있는가
    for c in cits:
        s2 = c.get("stage2") or {}
        terms = s2.get("absence_checked") or []
        if not terms:
            continue
        sids = {ev.get("source_id") for ev in (s2.get("evidence") or [])
                if isinstance(ev, dict) and ev.get("source_id")}
        sids.add((c.get("stage1") or {}).get("matched_source_id"))
        sids.discard(None)
        # 본문이 쓴 말 하나는 반드시 확인했어야 한다. 동의어까지 함께 훑는 것은
        # 오히려 좋은 습관이므로(한부모·한 부모·편부모) 개별 검색어를 벌하지 않고,
        # **본문에 걸리는 말이 하나도 없을 때만** 지적한다.
        claim = norm(c.get("claim") or "")
        if claim and not any(norm(_term(t)) and norm(_term(t)) in claim for t in terms):
            flag(c.get("id"), "irrelevant_absence",
                 f"부재를 확인한 말({', '.join(str(t) for t in terms[:4])}) 중 본문 주장에 나오는 것이 "
                 "하나도 없다 — 본문이 쓰지도 않은 말이 출처에 없다는 건 근거가 아니다",
                 "minor")
        for raw in terms:
            t = _term(raw)
            if t != str(raw).strip():
                # 설명이 붙어 있으면 무엇을 주장한 것인지 알 수 없다. 이때 0회라고
                # 단정하고 반박하면 없는 문제를 지어내게 된다 — 심판의 헛다리는
                # 놓치는 것보다 나쁘다. 형식을 지적하는 데서 멈춘다.
                flag(c.get("id"), "annotated_absence_term",
                     f"absence_checked에 설명이 붙어 있다: “{str(raw)[:50]}…”. "
                     "검색어만 적고 설명은 note에 쓴다", "minor")
                continue
            for sid in sids:
                path = _sources(corpus, str(sid))
                if not path:
                    continue
                if path not in cache:
                    cache[path] = page_lines(path)
                # 수치는 자릿수 경계를 지켜 센다. 15.8%를 보고 5.8%가
                # 있다고 하면 심판이 없는 문제를 지어내게 된다.
                n = count(cache[path], t)
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
        d = derive_verdict(s2.get("slots"), bool(s2.get("evidence")))
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
        # 판정이 맞아도 유형이 어긋날 수 있다 — 여기까지 봐야 '규칙에서 나왔다'가 성립한다
        pat = s2.get("pattern")
        if d[0] == got and pat and pat != d[1] and pat not in CROSS_STAGE:
            flag(c.get("id"), "pattern_not_derived",
                 f"슬롯 표대로면 유형이 {d[1]}인데 {pat}이라고 적었다", "minor")
        if got == "SUPPORTED" and pat not in (None, "none") and pat not in CROSS_STAGE:
            flag(c.get("id"), "pattern_contradicts_verdict",
                 f"SUPPORTED인데 오류 유형 {pat}이 붙어 있다", "major")

    # ── 대체 출처: 무엇을 하라는 것인지 밝혔는가
    for c in cits:
        rep = c.get("replacement")
        bad2 = ((c.get("stage2") or {}).get("verdict") in ("PARTIAL", "NOT_SUPPORTED")
                or (c.get("stage1") or {}).get("verdict") in ("MISMATCH", "FAIL")
                or c.get("tier_violation"))
        if not bad2:
            continue
        if not rep:
            flag(c.get("id"), "no_replacement",
                 "문제 인용인데 대체 출처도, 어떻게 하라는 말도 없다", "minor")
            continue
        act = rep.get("action")
        if act not in ("replace", "fix_claim", "delete", "none_found"):
            flag(c.get("id"), "replacement_action_missing",
                 f"replacement.action이 없거나 알 수 없다: {act}", "minor")
        elif act == "replace" and not (rep.get("citation") and rep.get("supports")):
            flag(c.get("id"), "replacement_incomplete",
                 "action=replace인데 어느 출처가 무엇으로 뒷받침하는지 비었다", "minor")

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
