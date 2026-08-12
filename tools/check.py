#!/usr/bin/env python3
"""회귀 게이트 — 스킬을 고치기 전과 후를 비교한다.

점수 없이 수정 없다. SKILL.md를 고쳤으면 벤치마크를 다시 돌리고 이 게이트를 통과해야 한다.
점수가 떨어졌으면 회귀다. 되돌린다.

  python3 tools/check.py                    전부 검사
  python3 tools/check.py --score run-a      리포트 하나 채점하고 이력에 남긴다
  python3 tools/check.py --promote run-a    이 결과를 새 기준선으로 삼는다
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "benchmark"
RUNS = BENCH / "runs"
BASELINE = RUNS / "baseline.json"

# 기준선 대비 이만큼 넘게 떨어지면 회귀로 본다. 모델 출력에는 실행마다 흔들림이 있다.
TOLERANCE = 2.0


def run(cmd: list[str], **kw) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)
    return p.returncode, (p.stdout + p.stderr)


def gate(name: str, cmd: list[str], env: dict | None = None) -> bool:
    import os
    e = {**os.environ, **(env or {})}
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=e)
    ok = p.returncode == 0
    print(f"  {'✓' if ok else '✗'} {name}")
    if not ok:
        tail = (p.stdout + p.stderr).strip().split("\n")[-12:]
        for ln in tail:
            print(f"      {ln}")
    return ok


def score_report(path: Path) -> dict:
    code, out = run([sys.executable, str(BENCH / "score.py"), str(path),
                     "--json", str(path.with_suffix(".score.json")), "--quiet"])
    if code != 0:
        raise SystemExit(f"채점 실패: {out}")
    return json.loads(path.with_suffix(".score.json").read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--score", help="benchmark/runs/<이름>.report.json 을 채점한다")
    ap.add_argument("--promote", help="이 실행 결과를 기준선으로 삼는다")
    a = ap.parse_args()
    env = {"PYTHONPATH": str(ROOT / "core" / "toolkit")}

    if a.promote:
        p = RUNS / f"{a.promote}.score.json"
        if not p.exists():
            print(f"{p} 가 없다. 먼저 --score {a.promote} 를 돌려라.", file=sys.stderr)
            return 1
        res = json.loads(p.read_text(encoding="utf-8"))
        BASELINE.write_text(json.dumps(
            {"run": a.promote, "score": res["score"],
             "formula_version": res["formula_version"],
             "components": res["components"]},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"기준선 갱신: {a.promote} = {res['score']:.2f}점")
        return 0

    print("회귀 게이트\n")
    print("구조")
    ok = True
    ok &= gate("dist/ 가 코어에서 그대로 재생성된다", [sys.executable, "tools/build.py", "--check"])
    ok &= gate("도구상자 시험", [sys.executable, "core/toolkit/tests/test_toolkit.py"], env)
    print("\n심판의 심판")
    ok &= gate("채점기 자기시험(공리 확인)", [sys.executable, "benchmark/selftest.py"], env)
    ok &= gate("벤치마크가 사양에서 재생성된다", [sys.executable, "benchmark/build.py"], env)

    if a.score:
        rp = RUNS / f"{a.score}.report.json"
        if not rp.exists():
            print(f"\n{rp} 가 없다.", file=sys.stderr)
            return 1
        print(f"\n채점: {a.score}")
        res = score_report(rp)
        code, out = run([sys.executable, str(BENCH / "score.py"), str(rp)])
        print("\n".join("  " + l for l in out.strip().split("\n")))
        if BASELINE.exists():
            base = json.loads(BASELINE.read_text(encoding="utf-8"))
            d = res["score"] - base["score"]
            print(f"\n  기준선({base['run']}) {base['score']:.2f} → 이번 {res['score']:.2f} "
                  f"({d:+.2f})")
            if base.get("formula_version") != res.get("formula_version"):
                print("  ⚠ 산식 버전이 달라 직접 비교할 수 없다. 기준선을 다시 잡아라.")
            elif d < -TOLERANCE:
                print(f"  ✗ 회귀 — {TOLERANCE}점 넘게 떨어졌다. 변경을 되돌려라.")
                ok = False
            else:
                print("  ✓ 회귀 없음")
                for k, v in res["components"].items():
                    bv = base["components"].get(k)
                    if bv is not None and v - bv < -0.10:
                        print(f"    · {k}: {bv:.0%} → {v:.0%} — 총점은 유지됐지만 이 항목이 나빠졌다")
        else:
            print("\n  기준선이 없다. --promote 로 이 결과를 기준선으로 삼을 수 있다.")

    print()
    print("통과" if ok else "실패 — 위 항목을 고치기 전에는 배포하지 말 것")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
