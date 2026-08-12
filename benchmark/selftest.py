#!/usr/bin/env python3
"""채점기 자기시험 — 심판의 심판이 공리대로 작동하는지 확인한다.

여기서 검사하는 것은 스킬이 아니라 **채점기 자신**이다.
합성 리포트를 넣어 점수가 정의대로 나오는지 본다. 이 시험이 통과해야만
score.py로 잰 점수를 근거로 스킬을 고칠 수 있다.

실행: python3 benchmark/selftest.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from score import score  # noqa: E402

KEY = json.loads((ROOT / "answer-key.json").read_text(encoding="utf-8"))
CORPUS = ROOT / "corpus"


# ────────────────────────────────────────────────────── 합성 리포트 생성기

def entry(k: dict, *, s1: str, s2: str, pattern: str, tier=None,
          violation=False, evidence=True, claim=None) -> dict:
    ev = []
    if evidence and k.get("evidence"):
        ev = [{
            "source_id": k["evidence"]["source_id"],
            "page": k["evidence"]["page"],
            "line": k["evidence"]["line_start"],
            "quote": k["evidence"]["sentence"],
        }]
    return {
        "id": k["id"],
        "claim": claim if claim is not None else k["claim"],
        "doc_locator": k["placement"],
        "cited_source": k["cited_as"],
        "stage1": {
            "verdict": s1,
            "tier": tier if tier is not None else k["expected"].get("tier"),
            "matched_source_id": k.get("true_source_id"),
            "mismatch_fields": k.get("mismatch_fields", []),
        },
        "stage2": {"verdict": s2, "pattern": pattern, "evidence": ev},
        "tier_violation": violation,
    }


def oracle() -> dict:
    return {"schema_version": "1.0", "document": "bench-01.docx", "mode": "offline-corpus",
            "citations": [entry(k, s1=k["expected"]["stage1"], s2=k["expected"]["stage2"],
                                pattern=k["expected"]["pattern"],
                                violation=bool(k["expected"].get("tier_violation")))
                          for k in KEY["citations"]]}


def empty() -> dict:
    return {"schema_version": "1.0", "document": "bench-01.docx", "citations": []}


def all_flag() -> dict:
    """전부 문제라고 외치는 리포트. 재현율은 높아도 정밀도가 무너져야 한다."""
    return {"schema_version": "1.0", "citations": [
        entry(k, s1="FAIL", s2="NOT_SUPPORTED", pattern="unsupported", evidence=False)
        for k in KEY["citations"]]}


def lazy_pass() -> dict:
    """전부 통과시키는 리포트. 오탐은 0이지만 심은 오류를 하나도 못 잡아야 한다."""
    return {"schema_version": "1.0", "citations": [
        entry(k, s1="PASS", s2="SUPPORTED", pattern="none", evidence=False)
        for k in KEY["citations"]]}


def fabricated_pinpoint() -> dict:
    """판정은 완벽하지만 근거 인용문을 지어낸 리포트."""
    r = oracle()
    for c in r["citations"]:
        for ev in c["stage2"]["evidence"]:
            ev["quote"] = "이 문장은 어떤 출처에도 존재하지 않는 지어낸 근거이다."
    return r


def wrong_page() -> dict:
    """인용문은 진짜인데 페이지 번호만 틀린 리포트."""
    r = oracle()
    for c in r["citations"]:
        for ev in c["stage2"]["evidence"]:
            ev["page"] = ev["page"] + 5
    return r


def paraphrased() -> dict:
    """주장을 옮겨 적지 않고 요약해 버린 리포트 — 제목 기반 구제 매칭을 시험한다."""
    r = oracle()
    for c in r["citations"]:
        c["claim"] = "본문의 어떤 주장을 저자가 자기 말로 요약한 문장"
    return r


def half_done() -> dict:
    """앞의 절반만 검증하고 만 리포트."""
    r = oracle()
    r["citations"] = r["citations"][:14]
    return r


def broken_schema() -> dict:
    return {"citations": [{"claim": "x", "stage1": {"verdict": "그럴듯함"},
                           "stage2": {"verdict": "아마도"}}]}


# ─────────────────────────────────────────────────────────────── 시험

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ✓ " if cond else "  ✗ ") + msg)
    if not cond:
        FAILS.append(msg)


def main() -> int:
    print("채점기 자기시험 — 공리 확인\n")
    res = {name: score(fn(), KEY, CORPUS) for name, fn in [
        ("oracle", oracle), ("empty", empty), ("all_flag", all_flag),
        ("lazy_pass", lazy_pass), ("fabricated", fabricated_pinpoint),
        ("wrong_page", wrong_page), ("paraphrased", paraphrased),
        ("half_done", half_done), ("broken", broken_schema),
    ]}
    for n, r in res.items():
        print(f"  {n:<12} {r['score']:>6.2f}")
    print()

    print("공리 1 — 정답표대로 답한 리포트는 만점이다")
    check(res["oracle"]["score"] == 100.0, f"oracle == 100 (실제 {res['oracle']['score']})")
    for k, v in res["oracle"]["components"].items():
        check(v == 1.0, f"oracle.{k} == 1.0 (실제 {v})")

    print("\n공리 2 — 아무것도 하지 않은 리포트는 0점이다")
    check(res["empty"]["score"] == 0.0, f"empty == 0 (실제 {res['empty']['score']})")

    print("\n공리 3 — 스키마를 어기면 0점이다")
    check(res["broken"]["score"] == 0.0, "broken == 0")
    check(res["broken"]["schema_valid"] is False, "broken.schema_valid == False")

    print("\n공리 4 — 전부 문제라고 외치면 대조군 오탐이 100%다")
    check(res["all_flag"]["counts"]["false_alarm_rate"] == 1.0, "all_flag 오탐률 == 100%")
    check(res["all_flag"]["components"]["precision_on_controls"] == 0.0, "all_flag 대조군 정밀도 == 0")
    check(res["all_flag"]["score"] < 40, f"all_flag < 40 (실제 {res['all_flag']['score']})")

    print("\n공리 5 — 전부 통과시키면 심은 오류를 하나도 못 잡는다")
    check(res["lazy_pass"]["components"]["planted_recall"] == 0.0, "lazy_pass 심은오류 적발 == 0")
    check(res["lazy_pass"]["components"]["precision_on_controls"] == 1.0, "lazy_pass 대조군 정밀도 == 1")
    check(res["lazy_pass"]["score"] < 50,
          f"lazy_pass < 50 — 아무것도 못 잡은 리포트는 낙제여야 한다 (실제 {res['lazy_pass']['score']})")

    print("\n공리 5-1 — 다수 클래스만 맞혀서는 점수를 얻지 못한다(균형 정확도)")
    check(res["lazy_pass"]["counts"]["stage2_plain_accuracy"] > 0.4,
          f"단순 정확도는 높게 나온다 ({res['lazy_pass']['counts']['stage2_plain_accuracy']:.0%}) — 그래서 쓰지 않는다")
    check(res["lazy_pass"]["components"]["stage2_accuracy"] < 0.3,
          f"균형 정확도는 낮다 ({res['lazy_pass']['components']['stage2_accuracy']:.0%})")

    print("\n공리 6 — 근거를 지어내면 핀포인트 실재율이 0이 된다")
    check(res["fabricated"]["components"]["pinpoint_validity"] == 0.0, "fabricated 핀포인트 == 0")
    check(res["fabricated"]["score"] < res["oracle"]["score"], "fabricated < oracle")
    check(res["fabricated"]["components"]["stage2_accuracy"] == 1.0,
          "fabricated의 판정 자체는 만점 — 핀포인트만 따로 벌한다")

    print("\n공리 7 — 페이지를 틀리게 적으면 핀포인트가 무효다")
    check(res["wrong_page"]["components"]["pinpoint_validity"] < 0.2,
          f"wrong_page 핀포인트 < 20% (실제 {res['wrong_page']['components']['pinpoint_validity']:.0%})")

    print("\n공리 8 — 절반만 하면 추출 재현율이 절반이다")
    hd = res["half_done"]["counts"]
    check(abs(hd["extraction_recall"] - 0.5) < 0.01, f"half_done 재현율 ≈ 50% (실제 {hd['extraction_recall']:.0%})")
    check(hd["extraction_precision"] == 1.0, "half_done 정밀도 == 100%")

    print("\n공리 9 — 점수 순서가 품질 순서와 일치한다")
    order = ["oracle", "fabricated", "lazy_pass", "all_flag", "empty"]
    vals = [res[n]["score"] for n in order]
    check(vals == sorted(vals, reverse=True),
          "oracle > fabricated > lazy_pass > all_flag > empty : " +
          " > ".join(f"{n}({v:.1f})" for n, v in zip(order, vals)))

    print("\n공리 10 — 주장을 옮겨 적지 않아도 출처가 유일하면 구제된다")
    check(res["paraphrased"]["counts"]["matched"] > 0,
          f"paraphrased 매칭 {res['paraphrased']['counts']['matched']}/{len(KEY['citations'])}건")

    print()
    if FAILS:
        print(f"자기시험 실패 — {len(FAILS)}건. 채점기를 고치기 전에는 점수를 신뢰하지 말 것.")
        return 1
    print("자기시험 통과 — 채점기는 정의대로 작동한다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
