"""HWPX·HWP 5.x 판독 — 표준 라이브러리만 쓴다.

네 개 런타임 중 ChatGPT 코드 인터프리터는 네트워크가 없어 `pip install`이
불가능하다. 그래서 한글 문서 판독은 의존성 없이 되어야 한다.

세 갈래로 처리한다.

  HWPX      ZIP + OWPML XML. 어디서나 된다. 각주·미주도 분리해 낸다.
  HWP 5.x   OLE2 복합문서 + 레코드 순회. 어디서나 되지만 각주 귀속은 근사다.
  rhwp      설치돼 있으면 고정밀 경로. `export-pdf`로 PDF를 얻으면
            페이지·행 핀포인트가 한글 뷰어에서 보는 쪽수와 맞는다.

rhwp 하위 명령은 `rhwp capabilities`로 알아낸다. 이 도구가 스스로를
기술하도록 만들어져 있으므로, 명령 이름을 넘겨짚지 않는다.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import struct
import subprocess
import zipfile
import zlib
from dataclasses import dataclass, field

# ────────────────────────────────────────────────────────────────── 공통

@dataclass
class Unit:
    """문서에서 뽑아낸 텍스트 한 덩이와 그 위치."""
    text: str
    part: str = "body"          # body | footnote | endnote | table | header | bibliography
    index: int = 0              # 같은 part 안에서의 순번
    note_id: str | None = None  # 각주·미주 번호
    page: int | None = None     # PDF 경유일 때만 채워진다
    line: int | None = None
    meta: dict = field(default_factory=dict)


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


# ───────────────────────────────────────────────────────────────── HWPX

# OWPML은 개정에 따라 접두사·요소명이 조금씩 달라진다. 이름공간을 고정하지 않고
# 지역명(local name)만 보고 훑는다 — 개정판이 바뀌어도 깨지지 않는다.
_TEXT_TAGS = {"t"}
_PARA_TAGS = {"p"}
_NOTE_HINT = re.compile(r"(footnote|endnote|footnt|endnt)", re.I)


def read_hwpx(path: str) -> list[Unit]:
    """HWPX(ZIP+OWPML)를 읽어 본문·각주·미주로 나눈다."""
    from . import safexml

    units: list[Unit] = []
    counters = {"body": 0, "footnote": 0, "endnote": 0}

    with safexml.open_zip(path) as z:
        names = [n for n in z.namelist()
                 if re.search(r"Contents/section\d+\.xml$", n, re.I)]
        if not names:
            names = [n for n in z.namelist() if n.lower().endswith(".xml")
                     and "section" in n.lower()]
        names.sort(key=lambda n: int(re.search(r"section(\d+)", n, re.I).group(1))
                   if re.search(r"section(\d+)", n, re.I) else 0)

        for name in names:
            root = safexml.fromstring(z.read(name))

            def walk(el, part: str, note_id: str | None):
                tag = _localname(el.tag)
                if _NOTE_HINT.search(tag):
                    kind = "endnote" if "end" in tag.lower() else "footnote"
                    nid = el.get("number") or el.get("instId") or el.get("id")
                    for ch in el:
                        walk(ch, kind, nid)
                    return
                if tag in _PARA_TAGS:
                    text = "".join(
                        (n.text or "") for n in el.iter()
                        if _localname(n.tag) in _TEXT_TAGS
                        and not _has_note_ancestor(el, n)
                    )
                    if text.strip():
                        counters[part] = counters.get(part, 0) + 1
                        units.append(Unit(text=text.strip(), part=part,
                                          index=counters[part], note_id=note_id,
                                          meta={"section": name}))
                    # 문단 안에 매달린 각주는 따로 훑는다
                    for n in el.iter():
                        if n is el:
                            continue
                        if _NOTE_HINT.search(_localname(n.tag)):
                            walk(n, part, note_id)
                    return
                for ch in el:
                    walk(ch, part, note_id)

            walk(root, "body", None)

    return units


def _has_note_ancestor(para, node) -> bool:
    """문단 텍스트를 모을 때 각주 안 글자는 빼기 위한 판정."""
    stack = [(para, False)]
    while stack:
        el, inside = stack.pop()
        if el is node:
            return inside
        nxt = inside or bool(_NOTE_HINT.search(_localname(el.tag)))
        for ch in el:
            stack.append((ch, nxt))
    return False


# ────────────────────────────────────────────── OLE2 복합문서 최소 판독기

class Cfb:
    """HWP 5.x가 담겨 있는 OLE2 복합문서를 표준 라이브러리만으로 연다."""

    SIG = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

    def __init__(self, data: bytes) -> None:
        if data[:8] != self.SIG:
            raise ValueError("OLE2 복합문서가 아니다")
        self.d = data
        self.ssz = 1 << struct.unpack_from("<H", data, 30)[0]
        self.mssz = 1 << struct.unpack_from("<H", data, 32)[0]
        n_fat = struct.unpack_from("<I", data, 44)[0]
        self.dir_start = struct.unpack_from("<I", data, 48)[0]
        self.mini_cutoff = struct.unpack_from("<I", data, 56)[0]
        mini_fat_start = struct.unpack_from("<I", data, 60)[0]
        n_mini_fat = struct.unpack_from("<I", data, 64)[0]
        difat_start = struct.unpack_from("<I", data, 68)[0]
        n_difat = struct.unpack_from("<I", data, 72)[0]

        difat = list(struct.unpack_from("<109I", data, 76))
        sec, guard = difat_start, 0
        while sec not in (0xFFFFFFFE, 0xFFFFFFFF) and guard < n_difat + 8:
            blk = self._sector(sec)
            per = self.ssz // 4 - 1
            difat += list(struct.unpack_from(f"<{per}I", blk, 0))
            sec = struct.unpack_from("<I", blk, self.ssz - 4)[0]
            guard += 1

        self.fat: list[int] = []
        for s in difat[:n_fat]:
            if s in (0xFFFFFFFE, 0xFFFFFFFF):
                continue
            blk = self._sector(s)
            self.fat += list(struct.unpack_from(f"<{self.ssz // 4}I", blk, 0))

        self.minifat: list[int] = []
        for blk in self._chain_blocks(mini_fat_start, n_mini_fat * self.ssz):
            self.minifat += list(struct.unpack_from(f"<{self.ssz // 4}I", blk, 0))

        self.entries = self._read_dir()
        root = self.entries[0]
        self.ministream = self._read_fat(root["start"], root["size"])

    def _sector(self, n: int) -> bytes:
        off = (n + 1) * self.ssz
        return self.d[off:off + self.ssz]

    def _chain_blocks(self, start: int, limit: int):
        sec, got, guard = start, 0, 0
        while sec not in (0xFFFFFFFE, 0xFFFFFFFF) and got < limit and guard < 1 << 22:
            yield self._sector(sec)
            got += self.ssz
            sec = self.fat[sec] if sec < len(self.fat) else 0xFFFFFFFE
            guard += 1

    def _read_fat(self, start: int, size: int) -> bytes:
        out = b"".join(self._chain_blocks(start, size + self.ssz))
        return out[:size]

    def _read_mini(self, start: int, size: int) -> bytes:
        out, sec, guard = b"", start, 0
        while sec not in (0xFFFFFFFE, 0xFFFFFFFF) and len(out) < size and guard < 1 << 22:
            off = sec * self.mssz
            out += self.ministream[off:off + self.mssz]
            sec = self.minifat[sec] if sec < len(self.minifat) else 0xFFFFFFFE
            guard += 1
        return out[:size]

    def _read_dir(self) -> list[dict]:
        raw = b""
        sec, guard = self.dir_start, 0
        while sec not in (0xFFFFFFFE, 0xFFFFFFFF) and guard < 1 << 20:
            raw += self._sector(sec)
            sec = self.fat[sec] if sec < len(self.fat) else 0xFFFFFFFE
            guard += 1
        out = []
        for i in range(len(raw) // 128):
            e = raw[i * 128:(i + 1) * 128]
            nlen = struct.unpack_from("<H", e, 64)[0]
            name = e[:max(0, nlen - 2)].decode("utf-16-le", "ignore")
            out.append({
                "name": name, "type": e[66],
                "left": struct.unpack_from("<I", e, 68)[0],
                "right": struct.unpack_from("<I", e, 72)[0],
                "child": struct.unpack_from("<I", e, 76)[0],
                "start": struct.unpack_from("<I", e, 116)[0],
                "size": struct.unpack_from("<Q", e, 120)[0],
            })
        return out

    def paths(self) -> dict[str, dict]:
        """'BodyText/Section0' 같은 전체 경로 -> 디렉터리 항목."""
        out: dict[str, dict] = {}

        def walk_sib(idx: int, prefix: str) -> None:
            if idx in (0xFFFFFFFF, 0xFFFFFFFE) or idx >= len(self.entries):
                return
            e = self.entries[idx]
            walk_sib(e["left"], prefix)
            p = f"{prefix}{e['name']}"
            if e["type"] == 2:
                out[p] = e
            elif e["type"] == 1:
                walk_sib(e["child"], p + "/")
            walk_sib(e["right"], prefix)

        root = self.entries[0]
        walk_sib(root["child"], "")
        return out

    def read(self, entry: dict) -> bytes:
        if entry["size"] < self.mini_cutoff:
            return self._read_mini(entry["start"], entry["size"])
        return self._read_fat(entry["start"], entry["size"])


# ──────────────────────────────────────────────────────── HWP 5.x 레코드

HWPTAG_BEGIN = 0x10
TAG_PARA_TEXT = HWPTAG_BEGIN + 51
TAG_CTRL_HEADER = HWPTAG_BEGIN + 71

# 문단 텍스트 안의 제어문자. 확장·인라인 제어는 자기 자신을 포함해
# UTF-16 부호단위 8개를 차지한다. 나머지는 한 개다.
_CTRL_WIDE = {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}
_CTRL_ONE = {10, 13, 24, 25, 26, 27, 28, 29, 30, 31, 0}


def _records(buf: bytes):
    i, n = 0, len(buf)
    while i + 4 <= n:
        (h,) = struct.unpack_from("<I", buf, i)
        tag = h & 0x3FF
        level = (h >> 10) & 0x3FF
        size = (h >> 20) & 0xFFF
        i += 4
        if size == 0xFFF:
            if i + 4 > n:
                return
            (size,) = struct.unpack_from("<I", buf, i)
            i += 4
        yield tag, level, buf[i:i + size]
        i += size


def _para_text(data: bytes) -> str:
    out, i, n = [], 0, len(data) // 2
    for _ in range(n):
        if i >= n:
            break
        (c,) = struct.unpack_from("<H", data, i * 2)
        if c in _CTRL_WIDE:
            i += 8
            continue
        if c in _CTRL_ONE:
            out.append("\n" if c in (10, 13) else "")
            i += 1
            continue
        out.append(chr(c))
        i += 1
    return "".join(out)


def read_hwp5(path: str) -> list[Unit]:
    """HWP 5.x 이진 파일에서 문단 텍스트를 뽑는다.

    각주·미주는 CTRL_HEADER의 컨트롤 id와 레코드 level 중첩으로 근사한다.
    정확한 귀속이 필요하면 HWPX로 저장하거나 rhwp를 쓰라.
    """
    data = open(path, "rb").read()
    cfb = Cfb(data)
    paths = cfb.paths()

    head = next((v for k, v in paths.items() if k.lower().endswith("fileheader")), None)
    compressed, encrypted = True, False
    if head:
        fh = cfb.read(head)
        if len(fh) >= 40:
            flags = struct.unpack_from("<I", fh, 36)[0]
            compressed = bool(flags & 1)
            encrypted = bool(flags & 2)
    if encrypted:
        raise ValueError("암호가 걸린 HWP 파일이다 — 암호를 풀고 다시 시도하라")

    secs = sorted(
        [(k, v) for k, v in paths.items() if re.search(r"bodytext/section(\d+)$", k, re.I)],
        key=lambda kv: int(re.search(r"section(\d+)$", kv[0], re.I).group(1)),
    )
    if not secs:
        raise ValueError("BodyText/Section 스트림을 찾지 못했다 — HWP 5.x가 아닐 수 있다")

    units: list[Unit] = []
    counters = {"body": 0, "footnote": 0, "endnote": 0}

    for name, ent in secs:
        raw = cfb.read(ent)
        if compressed:
            try:
                raw = zlib.decompress(raw, -15)
            except zlib.error:
                raw = zlib.decompress(raw)
        note_kind, note_level, note_id = None, -1, 0
        for tag, level, body in _records(raw):
            if tag == TAG_CTRL_HEADER and len(body) >= 4:
                cid = body[:4][::-1].decode("ascii", "ignore").strip()
                if cid in ("fn", "en"):
                    note_kind = "footnote" if cid == "fn" else "endnote"
                    note_level = level
                    note_id += 1
                elif level <= note_level:
                    note_kind, note_level = None, -1
            elif tag == TAG_PARA_TEXT:
                if note_kind and level <= note_level:
                    note_kind, note_level = None, -1
                part = note_kind or "body"
                text = _para_text(body).strip()
                if text:
                    counters[part] += 1
                    units.append(Unit(text=text, part=part, index=counters[part],
                                      note_id=str(note_id) if note_kind else None,
                                      meta={"section": name}))
    return units


# ─────────────────────────────────────────────────────────── rhwp 다리

def rhwp_path() -> str | None:
    return shutil.which("rhwp") or (os.environ.get("RHWP_BIN") or None)


def rhwp_capabilities() -> dict | None:
    """rhwp가 스스로 기술하는 명령 목록. 하위 명령 이름을 넘겨짚지 않기 위함."""
    exe = rhwp_path()
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "capabilities"], capture_output=True, timeout=30)
        return json.loads(r.stdout.decode("utf-8", "ignore"))
    except Exception:
        return None


def rhwp_to_pdf(src: str, dest: str) -> str | None:
    """rhwp로 HWP/HWPX를 PDF로 바꾼다.

    PDF로 만들면 페이지·행 핀포인트가 한글 뷰어에서 사람이 세는 쪽수와 맞는다.
    순수 파이썬 경로에는 쪽 개념이 아예 없으므로, rhwp가 있으면 이 길이 낫다.
    """
    exe = rhwp_path()
    if not exe:
        return None
    caps = rhwp_capabilities()
    cmd = "export-pdf"
    if isinstance(caps, dict):
        names = json.dumps(caps)
        for cand in ("export-pdf", "export_pdf", "to-pdf"):
            if f'"{cand}"' in names:
                cmd = cand
                break
    try:
        r = subprocess.run([exe, cmd, src, "-o", dest], capture_output=True, timeout=300)
        return dest if (r.returncode == 0 and os.path.exists(dest)) else None
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────── 진입점

def read_hangul(path: str) -> list[Unit]:
    """확장자와 매직 넘버로 HWPX/HWP를 가려 읽는다."""
    with open(path, "rb") as f:
        magic = f.read(8)
    if magic[:2] == b"PK":
        return read_hwpx(path)
    if magic == Cfb.SIG:
        return read_hwp5(path)
    raise ValueError(f"HWP/HWPX로 보이지 않는다: {path}")
