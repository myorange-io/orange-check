#!/usr/bin/env python3
"""벤치마크 빌더 — 사양(spec) + 산문(prose) → 코퍼스 PDF · 벤치마크 docx · 정답표.

이 스크립트가 Layer 0(심판의 심판)의 전부다. 원칙:

  1. 정답은 심어서 만든다. 사양이 유일한 진실이고, 나머지는 전부 여기서 파생된다.
  2. 파생 과정은 자기검증한다. 사실 문장이 PDF에 없거나, 두 번 나오거나,
     금지어가 새어 나오거나, 주장 문장이 문서에 없으면 빌드를 실패시킨다.
     정답표는 "빌드가 성공했다"는 사실만으로 신뢰할 수 있어야 한다.

실행: python3 benchmark/build.py [--bench bench-01]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import unicodedata
import zipfile
from html import escape
from pathlib import Path

import fitz  # PyMuPDF

ROOT = Path(__file__).resolve().parent
PAGE_W, PAGE_H = 595.0, 842.0
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 62.0, 64.0, 62.0
LINE_H = 15.6
FS_BODY = 10.5
FS_HEAD = 12.5
FS_TITLE = 15.0
FS_MARK = 7.6
FONT_KR = "korea"
FONT_EN = "helv"

FAILURES: list[str] = []


def fail(msg: str) -> None:
    FAILURES.append(msg)
    print(f"  ✗ {msg}", file=sys.stderr)


def norm(s: str) -> str:
    """공백을 전부 제거해 줄바꿈 위치와 무관하게 문자열을 비교한다."""
    s = unicodedata.normalize("NFC", s)
    return re.sub(r"\s+", "", s)


# ────────────────────────────────────────────────────────────── PDF 렌더링

def wrap(text: str, font: str, size: float, max_w: float) -> list[str]:
    """한글(공백 없이 이어짐)과 영문(단어 단위)을 모두 처리하는 탐욕적 줄바꿈."""
    out: list[str] = []
    line = ""
    i = 0
    while i < len(text):
        ch = text[i]
        trial = line + ch
        if fitz.get_text_length(trial, fontname=font, fontsize=size) > max_w and line:
            # 영문 단어 중간이면 마지막 공백까지 되감는다.
            if ch.isalnum() and ch.isascii() and " " in line.rstrip():
                cut = line.rstrip().rfind(" ")
                if cut > len(line) * 0.4:
                    out.append(line[:cut])
                    line = line[cut + 1:] + ch
                    i += 1
                    continue
            out.append(line)
            line = ch
        else:
            line = trial
        i += 1
    if line:
        out.append(line)
    return out


class PdfWriter:
    """한 줄씩 고정 위치에 찍고, 찍은 줄 번호를 그대로 기록한다.

    추출 순서(page.get_text())가 삽입 순서와 일치함을 build 마지막에 재확인한다.
    """

    def __init__(self, watermark: str, body_font: str) -> None:
        self.doc = fitz.open()
        self.wm = watermark
        self.font = body_font
        self.page = None
        self.y = 0.0
        self.lineno = 0
        self.pageno = 0
        # (pageno, lineno) -> 텍스트, 그리고 페이지별 평문
        self.page_lines: dict[int, list[str]] = {}
        self._new_page()

    def _new_page(self) -> None:
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.pageno += 1
        self.lineno = 0
        self.page_lines[self.pageno] = []
        self.y = MARGIN_TOP
        self._raw(self.wm, FONT_KR, 7.2, color=(0.45, 0.45, 0.45))
        self.y += 6.0

    def _raw(self, text: str, font: str, size: float, color=(0, 0, 0)) -> int:
        self.page.insert_text((MARGIN_X, self.y), text, fontname=font, fontsize=size, color=color)
        self.lineno += 1
        self.page_lines[self.pageno].append(text)
        self.y += LINE_H
        return self.lineno

    def _ensure(self, need: float = LINE_H) -> None:
        if self.y + need > PAGE_H - MARGIN_BOTTOM:
            self._new_page()

    def block(self, text: str, size: float = FS_BODY, indent: bool = True) -> list[tuple[int, int]]:
        """문단을 쓰고 [(page, line), ...] 좌표 목록을 돌려준다."""
        width = PAGE_W - 2 * MARGIN_X
        body = ("  " + text) if indent else text
        coords = []
        for ln in wrap(body, self.font, size, width):
            self._ensure()
            coords.append((self.pageno, self._raw(ln, self.font, size)))
        self.y += 3.4
        return coords

    def heading(self, text: str) -> None:
        self._ensure(LINE_H * 2)
        self.y += 6.0
        self._ensure()
        self._raw(text, self.font, FS_HEAD)
        self.y += 2.6

    def title(self, text: str, subtitle: str = "") -> None:
        self._raw(text, self.font, FS_TITLE)
        if subtitle:
            self._raw(subtitle, self.font, FS_BODY, color=(0.3, 0.3, 0.3))
        self.y += 10.0

    def save(self, path: Path) -> None:
        self.doc.save(str(path), garbage=3, deflate=True)


def build_source_pdf(src: dict, prose: dict, watermark: str, out: Path) -> dict:
    font = FONT_EN if src.get("language") == "en" else FONT_KR
    w = PdfWriter(watermark, font)
    m = src["meta"]
    sub = " · ".join(x for x in [m.get("publisher"), m.get("series"), m.get("date")] if x)
    w.title(m["title"], sub)
    for sec in prose["sections"]:
        w.heading(sec["heading"])
        for para in sec["paragraphs"]:
            w.block(para)
    w.save(out)

    # 재추출로 삽입 순서 == 추출 순서 확인
    doc = fitz.open(str(out))
    pages: dict[int, list[str]] = {}
    for i in range(doc.page_count):
        lines = [l for l in doc[i].get_text().split("\n")]
        while lines and not lines[-1].strip():
            lines.pop()
        pages[i + 1] = lines
    for pno, expected in w.page_lines.items():
        got = pages.get(pno, [])
        if [x for x in got] != [x for x in expected]:
            fail(f"{src['id']}: p{pno} 렌더링 순서 불일치 (삽입 {len(expected)}줄 / 추출 {len(got)}줄)")
            break
    return pages


def flat_index(pages: dict[int, list[str]]) -> tuple[str, list[tuple[int, int]]]:
    """문서 전체를 공백 없는 한 줄로 잇고, 각 문자의 (page, line)을 기록한다.

    각 페이지 1행은 워터마크이므로 색인에서 제외한다. 그러지 않으면
    페이지를 넘나드는 문장 한가운데 워터마크가 끼어들어 매칭이 끊긴다.
    행 번호는 워터마크를 포함한 실제 번호를 그대로 쓴다 — PDF를 열어 센 값과 같아야 한다.
    """
    flat: list[str] = []
    idx: list[tuple[int, int]] = []
    for pno in sorted(pages):
        for lineno, line in enumerate(pages[pno], 1):
            if lineno == 1:  # 워터마크
                continue
            for ch in norm(line):
                flat.append(ch)
                idx.append((pno, lineno))
    return "".join(flat), idx


def locate(pages: dict[int, list[str]], sentence: str) -> list[dict]:
    """문장이 등장하는 위치 목록. 공백 무시 매칭, 페이지 경계를 넘어도 찾는다."""
    flat, idx = flat_index(pages)
    target = norm(sentence)
    hits = []
    start = flat.find(target)
    while start != -1:
        p0, l0 = idx[start]
        p1, l1 = idx[start + len(target) - 1]
        hits.append({"page": p0, "line_start": l0, "page_end": p1, "line_end": l1})
        start = flat.find(target, start + 1)
    return hits


def count_occurrences(pages: dict[int, list[str]], needle: str) -> int:
    flat, _ = flat_index(pages)
    return flat.count(norm(needle))


# ────────────────────────────────────────────────────────────── docx 작성

NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)


def run(text: str, *, sup: bool = False, bold: bool = False, size: int | None = None) -> str:
    props = ""
    if bold:
        props += "<w:b/>"
    if size:
        props += f'<w:sz w:val="{size}"/>'
    if sup:
        props += '<w:vertAlign w:val="superscript"/>'
    rpr = f"<w:rPr>{props}</w:rPr>" if props else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def note_ref(kind: str, nid: int) -> str:
    tag = "footnoteReference" if kind == "footnote" else "endnoteReference"
    return (
        f'<w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr>'
        f'<w:{tag} w:id="{nid}"/></w:r>'
    )


def para(inner: str, style: str = "") -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}{inner}</w:p>"


def format_ref(meta: dict) -> str:
    bits = [meta.get("authors", ""), f"({meta.get('year','')})", meta.get("title", "")]
    for k in ("journal", "volume", "issue", "pages", "series", "publisher", "date"):
        v = meta.get(k)
        if not v:
            continue
        if k == "volume":
            bits.append(f"제{v}권")
        elif k == "issue":
            bits.append(f"제{v}호")
        elif k == "pages":
            bits.append(f"pp.{v}")
        else:
            bits.append(str(v))
    return ", ".join(b for b in bits if b).replace(", (", " (")


def inline_marker(meta: dict) -> str:
    return f"({meta.get('authors','')}, {meta.get('year','')})"


def build_docx(spec: dict, doc_prose: dict, out: Path) -> dict:
    """OOXML을 직접 조립한다. python-docx는 각주/미주를 쓰지 못하기 때문."""
    src_by_id = {s["id"]: s for s in spec["sources"]}
    cit_by_id = {c["id"]: c for c in spec["citations"]}

    def cited_meta(c: dict) -> dict:
        if c.get("fabricated_source"):
            return dict(c["fabricated_source"])
        m = dict(src_by_id[c["cites"]]["meta"])
        m.update(c.get("cited_meta_override") or {})
        return m

    body: list[str] = []
    footnotes: list[tuple[int, str]] = []
    endnotes: list[tuple[int, str]] = []
    fn_id, en_id = 1, 1
    note_map: dict[str, tuple[str, int]] = {}
    placed: set[str] = set()

    body.append(para(run(spec["document"]["title"], bold=True, size=32)))
    body.append(para(run(f"{spec['document']['author']} · {spec['document']['date']}", size=20)))

    for sec in doc_prose["sections"]:
        body.append(para(run(sec["heading"], bold=True, size=26)))
        for blk in sec["blocks"]:
            text = blk["text"]
            runs: list[str] = []
            cursor = 0
            for cid in blk.get("citation_ids", []):
                c = cit_by_id.get(cid)
                if c is None:
                    fail(f"문서 산문이 알 수 없는 인용 id를 참조: {cid}")
                    continue
                pos = text.find(c["claim"], cursor)
                if pos == -1:
                    continue  # 검증 단계에서 별도로 잡는다
                end = pos + len(c["claim"])
                runs.append(run(text[cursor:end]))
                meta = cited_meta(c)
                if c["placement"] == "body":
                    runs.append(run(inline_marker(meta)))
                elif c["placement"] == "footnote":
                    runs.append(note_ref("footnote", fn_id))
                    footnotes.append((fn_id, format_ref(meta)))
                    note_map[cid] = ("footnote", fn_id)
                    fn_id += 1
                else:
                    runs.append(note_ref("endnote", en_id))
                    endnotes.append((en_id, format_ref(meta)))
                    note_map[cid] = ("endnote", en_id)
                    en_id += 1
                placed.add(cid)
                cursor = end
            runs.append(run(text[cursor:]))
            body.append(para("".join(runs)))

    # 참고문헌 — 본문 인용 출처만(각주·미주 출처는 노트에만 존재해 전수 추출을 시험한다)
    body.append(para(run("참고문헌", bold=True, size=26)))
    rels: list[str] = []
    rid = 100
    seen: set[str] = set()
    for c in spec["citations"]:
        if c["placement"] != "body":
            continue
        meta = cited_meta(c)
        key = format_ref(meta)
        if key in seen:
            continue
        seen.add(key)
        url = meta.get("url")
        if url:
            rid += 1
            rels.append(
                f'<Relationship Id="rId{rid}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
                f'Target="{escape(url)}" TargetMode="External"/>'
            )
            link = f'<w:hyperlink r:id="rId{rid}">{run(url)}</w:hyperlink>'
            body.append(para(run(f"· {key} ") + link))
        else:
            body.append(para(run(f"· {key}")))

    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<w:document {NS}><w:body>{''.join(body)}"
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>'
        "</w:body></w:document>"
    )

    def notes_xml(kind: str, items: list[tuple[int, str]]) -> str:
        root = "footnotes" if kind == "footnote" else "endnotes"
        el = "footnote" if kind == "footnote" else "endnote"
        seps = (
            f'<w:{el} w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:{el}>'
            f'<w:{el} w:type="continuationSeparator" w:id="0"><w:p><w:r><w:continuationSeparator/></w:r></w:p></w:{el}>'
        )
        parts = "".join(f'<w:{el} w:id="{i}">{para(run(t))}</w:{el}>' for i, t in items)
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f"<w:{root} {NS}>{seps}{parts}</w:{root}>"
        )

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/footnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/>'
        '<Override PartName="/word/endnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml"/>'
        '<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    doc_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes" Target="footnotes.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes" Target="endnotes.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>'
        + "".join(rels) +
        "</Relationships>"
    )
    settings = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:settings {NS}><w:footnotePr><w:footnote w:id="-1"/><w:footnote w:id="0"/></w:footnotePr>'
        '<w:endnotePr><w:endnote w:id="-1"/><w:endnote w:id="0"/></w:endnotePr></w:settings>'
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("word/document.xml", document)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        z.writestr("word/footnotes.xml", notes_xml("footnote", footnotes))
        z.writestr("word/endnotes.xml", notes_xml("endnote", endnotes))
        z.writestr("word/settings.xml", settings)

    missing = [c["id"] for c in spec["citations"] if c["id"] not in placed]
    for cid in missing:
        fail(f"주장 문장이 문서에 배치되지 않음: {cid}")
    return note_map


def docx_text(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as z:
        parts = {}
        for name in ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml"):
            try:
                raw = z.read(name).decode("utf-8")
            except KeyError:
                raw = ""
            txt = re.sub(r"<[^>]+>", "", raw)
            parts[name] = txt
    return parts


# ─────────────────────────────────────────────────────────── 반칙 방지 점검

def overlap_score(claim: str, evidence: str) -> int:
    """주장과 근거 문장의 최장 공통 연속 부분열 길이(숫자·문장부호 제외).

    값이 크면 본문이 출처를 그대로 베낀 것이므로, 문자열 일치만으로
    정답을 맞힐 수 있는 반칙 경로가 생긴다.
    """
    a = re.sub(r"[\d\s.,%()~·\-–—:;]", "", unicodedata.normalize("NFC", claim))
    b = re.sub(r"[\d\s.,%()~·\-–—:;]", "", unicodedata.normalize("NFC", evidence))
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


# ─────────────────────────────────────────────────────────────────── main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", default="bench-01")
    ap.add_argument("--overlap-limit", type=int, default=14,
                    help="주장·근거 최장 공통 연속 부분열 허용 상한(자)")
    args = ap.parse_args()

    spec = json.loads((ROOT / "spec" / f"{args.bench}.spec.json").read_text(encoding="utf-8"))
    prose_dir = ROOT / "spec" / "prose"
    watermark = spec["world"]["watermark"]

    corpus_dir = ROOT / "corpus"
    if corpus_dir.exists():
        shutil.rmtree(corpus_dir)
    corpus_dir.mkdir(parents=True)

    print("── 코퍼스 PDF 렌더링")
    fact_loc: dict[str, dict] = {}
    manifest = {"world": spec["world"]["name"], "closed_world_rule": spec["closed_world_rule"], "sources": []}
    page_cache: dict[str, dict[int, list[str]]] = {}

    for src in spec["sources"]:
        pf = prose_dir / f"{src['id']}.json"
        if not pf.exists():
            fail(f"{src['id']}: 산문 파일 없음 ({pf})")
            continue
        prose = json.loads(pf.read_text(encoding="utf-8"))
        pdf_path = corpus_dir / f"{src['id']}.pdf"
        pages = build_source_pdf(src, prose, watermark, pdf_path)
        page_cache[src["id"]] = pages

        for f in src["facts"]:
            hits = locate(pages, f["sentence"])
            if len(hits) != 1:
                fail(f"{src['id']}/{f['fid']}: 사실 문장이 {len(hits)}회 등장(1회여야 함)")
                continue
            fact_loc[f["fid"]] = {
                "source_id": src["id"], "file": f"{src['id']}.pdf",
                **hits[0], "sentence": f["sentence"],
            }
        for bad in src.get("must_not_contain", []):
            n = count_occurrences(pages, bad)
            if n:
                fail(f"{src['id']}: 금지어 '{bad}'가 {n}회 누출됨")

        manifest["sources"].append({
            "id": src["id"], "file": f"{src['id']}.pdf", "tier": src["tier"],
            "kind": src["kind"], "pages": len(pages), **{"meta": src["meta"]},
        })
        print(f"  {src['id']}  {len(pages)}p  facts={len(src['facts'])}  {pdf_path.name}")

    (corpus_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("── 벤치마크 문서 조립")
    doc_prose = json.loads((prose_dir / f"{args.bench}.doc.json").read_text(encoding="utf-8"))
    docx_path = ROOT / "docs" / f"{args.bench}.docx"
    note_map = build_docx(spec, doc_prose, docx_path)

    parts = docx_text(docx_path)
    whole = norm("".join(parts.values()))
    for c in spec["citations"]:
        n = whole.count(norm(c["claim"]))
        if n != 1:
            fail(f"{c['id']}: 주장 문장이 문서에 {n}회 등장(1회여야 함)")

    print("── 반칙 방지 점검(주장·근거 문자열 겹침)")
    worst = []
    for c in spec["citations"]:
        fid = c.get("evidence_fid")
        if not fid or fid not in fact_loc:
            continue
        ov = overlap_score(c["claim"], fact_loc[fid]["sentence"])
        worst.append((ov, c["id"]))
        if ov > args.overlap_limit:
            fail(f"{c['id']}: 주장이 출처 문장과 {ov}자 연속 일치 — 패러프레이즈 필요(상한 {args.overlap_limit})")
    worst.sort(reverse=True)
    print("  최대 겹침:", ", ".join(f"{cid}={ov}" for ov, cid in worst[:5]))

    print("── 정답표 생성")
    key = {
        "bench_id": spec["bench_id"],
        "spec_version": spec["spec_version"],
        "document": f"docs/{args.bench}.docx",
        "corpus": "corpus/",
        "watermark": watermark,
        "closed_world_rule": spec["closed_world_rule"],
        "planted_taxonomy": spec["planted_taxonomy"],
        "totals": {},
        "citations": [],
    }
    src_by_id = {s["id"]: s for s in spec["sources"]}
    for c in spec["citations"]:
        meta = dict(c["fabricated_source"]) if c.get("fabricated_source") else dict(src_by_id[c["cites"]]["meta"])
        if c.get("cited_meta_override"):
            meta.update(c["cited_meta_override"])
        ev = fact_loc.get(c.get("evidence_fid") or "")
        entry = {
            "id": c["id"],
            "anchor": norm(c["claim"]),
            "claim": c["claim"],
            "placement": c["placement"],
            "note": note_map.get(c["id"]),
            "cited_as": meta,
            "true_source_id": c.get("cites"),
            "planted": c["planted"],
            "slots": c["slots"],
            "expected": c["expected"],
            "evidence": ev,
            "mismatch_fields": c.get("mismatch_fields", []),
            "absence_evidence": c.get("absence_evidence", []),
            "rationale": c.get("rationale", ""),
        }
        key["citations"].append(entry)

    from collections import Counter
    key["totals"] = {
        "citations": len(spec["citations"]),
        "planted": sum(1 for c in spec["citations"] if c["planted"] != "none"),
        "control": sum(1 for c in spec["citations"] if c["planted"] == "none"),
        "by_pattern": dict(Counter(c["planted"] for c in spec["citations"])),
        "by_placement": dict(Counter(c["placement"] for c in spec["citations"])),
    }
    (ROOT / "answer-key.json").write_text(
        json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    if FAILURES:
        print(f"빌드 실패 — {len(FAILURES)}건의 위반. 정답표를 신뢰할 수 없다.", file=sys.stderr)
        return 1
    print(f"빌드 성공: 인용 {key['totals']['citations']}건 "
          f"(심은 오류 {key['totals']['planted']} / 대조군 {key['totals']['control']})")
    print(f"  코퍼스 {len(manifest['sources'])}종 → {corpus_dir}")
    print(f"  문서 → {docx_path}")
    print(f"  정답표 → {ROOT / 'answer-key.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
