#!/usr/bin/env python3
"""회귀 게이트 — 스킬을 고치기 전과 후를 비교한다.

점수 없이 수정 없다. SKILL.md를 고쳤으면 벤치마크를 다시 돌리고 이 게이트를 통과해야 한다.
점수가 떨어졌으면 회귀다. 되돌린다.

  python3 tools/check.py                       전부 검사
  python3 tools/check.py --score run-b          bench-01 리포트를 채점한다
  python3 tools/check.py --score run-c --bench bench-02
  python3 tools/check.py --promote run-b        이 결과를 그 벤치마크의 기준선으로 삼는다

기준선은 벤치마크마다 따로 잡고, 총평은 평균으로 낸다. 한쪽만 좋아지고
다른 쪽이 나빠지는 것을 총점 하나로 덮지 않기 위해서다.
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
BENCHES = ("bench-01", "bench-02", "bench-03")

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


def check_zip_layout() -> bool:
    """스킬 zip은 풀었을 때 SKILL.md를 담은 폴더 하나가 나와야 한다.

    claude.ai 스킬 업로드가 그 구조를 기대한다. 여러 스킬을 한 겹 더 감싸 넣으면
    업로드 자체가 되지 않는다 — 한 번 그렇게 만들었다가 잡았다.
    """
    import zipfile
    pk = ROOT / "dist" / "packages"
    bad = []
    for z in sorted(pk.glob("*.zip")):
        if z.name.endswith("-all.zip"):
            continue
        with zipfile.ZipFile(z) as zf:
            names = zf.namelist()
        roots = {n.split("/")[0] for n in names}
        skills = [n for n in names if n.count("/") == 1 and n.endswith("SKILL.md")]
        if len(roots) != 1 or len(skills) != 1:
            bad.append(f"{z.name}: 최상위 폴더 {sorted(roots)}, 1단계 SKILL.md {len(skills)}개")
    print(f"  {'✓' if not bad else '✗'} 스킬 zip 구조 (풀면 SKILL.md 담은 폴더 하나)")
    for b in bad:
        print(f"      {b}")
    return not bad


def check_single_package() -> bool:
    """패키지는 하나여야 한다 — 플랫폼별로 갈라지면 반드시 어긋난다."""
    skills = ROOT / "dist" / "skills"
    # 빈 폴더는 세지 않는다. macOS가 빌드 중에 "skills 2" 같은 빈 중복 폴더를
    # 만들어 두는 일이 있는데, 그건 플랫폼별 분기가 생긴 것과는 다른 문제다.
    stray = [p.name for p in (ROOT / "dist").iterdir()
             if p.is_dir() and p.name not in ("skills", "packages")
             and any(p.rglob("*"))]
    ok = skills.is_dir() and not stray
    print(f"  {'✓' if ok else '✗'} 패키지가 하나다 (플랫폼별 분기 없음)")
    if stray:
        print(f"      플랫폼별 폴더가 남아 있다: {stray}")
    return ok


def score_path(name: str) -> Path:
    return RUNS / f"{name}.score.json"


def score_report(name: str, bench: str = "bench-01") -> dict:
    rp, sp = RUNS / f"{name}.report.json", score_path(name)
    code, out = run([sys.executable, str(BENCH / "score.py"), str(rp),
                     "--bench", bench, "--json", str(sp), "--quiet"])
    if code != 0:
        raise SystemExit(f"채점 실패: {out}")
    res = json.loads(sp.read_text(encoding="utf-8"))
    res["bench"] = bench
    sp.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    return res


def load_baseline() -> dict:
    """{bench: {run, score, ...}}. 예전 단일 형식도 읽어 준다."""
    if not BASELINE.exists():
        return {}
    d = json.loads(BASELINE.read_text(encoding="utf-8"))
    return d if "bench-01" in d or "bench-02" in d else {"bench-01": d}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--score", help="benchmark/runs/<이름>.report.json 을 채점한다")
    ap.add_argument("--promote", help="이 실행 결과를 기준선으로 삼는다")
    ap.add_argument("--bench", default="bench-01", choices=list(BENCHES),
                    help="어느 벤치마크로 채점할지")
    a = ap.parse_args()
    env = {"PYTHONPATH": str(ROOT / "core" / "toolkit")}

    if a.promote:
        p = score_path(a.promote)
        if not p.exists():
            print(f"{p} 가 없다. 먼저 --score {a.promote} 를 돌려라.", file=sys.stderr)
            return 1
        res = json.loads(p.read_text(encoding="utf-8"))
        bench = res.get("bench", a.bench)
        base = load_baseline()
        base[bench] = {"run": a.promote, "score": res["score"],
                       "formula_version": res["formula_version"],
                       "components": res["components"]}
        BASELINE.write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
        avg = sum(b["score"] for b in base.values()) / len(base)
        print(f"기준선 갱신: {bench} = {res['score']:.2f}점 (전체 평균 {avg:.2f})")
        return 0

    print("회귀 게이트\n")
    print("구조")
    ok = True
    ok &= gate("dist/ 가 코어에서 그대로 재생성된다", [sys.executable, "tools/build.py", "--check"])
    ok &= check_single_package()
    ok &= gate("도구상자 시험", [sys.executable, "core/toolkit/tests/test_toolkit.py"], env)
    ok &= check_zip_layout()
    print("\n심판의 심판")
    ok &= gate("채점기 자기시험(공리 확인)", [sys.executable, "benchmark/selftest.py"], env)
    for b in BENCHES:
        ok &= gate(f"{b}이 사양에서 재생성된다",
                   [sys.executable, "benchmark/build.py", "--bench", b], env)

    if a.score:
        rp = RUNS / f"{a.score}.report.json"
        if not rp.exists():
            print(f"\n{rp} 가 없다.", file=sys.stderr)
            return 1
        print(f"\n채점: {a.score}  [{a.bench}]")
        res = score_report(a.score, a.bench)
        code, out = run([sys.executable, str(BENCH / "score.py"), str(rp), "--bench", a.bench])
        print("\n".join("  " + l for l in out.strip().split("\n")))
        all_base = load_baseline()
        base = all_base.get(a.bench)
        if base:
            d = res["score"] - base["score"]
            print(f"\n  {a.bench} 기준선({base['run']}) {base['score']:.2f} → 이번 "
                  f"{res['score']:.2f} ({d:+.2f})")
            others = {k: v["score"] for k, v in all_base.items() if k != a.bench}
            if others:
                avg = (res["score"] + sum(others.values())) / (1 + len(others))
                old = sum(v["score"] for v in all_base.values()) / len(all_base)
                print(f"  전체 평균 {old:.2f} → {avg:.2f}  "
                      f"({', '.join(f'{k} {v:.1f}' for k, v in others.items())} 포함)")
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
            print(f"\n  {a.bench} 기준선이 없다. --promote 로 이 결과를 기준선으로 삼을 수 있다.")

    print()
    print("통과" if ok else "실패 — 위 항목을 고치기 전에는 배포하지 말 것")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
