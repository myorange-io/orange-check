#!/usr/bin/env python3
"""결정적 채점기 — 심판의 심판(Layer 0).

LLM 판단이 전혀 없다. 정답표와 리포트를 기계적으로 대조하고,
핀포인트로 적힌 인용문이 실제 그 PDF 그 페이지에 있는지 다시 열어 확인한다.

산식은 고정·공개다. 가중치를 바꾸면 과거 점수와 비교할 수 없으므로
`WEIGHTS`와 `SCORE_FORMULA_VERSION`을 함께 올린다.

실행:
  python3 benchmark/score.py report.json
  python3 benchmark/score.py report.json --key benchmark/answer-key.json --json out.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent

SCORE_FORMULA_VERSION = "1.1"
WEIGHTS = {
    "extraction_f1": 0.18,
    "stage1_accuracy": 0.14,
    "stage2_accuracy": 0.22,
    "planted_recall": 0.14,
    "precision_on_controls": 0.10,   # 1 - false_alarm_rate
    "pinpoint_validity": 0.12,
    "tier_accuracy": 0.05,
    "pattern_accuracy": 0.05,
}

STAGE1 = {"PASS", "MISMATCH", "FAIL"}
STAGE2 = {"SUPPORTED", "PARTIAL", "NOT_SUPPORTED", "NOT_APPLICABLE"}
PATTERNS = {
    "none", "hallucinated", "biblio_mismatch", "overreach", "variable_name",
    "wrong_dataset", "number_error", "time_mismatch", "unsupported", "tier_violation",
}


def norm(s) -> str:
    if not isinstance(s, str):
        return ""
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", s))


def norm_title(s) -> str:
    """서지 제목 비교용: 공백 제거 + 문장부호 제거 + 소문자."""
    return re.sub(r"[^\w가-힣]", "", norm(s)).lower()


# ────────────────────────────────────────────────────────── 스키마 검증(무의존)

def validate(report) -> list[str]:
    errs: list[str] = []
    if not isinstance(report, dict):
        return ["리포트 최상위가 객체가 아님"]
    cits = report.get("citations")
    if not isinstance(cits, list):
        return ["citations 배열이 없음"]
    for i, c in enumerate(cits):
        w = f"citations[{i}]"
        if not isinstance(c, dict):
            errs.append(f"{w}: 객체가 아님")
            continue
        if not isinstance(c.get("claim"), str) or not c["claim"].strip():
            errs.append(f"{w}: claim(본문 주장 원문)이 비었음")
        s1 = c.get("stage1")
        if not isinstance(s1, dict) or s1.get("verdict") not in STAGE1:
            errs.append(f"{w}.stage1.verdict가 {sorted(STAGE1)} 중 하나가 아님")
        s2 = c.get("stage2")
        if not isinstance(s2, dict) or s2.get("verdict") not in STAGE2:
            errs.append(f"{w}.stage2.verdict가 {sorted(STAGE2)} 중 하나가 아님")
        if isinstance(s2, dict):
            ev = s2.get("evidence", [])
            if ev is not None and not isinstance(ev, list):
                errs.append(f"{w}.stage2.evidence가 배열이 아님")
    return errs


# ─────────────────────────────────────────────────────────────── 매칭

def match(report_cits: list[dict], key_cits: list[dict]) -> tuple[dict, list[int]]:
    """정답 id -> 리포트 인덱스. 두 가지 결정적 규칙만 쓴다.

    1) 정답의 anchor(공백 제거한 주장 원문)가 리포트 claim에 포함되면 매칭.
       -> 리포트는 문서의 문장을 그대로 옮겨 적어야 한다(리포트 계약).
    2) 실패 시, 인용 서지 제목이 정답과 같고 그 제목이 정답표에서 유일하면 매칭.
       -> 주장을 바꿔 썼더라도 출처가 일의적이면 구제한다.
    """
    used: set[int] = set()
    pairs: dict[str, int] = {}
    rnorm = [norm(c.get("claim", "")) for c in report_cits]

    for k in key_cits:
        anchor = k["anchor"]
        for i, rc in enumerate(rnorm):
            if i in used:
                continue
            if anchor and anchor in rc:
                pairs[k["id"]] = i
                used.add(i)
                break

    title_counts: dict[str, int] = {}
    for k in key_cits:
        title_counts[norm_title(k["cited_as"].get("title"))] = \
            title_counts.get(norm_title(k["cited_as"].get("title")), 0) + 1

    for k in key_cits:
        if k["id"] in pairs:
            continue
        kt = norm_title(k["cited_as"].get("title"))
        if not kt or title_counts.get(kt, 0) != 1:
            continue
        for i, c in enumerate(report_cits):
            if i in used:
                continue
            src = c.get("cited_source") or {}
            if norm_title(src.get("title")) == kt:
                pairs[k["id"]] = i
                used.add(i)
                break

    spurious = [i for i in range(len(report_cits)) if i not in used]
    return pairs, spurious


# ──────────────────────────────────────────────────────── 핀포인트 실재 확인

def check_pinpoints(report_cits: list[dict], corpus: Path,
                    watermark: str = "") -> tuple[int, int, list[str]]:
    """리포트가 적은 (source_id, page, quote)를 PDF를 다시 열어 확인한다.

    인용문이 그 페이지에 실제로 없으면 지어낸 근거다. 여기서 걸린다.

    한 문장이 페이지를 걸칠 수 있으므로 다음 페이지까지 이어 붙여 찾되,
    **시작 위치가 적어 낸 페이지 안**이어야 유효로 친다. 다음 페이지에서야
    비로소 시작하는 인용문은 틀린 페이지를 적은 것이다.
    """
    try:
        import fitz
    except ImportError:
        return 0, 0, ["PyMuPDF 없음 — 핀포인트 검증 불가(0점 처리)"]

    docs: dict[str, object] = {}
    ptext: dict[tuple[str, int], str] = {}
    wm = norm(watermark)

    def page_norm(sid: str, page: int) -> str:
        """워터마크 줄을 제외한 페이지 본문(공백 제거)."""
        k = (sid, page)
        if k in ptext:
            return ptext[k]
        if sid not in docs:
            pdf = corpus / f"{sid}.pdf"
            docs[sid] = fitz.open(str(pdf)) if pdf.exists() else None
        d = docs[sid]
        out = ""
        if d is not None and 1 <= page <= d.page_count:
            lines = d[page - 1].get_text().split("\n")
            out = "".join(norm(l) for l in lines if not (wm and norm(l) == wm))
        ptext[k] = out
        return out

    total = ok = 0
    notes: list[str] = []
    for c in report_cits:
        s2 = c.get("stage2") or {}
        for ev in (s2.get("evidence") or []):
            if not isinstance(ev, dict):
                continue
            total += 1
            quote, sid, page = ev.get("quote"), ev.get("source_id") or ev.get("source"), ev.get("page")
            if not quote or not sid or not isinstance(page, int):
                notes.append(f"{c.get('id','?')}: 근거에 source_id/page/quote가 갖춰지지 않음")
                continue
            here = page_norm(str(sid), page)
            spill = here + page_norm(str(sid), page + 1)
            i = spill.find(norm(quote))
            if i != -1 and i < len(here):
                ok += 1
            else:
                notes.append(f"{c.get('id','?')}: '{str(quote)[:34]}…' 가 {sid} p{page}에서 시작하지 않음")
    return ok, total, notes


# ─────────────────────────────────────────────────────────────── 채점

def ratio(num: int, den: int) -> float:
    """분모가 0이면 0점. 아무것도 안 한 리포트가 점수를 얻지 못하게 한다."""
    return (num / den) if den else 0.0


def macro_recall(per_class: dict[str, list[int]]) -> float:
    """클래스별 재현율의 단순 평균(균형 정확도).

    판정 분포는 PASS·SUPPORTED 쪽으로 크게 치우쳐 있다. 단순 정확도를 쓰면
    전부 "이상 없음"이라고 답하는 리포트가 절반 넘는 점수를 받는다.
    클래스마다 같은 무게를 주어, 소수 클래스(FAIL·PARTIAL·NOT_SUPPORTED)를
    실제로 가려낸 리포트만 점수를 얻게 한다.

    정답표에 한 번도 나오지 않는 클래스는 평균에서 제외한다.
    """
    rs = [ok / n for ok, n in per_class.values() if n]
    return sum(rs) / len(rs) if rs else 0.0


def score(report: dict, key: dict, corpus: Path) -> dict:
    key_cits = key["citations"]
    rcits = report.get("citations") or []

    errs = validate(report)
    if errs:
        return {
            "score": 0.0, "schema_valid": False, "schema_errors": errs[:20],
            "formula_version": SCORE_FORMULA_VERSION,
        }

    pairs, spurious = match(rcits, key_cits)

    tp = len(pairs)
    extraction_recall = ratio(tp, len(key_cits))
    extraction_precision = ratio(tp, len(rcits))
    f1 = (2 * extraction_recall * extraction_precision /
          (extraction_recall + extraction_precision)) if (extraction_recall + extraction_precision) else 0.0

    s1_ok = s1_n = s2_ok = s2_n = 0
    tier_ok = tier_n = pat_ok = pat_n = 0
    planted_ok = planted_n = 0
    control_clean = control_n = 0
    per_citation = []
    confusion1: dict[str, int] = {}
    confusion2: dict[str, int] = {}
    # 클래스별 (맞춘 수, 전체 수) — 균형 정확도용. 누락된 인용도 오답으로 센다.
    cls1: dict[str, list[int]] = {v: [0, 0] for v in STAGE1}
    cls2: dict[str, list[int]] = {v: [0, 0] for v in STAGE2}

    for k in key_cits:
        exp = k["expected"]
        idx = pairs.get(k["id"])
        row = {"id": k["id"], "planted": k["planted"], "found": idx is not None}
        cls1[exp["stage1"]][1] += 1
        cls2[exp["stage2"]][1] += 1
        if idx is None:
            if k["planted"] != "none":
                planted_n += 1
            else:
                control_n += 1
            row["expected_stage1"] = exp["stage1"]
            row["expected_stage2"] = exp["stage2"]
            per_citation.append(row)
            continue

        rc = rcits[idx]
        g1 = (rc.get("stage1") or {}).get("verdict")
        g2 = (rc.get("stage2") or {}).get("verdict")
        gtier = (rc.get("stage1") or {}).get("tier")
        gpat = (rc.get("stage2") or {}).get("pattern")
        gviol = bool(rc.get("tier_violation"))

        s1_n += 1
        if g1 == exp["stage1"]:
            s1_ok += 1
            cls1[exp["stage1"]][0] += 1
        confusion1[f"{exp['stage1']}→{g1}"] = confusion1.get(f"{exp['stage1']}→{g1}", 0) + 1

        s2_n += 1
        if g2 == exp["stage2"]:
            s2_ok += 1
            cls2[exp["stage2"]][0] += 1
        confusion2[f"{exp['stage2']}→{g2}"] = confusion2.get(f"{exp['stage2']}→{g2}", 0) + 1

        if exp.get("tier"):
            tier_n += 1
            if gtier == exp["tier"]:
                tier_ok += 1

        pat_n += 1
        if gpat in PATTERNS and gpat == exp["pattern"]:
            pat_ok += 1

        clean = (g1 == "PASS" and g2 == "SUPPORTED" and not gviol)
        if k["planted"] == "none":
            control_n += 1
            if clean:
                control_clean += 1
        else:
            planted_n += 1
            hit = (g1 == exp["stage1"] and g2 == exp["stage2"]
                   and gviol == bool(exp.get("tier_violation")))
            if hit:
                planted_ok += 1

        row.update({
            "expected_stage1": exp["stage1"], "got_stage1": g1,
            "expected_stage2": exp["stage2"], "got_stage2": g2,
            "expected_pattern": exp["pattern"], "got_pattern": gpat,
            "expected_tier": exp.get("tier"), "got_tier": gtier,
            "expected_violation": bool(exp.get("tier_violation")), "got_violation": gviol,
        })
        per_citation.append(row)

    pin_ok, pin_total, pin_notes = check_pinpoints(rcits, corpus, key.get("watermark", ""))

    comp = {
        "extraction_f1": f1,
        "stage1_accuracy": macro_recall(cls1),
        "stage2_accuracy": macro_recall(cls2),
        "planted_recall": ratio(planted_ok, planted_n),
        "precision_on_controls": ratio(control_clean, control_n),
        "pinpoint_validity": ratio(pin_ok, pin_total),
        "tier_accuracy": ratio(tier_ok, tier_n),
        "pattern_accuracy": ratio(pat_ok, pat_n),
    }
    total = round(100.0 * sum(WEIGHTS[k] * v for k, v in comp.items()), 2)

    return {
        "score": total,
        "formula_version": SCORE_FORMULA_VERSION,
        "schema_valid": True,
        "weights": WEIGHTS,
        "components": {k: round(v, 4) for k, v in comp.items()},
        "counts": {
            "key_citations": len(key_cits), "report_citations": len(rcits),
            "matched": tp, "spurious": len(spurious),
            "extraction_recall": round(extraction_recall, 4),
            "extraction_precision": round(extraction_precision, 4),
            "planted_total": planted_n, "planted_exact": planted_ok,
            "control_total": control_n, "control_clean": control_clean,
            "false_alarm_rate": round(1 - ratio(control_clean, control_n), 4),
            "pinpoint_checked": pin_total, "pinpoint_valid": pin_ok,
            # 참고용 단순 정확도 — 점수에는 균형 정확도를 쓴다
            "stage1_plain_accuracy": round(ratio(s1_ok, s1_n), 4),
            "stage2_plain_accuracy": round(ratio(s2_ok, s2_n), 4),
            "stage1_per_class": {k2: f"{v[0]}/{v[1]}" for k2, v in cls1.items() if v[1]},
            "stage2_per_class": {k2: f"{v[0]}/{v[1]}" for k2, v in cls2.items() if v[1]},
        },
        "stage1_confusion": confusion1,
        "stage2_confusion": confusion2,
        "pinpoint_problems": pin_notes[:20],
        "per_citation": per_citation,
    }


def render(res: dict) -> str:
    if not res.get("schema_valid"):
        return ("점수 0.0 — 리포트 스키마 위반\n  " +
                "\n  ".join(res.get("schema_errors", [])))
    c, n = res["components"], res["counts"]
    lines = [
        f"점수 {res['score']:.2f} / 100   (산식 v{res['formula_version']})",
        "",
        f"  인용 추출     재현 {n['extraction_recall']:.0%}  정밀 {n['extraction_precision']:.0%}  "
        f"(정답 {n['key_citations']}건 중 {n['matched']}건 매칭, 유령 {n['spurious']}건)",
        f"  1단계 서지    정확도 {c['stage1_accuracy']:.0%}",
        f"  2단계 적절성  정확도 {c['stage2_accuracy']:.0%}",
        f"  심은 오류     {n['planted_exact']}/{n['planted_total']} 정확 적발 ({c['planted_recall']:.0%})",
        f"  대조군 오탐   {n['false_alarm_rate']:.0%}  (정상 {n['control_total']}건 중 {n['control_total']-n['control_clean']}건 잘못 지적)",
        f"  핀포인트 실재 {n['pinpoint_valid']}/{n['pinpoint_checked']} ({c['pinpoint_validity']:.0%})",
        f"  등급/패턴     {c['tier_accuracy']:.0%} / {c['pattern_accuracy']:.0%}",
    ]
    if res.get("pinpoint_problems"):
        lines += ["", "  지어낸 근거로 의심되는 항목:"]
        lines += [f"    · {p}" for p in res["pinpoint_problems"][:6]]
    miss = [r["id"] for r in res["per_citation"] if not r["found"]]
    if miss:
        lines += ["", f"  누락된 인용: {', '.join(miss)}"]
    wrong = [f"{r['id']}({r['expected_stage2']}→{r.get('got_stage2')})"
             for r in res["per_citation"]
             if r["found"] and r.get("got_stage2") != r["expected_stage2"]]
    if wrong:
        lines += [f"  2단계 오판: {', '.join(wrong)}"]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report", help="채점할 report.json")
    ap.add_argument("--key", default=str(ROOT / "answer-key.json"))
    ap.add_argument("--corpus", default=str(ROOT / "corpus"))
    ap.add_argument("--json", help="결과를 이 경로에 JSON으로 저장")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    report = json.loads(Path(a.report).read_text(encoding="utf-8"))
    key = json.loads(Path(a.key).read_text(encoding="utf-8"))
    res = score(report, key, Path(a.corpus))
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    if not a.quiet:
        print(render(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
