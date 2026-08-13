"""검증 대상 문서 판독 — docx · pdf · hwp · hwpx · txt/md.

이 단계에서 하나라도 놓치면 그 인용은 영원히 검증되지 않는다. 그래서
본문만이 아니라 **각주·미주·하이퍼링크**까지 전수로 꺼낸다. 실제 문서에서
인용의 상당수는 각주에만 있고 참고문헌 목록에는 없다.
"""
from __future__ import annotations

import os
import re

from .hwp import Unit, read_hangul
from . import safexml

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


# ─────────────────────────────────────────────────────────────────── docx

def read_docx(path: str) -> list[Unit]:
    units: list[Unit] = []
    with safexml.open_zip(path) as z:
        names = set(z.namelist())

        rels: dict[str, str] = {}
        if "word/_rels/document.xml.rels" in names:
            root = safexml.fromstring(z.read("word/_rels/document.xml.rels"))
            for rel in root:
                if rel.get("TargetMode") == "External":
                    rels[rel.get("Id")] = rel.get("Target")

        def paragraphs(xml: bytes, part: str, id_attr: str | None = None):
            root = safexml.fromstring(xml)
            idx = 0
            container = root if id_attr is None else None
            groups = [(None, root)] if container is not None else [
                (el.get(f"{W}id"), el) for el in root
                if el.tag in (f"{W}footnote", f"{W}endnote")
                and el.get(f"{W}type") is None
            ]
            for note_id, scope in groups:
                for p in scope.iter(f"{W}p"):
                    text = "".join(t.text or "" for t in p.iter(f"{W}t"))
                    links = [rels[h.get(f"{R}id")] for h in p.iter(f"{W}hyperlink")
                             if h.get(f"{R}id") in rels]
                    notes = _docx_note_refs(p) if part == "body" else []
                    if not text.strip() and not links:
                        continue
                    idx += 1
                    meta = {}
                    if links:
                        meta["hyperlinks"] = links
                    if notes:
                        meta["notes"] = notes
                    units.append(Unit(text=text.strip(), part=part, index=idx,
                                      note_id=note_id, meta=meta))

        if "word/document.xml" in names:
            paragraphs(z.read("word/document.xml"), "body")
        if "word/footnotes.xml" in names:
            paragraphs(z.read("word/footnotes.xml"), "footnote", id_attr=f"{W}id")
        if "word/endnotes.xml" in names:
            paragraphs(z.read("word/endnotes.xml"), "endnote", id_attr=f"{W}id")
    return units


def _docx_note_refs(para) -> list[dict]:
    """각주·미주 표시가 문단의 **어느 글자 위치**에 붙어 있는지 찾는다.

    이게 없으면 각주가 그 문단 어디에 달렸는지 알 수 없다. 문단 끝에 달린
    것처럼 보여서, 실제로는 첫 문장에 달린 각주를 통째로 놓치게 된다.
    실측에서 이 때문에 인용 두 건을 놓쳤다.
    """
    out, pos = [], 0
    for node in para.iter():
        tag = node.tag
        if tag == f"{W}t":
            pos += len(node.text or "")
        elif tag in (f"{W}footnoteReference", f"{W}endnoteReference"):
            out.append({
                "kind": "footnote" if tag.endswith("footnoteReference") else "endnote",
                "id": node.get(f"{W}id"),
                "after_chars": pos,
            })
    return out


# ──────────────────────────────────────────────────────────────────── pdf

def read_pdf(path: str) -> list[Unit]:
    from .pdf import page_lines
    units: list[Unit] = []
    idx = 0
    for pno, lines in page_lines(path).items():
        for lno, line in enumerate(lines, 1):
            if not line.strip():
                continue
            idx += 1
            units.append(Unit(text=line.strip(), part="body", index=idx,
                              page=pno, line=lno))
    return units


# ──────────────────────────────────────────────────────────────────── 기타

def read_text(path: str) -> list[Unit]:
    raw = open(path, encoding="utf-8", errors="replace").read()
    return [Unit(text=p.strip(), part="body", index=i)
            for i, p in enumerate(re.split(r"\n\s*\n", raw), 1) if p.strip()]


READERS = {
    ".docx": read_docx, ".docm": read_docx,
    ".pdf": read_pdf,
    ".hwp": read_hangul, ".hwpx": read_hangul, ".hml": read_hangul,
    ".txt": read_text, ".md": read_text,
}


def read_document(path: str) -> list[Unit]:
    ext = os.path.splitext(path)[1].lower()
    fn = READERS.get(ext)
    if fn is None:
        raise ValueError(
            f"지원하지 않는 형식이다: {ext or path}. "
            f"지원 형식: {', '.join(sorted(READERS))}"
        )
    return fn(path)


def summarize(units: list[Unit]) -> dict:
    out: dict[str, int] = {}
    for u in units:
        out[u.part] = out.get(u.part, 0) + 1
    return out
