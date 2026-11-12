"""Đọc json3 / vtt / srt của YouTube, ghi SRT/TXT, ghép song ngữ (port từ Subs.kt)."""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

_TAG = re.compile(r"<[^>]+>")
_INLINE_TS = re.compile(r"<\d{1,2}:\d{2}[:.]")
_SPACES = re.compile(r"\s+")


@dataclass
class Cue:
    start: int  # ms
    end: int
    text: str


def _ms(ts: str) -> int:
    parts = ts.strip().replace(",", ".").split(":")
    if len(parts) == 2:
        parts = ["0"] + parts
    h, m, s = parts
    return int(h) * 3_600_000 + int(m) * 60_000 + round(float(s) * 1000)


def _fmt(v: int) -> str:
    x = max(0, v)
    h, x = divmod(x, 3_600_000)
    m, x = divmod(x, 60_000)
    s, r = divmod(x, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{r:03d}"


def _clean(line: str) -> str:
    return _SPACES.sub(" ", html.unescape(_TAG.sub("", line))).strip()


def normalize(cues: list[Cue]) -> list[Cue]:
    out: list[Cue] = []
    for c0 in sorted((c for c in cues if c.text.strip()), key=lambda c: c.start):
        c = replace(c0, end=c0.start + 2000 if c0.end <= c0.start else c0.end)
        if out and out[-1].text == c.text and c.start - out[-1].end < 500:
            out[-1].end = max(out[-1].end, c.end)
            continue
        out.append(c)
    for a, b in zip(out, out[1:]):
        if a.start < b.start < a.end:
            a.end = b.start
    return out


def parse_text(raw: str) -> list[Cue]:
    text = raw.replace("﻿", "").replace("\r\n", "\n").replace("\r", "\n")
    rolling = "<c>" in text or bool(_INLINE_TS.search(text))
    raws: list[tuple[int, int, list[str]]] = []
    cur = None
    for line in text.split("\n"):
        if "-->" in line:
            if cur is not None:
                body = cur[2]
                while body and not body[-1].strip():
                    body.pop()
                if body and body[-1].strip().isdigit() and (len(body) == 1 or not body[-2].strip()):
                    body.pop()
            left, right = line.split("-->", 1)
            right = (right.strip().split() or [""])[0]
            try:
                cur = (_ms(left), _ms(right), [])
                raws.append(cur)
            except Exception:
                cur = None
            continue
        if cur is not None:
            cur[2].append(line)

    out: list[Cue] = []
    prev: list[str] = []
    for s, e, body_raw in raws:
        body = [b for b in (_clean(x) for x in body_raw) if b]
        if rolling:
            fresh = [b for b in body if b not in prev]
            prev = body
            if e - s <= 60 or not fresh:
                continue
            body = fresh
        if body:
            out.append(Cue(s, e, "\n".join(body)))
    return normalize(out)


def parse_json3(text: str) -> list[Cue]:
    events = json.loads(text).get("events") or []
    out: list[Cue] = []
    for ev in events:
        segs = ev.get("segs")
        if not segs:
            continue
        t = "".join(sg.get("utf8", "") for sg in segs)
        t = "\n".join(x.strip() for x in t.split("\n") if x.strip())
        if not t:
            continue
        start = int(ev.get("tStartMs", 0))
        dur = int(ev.get("dDurationMs", 0)) or 2000
        out.append(Cue(start, start + dur, html.unescape(t)))
    return normalize(out)


def load(path: Path) -> list[Cue]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    if Path(path).suffix.lower() == ".json3" or text.lstrip().startswith("{"):
        return parse_json3(text)
    return parse_text(text)


def to_srt(cues: list[Cue]) -> str:
    return "".join(f"{i}\n{_fmt(c.start)} --> {_fmt(c.end)}\n{c.text}\n\n" for i, c in enumerate(cues, 1))


def to_txt(cues: list[Cue]) -> str:
    out: list[str] = []
    for c in cues:
        for line in (x.strip() for x in c.text.split("\n")):
            if line and (not out or out[-1] != line):
                out.append(line)
    return "\n".join(out) + "\n"


def _one_line(t: str) -> str:
    return " ".join(x.strip() for x in t.split("\n") if x.strip())


def merge_bilingual(primary: list[Cue], secondary: list[Cue], color: str | None = None) -> list[Cue]:
    """Dòng trên = primary, dòng dưới = secondary. color != None → tô màu dòng dưới."""
    extras: list[list[str]] = [[] for _ in primary]
    lonely: list[Cue] = []
    j = 0
    for sc in sorted(secondary, key=lambda c: c.start):
        while j < len(primary) - 1 and primary[j].end <= sc.start:
            j += 1
        best, best_ov, k = -1, 0, j
        while k < len(primary) and primary[k].start < sc.end:
            ov = min(primary[k].end, sc.end) - max(primary[k].start, sc.start)
            if ov > best_ov:
                best, best_ov = k, ov
            k += 1
        if best < 0:
            lonely.append(sc)
        else:
            extras[best].append(_one_line(sc.text))

    def paint(t: str) -> str:
        return f'<font color="{color}">{t}</font>' if color else t

    out = []
    for c, ex in zip(primary, extras):
        top = _one_line(c.text)
        out.append(Cue(c.start, c.end, top if not ex else top + "\n" + paint(" ".join(ex))))
    out += [Cue(c.start, c.end, paint(_one_line(c.text))) for c in lonely]
    return sorted(out, key=lambda c: c.start)
