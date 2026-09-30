"""Simple heading-aware Markdown chunking for RAG (feed entries, no page numbers)."""
from __future__ import annotations

import math
import re

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")


def approx_tokens(text: str) -> int:
    return math.ceil(len(text) / 4) if text else 0


def _measure(text: str, unit: str) -> int:
    return approx_tokens(text) if unit == "tokens" else len(text)


def _split_blocks(md: str) -> list[str]:
    blocks, buf = [], []
    for line in md.split("\n"):
        if not line.strip():
            if buf:
                blocks.append("\n".join(buf))
                buf = []
            continue
        if _HEADING.match(line):
            if buf:
                blocks.append("\n".join(buf))
                buf = []
            blocks.append(line)
            continue
        buf.append(line)
    if buf:
        blocks.append("\n".join(buf))
    return blocks


def chunk_markdown(
    md: str,
    *,
    chunk_size: int = 1000,
    chunk_overlap: int = 150,
    unit: str = "tokens",
) -> list[dict]:
    if not (md or "").strip():
        return []
    chunk_overlap = max(0, min(chunk_overlap, chunk_size // 2))
    path: list[tuple[int, str]] = []
    blocks: list[tuple[str, tuple[str, ...], str]] = []  # text, heading_path, kind
    for b in _split_blocks(md):
        m = _HEADING.match(b)
        if m:
            level = len(m.group(1))
            path = [p for p in path if p[0] < level] + [(level, m.group(2).strip())]
            blocks.append((b, tuple(t for _, t in path), "heading"))
        else:
            blocks.append((b, tuple(t for _, t in path), "text"))

    # explode oversized text blocks on sentences
    exploded: list[tuple[str, tuple[str, ...], str]] = []
    for text, hp, kind in blocks:
        if kind == "heading" or _measure(text, unit) <= chunk_size:
            exploded.append((text, hp, kind))
            continue
        sents = _SENT.split(text)
        cur = ""
        for s in sents:
            while _measure(s, unit) > chunk_size:
                cut = chunk_size * 4 if unit == "tokens" else chunk_size
                if cur:
                    exploded.append((cur, hp, kind))
                    cur = ""
                exploded.append((s[:cut], hp, kind))
                s = s[cut:]
            if cur and _measure(cur + " " + s, unit) > chunk_size:
                exploded.append((cur, hp, kind))
                cur = s
            else:
                cur = (cur + " " + s).strip()
        if cur:
            exploded.append((cur, hp, kind))

    chunks: list[list[tuple[str, tuple[str, ...], str]]] = []
    cur_list: list[tuple[str, tuple[str, ...], str]] = []
    cur_size = 0
    for b in exploded:
        bsize = _measure(b[0], unit)
        if cur_list and cur_size + bsize > chunk_size:
            chunks.append(cur_list)
            carry, csize = [], 0
            for prev in reversed(cur_list):
                psize = _measure(prev[0], unit)
                if prev[2] == "heading" or csize + psize > chunk_overlap:
                    break
                carry.insert(0, prev)
                csize += psize
            while cur_list and cur_list[-1][2] == "heading":
                carry.append(cur_list.pop())
            if not chunks[-1]:
                chunks.pop()
            cur_list, cur_size = carry, sum(_measure(x[0], unit) for x in carry)
        cur_list.append(b)
        cur_size += bsize
    if cur_list:
        chunks.append(cur_list)
    chunks = [c for c in chunks if any(x[2] != "heading" for x in c)] or chunks

    out = []
    for i, c in enumerate(chunks):
        text = "\n\n".join(x[0] for x in c)
        content = [x for x in c if x[2] != "heading"] or c
        hp = list(content[0][1])
        out.append({
            "chunkIndex": i,
            "chunkCount": len(chunks),
            "text": text,
            "headingPath": hp,
            "charCount": len(text),
            "tokenEstimate": approx_tokens(text),
        })
    return out
