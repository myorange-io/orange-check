#!/usr/bin/env python3
"""dist/ 를 코어에서 생성한다.

방법론 산문은 `core/methodology/` 한 곳에만 있고, SKILL.md는 여기서 조립한다.
이 저장소가 이전에 겪은 실패가 정확히 그것이었다 — claude-code와 cowork의
SKILL.md가 조용히 갈라져 한쪽에만 있는 규칙이 생겼다.

패키지는 **하나**다. 네 플랫폼이 같은 것을 쓴다. 플랫폼별로 따로 만들어 보니
갈라지는 내용이 273줄 중 30줄뿐이었고 전부 런타임 사실이어서, 스킬이 실행할 때
스스로 확인하도록 옮겼다.

`--check`는 임시 폴더에 다시 지어 committed dist/ 와 바이트 단위로 비교한다.
누가 dist/ 를 직접 고치면 여기서 걸린다.

실행:
  python3 tools/build.py            # dist/ 생성 + zip 패키지
  python3 tools/build.py --check    # 재현 가능한지만 확인 (CI용)
"""
from __future__ import annotations

import argparse
import filecmp
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "core"
PLATFORMS = ROOT / "platforms"
DIST = ROOT / "dist"


# ────────────────────────────────────────────────────── 최소 YAML 판독기

def parse_yaml(text: str):
    """이 저장소가 쓰는 만큼만 읽는다: 스칼라·리스트·중첩 맵·블록 스칼라(|)."""
    lines = text.replace("\t", "  ").split("\n")
    pos = 0

    def indent_of(s: str) -> int:
        return len(s) - len(s.lstrip(" "))

    def scalar(v: str):
        v = v.strip()
        if not v:
            return ""
        if v[0] in "\"'" and v[-1] == v[0] and len(v) > 1:
            return v[1:-1].replace('\\"', '"')
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            return [scalar(x) for x in inner.split(",")] if inner else []
        if v in ("true", "false"):
            return v == "true"
        if re.fullmatch(r"-?\d+", v):
            return int(v)
        return v

    def block(base: int) -> str:
        nonlocal pos
        out = []
        while pos < len(lines):
            ln = lines[pos]
            if ln.strip() and indent_of(ln) < base:
                break
            out.append(ln[base:] if len(ln) >= base else "")
            pos += 1
        while out and not out[-1].strip():
            out.pop()
        return "\n".join(out) + "\n"

    def parse(base: int):
        nonlocal pos
        # 리스트인가?
        while pos < len(lines) and not lines[pos].strip():
            pos += 1
        if pos < len(lines) and lines[pos].lstrip().startswith("- ") and indent_of(lines[pos]) >= base:
            items = []
            lvl = indent_of(lines[pos])
            while pos < len(lines):
                ln = lines[pos]
                if not ln.strip():
                    pos += 1
                    continue
                if indent_of(ln) < lvl or not ln.lstrip().startswith("- "):
                    break
                items.append(scalar(ln.lstrip()[2:]))
                pos += 1
            return items
        out: dict = {}
        while pos < len(lines):
            ln = lines[pos]
            if not ln.strip() or ln.lstrip().startswith("#"):
                pos += 1
                continue
            ind = indent_of(ln)
            if ind < base:
                break
            m = re.match(r"^\s*([\w\-]+):\s*(.*)$", ln)
            if not m:
                pos += 1
                continue
            key, rest = m.group(1), m.group(2).split(" #")[0].strip()
            pos += 1
            if rest == "|":
                out[key] = block(ind + 2)
            elif rest == "":
                out[key] = parse(ind + 1)
            else:
                out[key] = scalar(rest)
        return out

    return parse(0)


# ─────────────────────────────────────────────────── 조각 조립기

COND = re.compile(r"<!--if:([a-z_]+)-->\n(.*?)<!--endif-->\n", re.S)


def apply_flags(text: str, flags: set[str]) -> str:
    """<!--if:flag--> 블록을 걸러낸다."""
    def keep(m):
        return m.group(2) if m.group(1) in flags else ""
    prev = None
    while prev != text:
        prev = text
        text = COND.sub(keep, text)
    return re.sub(r"\n{3,}", "\n\n", text)


def substitute(text: str, prof: dict) -> str:
    return (text
            .replace("{{TOOLKIT}}", prof.get("toolkit_cmd", "scripts -m refver"))
            .replace("{{TOOLKIT_DIR}}", prof.get("toolkit_dir", "scripts")))


def pack_description(segments, limit: int, name: str) -> str:
    """우선순위대로 이어 붙이되 제한을 넘지 않게 자른다. 문장 중간에서 자르지 않는다."""
    if isinstance(segments, str):
        segments = [segments]
    out = ""
    for seg in segments:
        cand = (out + " " + seg).strip() if out else seg
        if len(cand) <= limit:
            out = cand
        else:
            break
    if not out:
        raise SystemExit(
            f"[{name}] description 첫 조각이 {len(segments[0])}자로 제한 {limit}자를 넘는다. "
            "조각을 더 짧게 쪼개라."
        )
    return out


def frontmatter(skill: dict, prof: dict) -> str:
    allow = set(prof.get("frontmatter_allow") or ["name", "description"])
    fields: dict[str, str] = {}
    if "name" in allow:
        fields["name"] = skill["name"]
    if "description" in allow:
        fields["description"] = pack_description(
            skill["description"], int(prof.get("description_max", 1024)), skill["name"])
    if "license" in allow:
        fields["license"] = "MIT"
    for k, v in (prof.get("extra_frontmatter") or {}).items():
        if k in allow:
            fields[k] = v
    lines = ["---"]
    for k, v in fields.items():
        v = str(v).replace("\n", " ").strip()
        if any(ch in v for ch in ':"#') or k == "description":
            v = '"' + v.replace('"', '\\"') + '"'
        lines.append(f"{k}: {v}")
    if "metadata" in allow:
        lines += ["metadata:",
                  f"  runtime-profile: {prof['profile']}",
                  "  suite: orange-check",
                  "  contract: refver-report/1.0"]
    lines.append("---")
    return "\n".join(lines)


def build_skill(skill_dir: Path, prof: dict, out_root: Path) -> Path:
    skill = parse_yaml((skill_dir / "skill.yaml").read_text(encoding="utf-8"))
    flags = set(prof.get("flags") or [])
    name = skill["name"]
    dest = out_root / name
    (dest / "references").mkdir(parents=True, exist_ok=True)

    body = [frontmatter(skill, prof), "", f"# {skill.get('title', name)}", ""]
    if skill.get("intro"):
        body += [substitute(apply_flags(skill["intro"], flags), prof).strip(), ""]
    body += [f"> 실행 환경: {prof['label']}", ""]
    body += ["---", ""]

    for frag in (skill.get("fragments") or []):
        raw = (CORE / "methodology" / f"{frag}.md").read_text(encoding="utf-8")
        body += [substitute(apply_flags(raw, flags), prof).strip(), "", "---", ""]

    refs = skill.get("references") or []
    if refs:
        body += ["## 참고 문서", ""]
        for r in refs:
            src = CORE / "methodology" / f"{r}.md"
            shutil.copyfile(src, dest / "references" / f"{r}.md")
            first = src.read_text(encoding="utf-8").lstrip().split("\n")[0].lstrip("# ")
            body.append(f"- `references/{r}.md` — {first}")
        body.append("")
    if skill.get("outro"):
        body += [substitute(apply_flags(skill["outro"], flags), prof).strip(), ""]

    text = re.sub(r"\n{3,}", "\n\n", "\n".join(body)).rstrip() + "\n"

    # 내보낸 frontmatter를 되읽어 제한을 실제로 지켰는지 확인한다.
    # 이스케이프 때문에 눈으로 센 길이는 실제 값보다 길게 보인다 — 파싱해서 센다.
    emitted = parse_yaml(text.split("---")[1])
    limit = int(prof.get("description_max", 1024))
    if len(str(emitted.get("description", ""))) > limit:
        raise SystemExit(f"[{name}/{prof['profile']}] description이 제한 {limit}자를 넘었다: "
                         f"{len(str(emitted['description']))}자")
    if emitted.get("name") != name:
        raise SystemExit(f"[{name}] frontmatter의 name이 폴더명과 다르다: {emitted.get('name')}")
    stray = set(emitted) - set(prof.get("frontmatter_allow") or [])
    if stray:
        raise SystemExit(f"[{name}/{prof['profile']}] 이 플랫폼이 받지 않는 frontmatter: {sorted(stray)}")

    (dest / "SKILL.md").write_text(text, encoding="utf-8")

    tk = dest / "scripts" / "refver"
    tk.mkdir(parents=True, exist_ok=True)
    for py in sorted((CORE / "toolkit" / "refver").glob("*.py")):
        shutil.copyfile(py, tk / py.name)
    return dest


def build_profile(pf: Path, out_root: Path) -> dict:
    prof = parse_yaml(pf.read_text(encoding="utf-8"))
    root = out_root / "skills"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    built = []
    for sd in sorted((CORE / "skills").iterdir()):
        if (sd / "skill.yaml").exists():
            built.append(build_skill(sd, prof, root).name)
    install = (CORE / "INSTALL.md").read_text(encoding="utf-8")
    install += "\n## 들어 있는 스킬\n\n" + "\n".join(f"- `{b}/`" for b in built) + "\n"
    (root / "INSTALL.md").write_text(install, encoding="utf-8")
    return {"profile": prof["profile"], "label": prof["label"],
            "skills": built, "package": prof.get("package", "both"), "root": root}


def make_zip(info: dict, out_dir: Path) -> list[Path]:
    """zip을 쓰는 플랫폼용 패키지.

    claude.ai 스킬 업로드는 **zip 하나당 스킬 하나**를 기대한다. 압축을 풀면
    SKILL.md를 담은 폴더 하나가 나와야 한다. 여러 스킬을 한 겹 더 감싸 넣으면
    업로드가 되지 않는다. 그래서 스킬마다 따로 만들고,
    지침을 통째로 붙여 쓰는 환경을 위해 묶음 하나를 더 만든다.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    # 스킬별 zip은 업로드로 설치하는 환경에만 필요하다.
    # 폴더째 복사하는 환경(Claude Code·Codex)에는 묶음 하나면 된다.
    if info["package"] in ("zip", "both"):
        for skill in info["skills"]:
            src = info["root"] / skill
            z = out_dir / f"{skill}.zip"
            with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
                for p in sorted(src.rglob("*")):
                    if p.is_file():
                        zf.write(p, str(Path(skill) / p.relative_to(src)))
            made.append(z)
    bundle = out_dir / "orange-check-all.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(info["root"].rglob("*")):
            if p.is_file():
                zf.write(p, str(p.relative_to(info["root"])))
    made.append(bundle)
    return made


def build_all(out_root: Path, quiet: bool = False) -> list[dict]:
    infos = []
    for pf in sorted(PLATFORMS.glob("*.yaml")):
        info = build_profile(pf, out_root)
        zs = make_zip(info, out_root / "packages")
        info["zips"] = zs
        infos.append(info)
        if not quiet:
            n = sum(1 for _ in info["root"].rglob("*") if _.is_file())
            print(f"  {info['profile']:<14} 스킬 {len(info['skills'])}개 · 파일 {n}개"
                  + (f" · zip {len(zs)}개" if zs else ""))
    return infos


def diff_tree(a: Path, b: Path) -> list[str]:
    out = []
    fa = {str(p.relative_to(a)) for p in a.rglob("*") if p.is_file()}
    fb = {str(p.relative_to(b)) for p in b.rglob("*") if p.is_file()}
    out += [f"없어야 할 파일: {x}" for x in sorted(fa - fb)]
    out += [f"빠진 파일: {x}" for x in sorted(fb - fa)]
    for x in sorted(fa & fb):
        if x.endswith(".zip"):
            continue  # zip은 타임스탬프 때문에 바이트가 달라진다
        if not filecmp.cmp(a / x, b / x, shallow=False):
            out.append(f"내용 다름: {x}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="dist/ 가 코어에서 그대로 재생성되는지 확인만 한다")
    a = ap.parse_args()

    if a.check:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d) / "dist"
            build_all(tmp, quiet=True)
            if not DIST.exists():
                print("dist/ 가 없다. 먼저 python3 tools/build.py 를 돌려라.", file=sys.stderr)
                return 1
            diffs = diff_tree(DIST, tmp)
            if diffs:
                print(f"dist/ 가 코어와 어긋난다 — {len(diffs)}건:", file=sys.stderr)
                for x in diffs[:20]:
                    print(f"  - {x}", file=sys.stderr)
                print("\ndist/ 를 직접 고치지 말고 core/ 를 고친 뒤 다시 빌드하라.", file=sys.stderr)
                return 1
            print("dist/ 는 코어에서 그대로 재생성된다.")
            return 0

    print("dist/ 생성")
    if DIST.exists():
        shutil.rmtree(DIST)
    infos = build_all(DIST)
    print(f"\n플랫폼 {len(infos)}종 완료 → {DIST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
