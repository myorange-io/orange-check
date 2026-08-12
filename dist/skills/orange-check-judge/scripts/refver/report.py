"""리포트 계약 — 검증·렌더링.

사람이 읽는 마크다운 리포트는 report.json에서 **생성**한다. 손으로 쓰지 않는다.
두 벌을 각각 쓰면 반드시 어긋나고, 어긋난 순간 어느 쪽이 진실인지 알 수 없게 된다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

SCHEMA_VERSION = "refver-report/1.0"

STAGE1 = ("PASS", "MISMATCH", "FAIL", "UNVERIFIABLE")
STAGE2 = ("SUPPORTED", "PARTIAL", "NOT_SUPPORTED", "NOT_APPLICABLE", "INSUFFICIENT_EVIDENCE")
PATTERNS = ("none", "hallucinated", "biblio_mismatch", "overreach", "variable_name",
            "wrong_dataset", "number_error", "time_mismatch", "direction_only",
            "unsupported", "tier_violation")
TIERS = ("T1", "T2", "T3", "T4", "T5")
SLOTS = ("who", "when", "what", "value", "dataset", "relation")

VERDICT_KO = {
    "PASS": "일치", "MISMATCH": "서지 불일치", "FAIL": "존재하지 않음", "UNVERIFIABLE": "확인 불가",
    "SUPPORTED": "뒷받침됨", "PARTIAL": "부분적", "NOT_SUPPORTED": "뒷받침 안 됨",
    "NOT_APPLICABLE": "판정 불가", "INSUFFICIENT_EVIDENCE": "근거 부족",
}
PATTERN_KO = {
    "none": "—", "hallucinated": "환각 출처", "biblio_mismatch": "서지 오기",
    "overreach": "과확장", "variable_name": "지표명 오기", "wrong_dataset": "자료원 불일치",
    "number_error": "수치 오기", "time_mismatch": "시점 불일치",
    "direction_only": "방향만 맞음", "unsupported": "출처가 다루지 않음",
    "tier_violation": "등급 규칙 위반",
}


def validate(report) -> list[str]:
    """스키마 위반 목록. 빈 목록이면 통과."""
    e: list[str] = []
    if not isinstance(report, dict):
        return ["최상위가 객체가 아님"]
    cits = report.get("citations")
    if not isinstance(cits, list):
        return ["citations 배열이 없음"]
    if not cits:
        e.append("citations가 비어 있음 — 인용을 하나도 추출하지 못했다")
    seen = set()
    for i, c in enumerate(cits):
        w = f"citations[{i}]"
        if not isinstance(c, dict):
            e.append(f"{w}: 객체가 아님")
            continue
        cid = c.get("id")
        if cid in seen:
            e.append(f"{w}: id 중복 ({cid})")
        seen.add(cid)
        if not isinstance(c.get("claim"), str) or not c["claim"].strip():
            e.append(f"{w}: claim이 비었음 — 문서의 문장을 그대로 옮겨야 한다")
        s1, s2 = c.get("stage1"), c.get("stage2")
        if not isinstance(s1, dict) or s1.get("verdict") not in STAGE1:
            e.append(f"{w}.stage1.verdict가 {list(STAGE1)} 중 하나가 아님")
        else:
            if s1.get("tier") not in TIERS + (None,):
                e.append(f"{w}.stage1.tier가 T1~T5 또는 null이 아님")
            if s1["verdict"] == "MISMATCH" and not s1.get("mismatch_fields"):
                e.append(f"{w}: MISMATCH인데 어느 항목이 다른지(mismatch_fields) 비었음")
        if not isinstance(s2, dict) or s2.get("verdict") not in STAGE2:
            e.append(f"{w}.stage2.verdict가 {list(STAGE2)} 중 하나가 아님")
        else:
            if s2.get("pattern") not in PATTERNS + (None,):
                e.append(f"{w}.stage2.pattern이 허용 목록에 없음: {s2.get('pattern')}")
            ev = s2.get("evidence") or []
            if not isinstance(ev, list):
                e.append(f"{w}.stage2.evidence가 배열이 아님")
            else:
                for j, x in enumerate(ev):
                    if not isinstance(x, dict):
                        e.append(f"{w}.evidence[{j}]: 객체가 아님")
                        continue
                    if not x.get("quote"):
                        e.append(f"{w}.evidence[{j}]: quote가 없음 — 원문 표현을 그대로 인용해야 한다")
                    if not isinstance(x.get("page"), int):
                        e.append(f"{w}.evidence[{j}]: page가 정수가 아님")
            if s2["verdict"] in ("SUPPORTED", "PARTIAL") and not ev:
                e.append(f"{w}: {s2['verdict']}인데 근거(evidence)가 없음 — 쪽·행과 원문 인용이 있어야 한다")
            if s2["verdict"] == "PARTIAL" and not s2.get("slots"):
                e.append(f"{w}: PARTIAL인데 어느 슬롯이 어긋났는지(slots) 비었음")
    return e


def new_report(document: str, platform: str = "", capabilities: dict | None = None) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "run": {
            "platform_profile": platform,
            "capabilities_observed": capabilities or {},
            "degraded": False,
            "degraded_reasons": [],
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        "document": {"filename": document},
        "citations": [],
    }


# ─────────────────────────────────────────────────────────── 마크다운 렌더

def _tally(cits, path, keys):
    out = {k: 0 for k in keys}
    for c in cits:
        v = (c.get(path) or {}).get("verdict")
        if v in out:
            out[v] += 1
    return out


def render(report: dict) -> str:
    cits = report.get("citations") or []
    run = report.get("run") or {}
    doc = (report.get("document") or {}).get("filename", "(문서명 없음)")
    t1 = _tally(cits, "stage1", STAGE1)
    t2 = _tally(cits, "stage2", STAGE2)
    n = len(cits)
    bad = t1["MISMATCH"] + t1["FAIL"] + t2["PARTIAL"] + t2["NOT_SUPPORTED"]

    L = [f"# 참고문헌 검증 리포트 — {doc}", ""]
    if run.get("degraded"):
        L += ["> **이 검증은 제한된 조건에서 수행됐다.** "
              + ", ".join(run.get("degraded_reasons") or []) + "", ""]
    L += ["## 1. 검증 개요", "",
          f"- 대상 문서: {doc}",
          f"- 검증 인용: {n}건",
          f"- 실행 환경: {run.get('platform_profile') or '미상'}",
          f"- 생성 시각: {run.get('generated_at', '')}", "",
          "## 2. 종합 판정", "",
          "| 단계 | 판정 | 건수 |", "|---|---|---|"]
    for k, v in t1.items():
        if v:
            L.append(f"| 1단계 서지 | {VERDICT_KO[k]} | {v} |")
    for k, v in t2.items():
        if v:
            L.append(f"| 2단계 적절성 | {VERDICT_KO[k]} | {v} |")
    L.append("")
    if n:
        rate = bad / n
        L.append(f"문제 인용 {bad}건 / 전체 {n}건 ({rate:.0%}).")
        if rate > 0.3:
            L.append("")
            L.append("> 문제 비율이 30%를 넘는다. 개별 각주를 고치는 수준이 아니라 "
                     "**근거 전체를 다시 세우기를 권한다.**")
    L += ["", "## 3. 1단계 — 서지 실존·정확성", "",
          "| # | 인용 출처 | 등급 | 판정 | 비고 |", "|---|---|---|---|---|"]
    for c in cits:
        s = c.get("stage1") or {}
        src = c.get("cited_source") or {}
        ref = f"{src.get('authors','')} ({src.get('year','')}) {src.get('title','')}".strip()
        note = s.get("note") or ""
        if s.get("mismatch_fields"):
            note = f"불일치 항목: {', '.join(s['mismatch_fields'])}. {note}".strip()
        L.append(f"| {c.get('id','')} | {ref[:70]} | {s.get('tier') or '—'} | "
                 f"{VERDICT_KO.get(s.get('verdict'), '?')} | {note[:80]} |")

    L += ["", "## 4. 2단계 — 인용 적절성", "",
          "| # | 본문 위치 | 판정 | 유형 | 출처 근거 위치 |", "|---|---|---|---|---|"]
    for c in cits:
        s = c.get("stage2") or {}
        ev = (s.get("evidence") or [{}])[0]
        loc = ""
        if ev.get("page"):
            loc = f"{ev.get('source_id','')} p{ev['page']}"
            if ev.get("line"):
                loc += f" l{ev['line']}"
        L.append(f"| {c.get('id','')} | {(c.get('doc_locator') or '')} | "
                 f"{VERDICT_KO.get(s.get('verdict'),'?')} | "
                 f"{PATTERN_KO.get(s.get('pattern'), s.get('pattern') or '—')} | {loc} |")

    prob = [c for c in cits
            if (c.get("stage2") or {}).get("verdict") in ("PARTIAL", "NOT_SUPPORTED")
            or (c.get("stage1") or {}).get("verdict") in ("MISMATCH", "FAIL")
            or c.get("tier_violation")]
    if prob:
        L += ["", "## 5. 문제 인용 상세", ""]
        for c in prob:
            s1, s2 = c.get("stage1") or {}, c.get("stage2") or {}
            L += [f"### {c.get('id','')} — {PATTERN_KO.get(s2.get('pattern'), '')}", "",
                  f"**본문 주장**: {c.get('claim','')}", ""]
            if s2.get("slots"):
                L += ["| 슬롯 | 본문이 말한 것 | 출처가 말한 것 | 일치 |", "|---|---|---|---|"]
                for k in SLOTS:
                    v = (s2["slots"] or {}).get(k)
                    if not v:
                        continue
                    if isinstance(v, dict):
                        L.append(f"| {k} | {v.get('claimed','')} | {v.get('source','')} | "
                                 f"{'○' if v.get('match') else '×'} |")
                    else:
                        L.append(f"| {k} | {v} | | |")
                L.append("")
            for ev in (s2.get("evidence") or []):
                L.append(f"- 근거: {ev.get('source_id','')} p{ev.get('page','')}"
                         f"{' l' + str(ev['line']) if ev.get('line') else ''} — “{ev.get('quote','')}”")
            if s2.get("absence_checked"):
                L.append(f"- 부재 확인: {', '.join(s2['absence_checked'])} → 출처 전문에 0회")
            if s2.get("note"):
                L.append(f"- 판단: {s2['note']}")
            if s1.get("note"):
                L.append(f"- 서지: {s1['note']}")
            rep = c.get("replacement")
            if rep:
                act = {"replace": "대체 출처 제안", "fix_claim": "주장을 고칠 것",
                       "delete": "인용을 지울 것", "none_found": "대체 출처를 찾지 못함"}
                L.append(f"- **{act.get(rep.get('action'), '대체 출처 제안')}**: "
                         f"{rep.get('citation','')} {rep.get('tier') or ''} {rep.get('url','')}".rstrip())
                if rep.get("supports"):
                    L.append(f"  - 뒷받침 근거: {rep['supports']}")
            L.append("")

    todo = [c for c in cits
            if (c.get("stage2") or {}).get("verdict") in ("INSUFFICIENT_EVIDENCE", "NOT_APPLICABLE")
            or (c.get("stage1") or {}).get("verdict") == "UNVERIFIABLE"]
    L += ["", "## 6. 사람이 확인해야 할 항목", ""]
    if todo:
        for c in todo:
            L.append(f"- [ ] {c.get('id','')}: {c.get('claim','')[:60]}… — "
                     f"{VERDICT_KO.get((c.get('stage2') or {}).get('verdict'),'')}")
    else:
        L.append("- 없음")
    L += ["", "---", "",
          f"자동 생성 — `refver render` (schema {report.get('schema_version', SCHEMA_VERSION)}). "
          "이 파일은 report.json에서 만들어졌다. 직접 고치지 말고 report.json을 고쳐 다시 생성하라."]
    return "\n".join(L)


def load(path: str) -> dict:
    return json.loads(open(path, encoding="utf-8").read())
