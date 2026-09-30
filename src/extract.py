"""HTML → Markdown via trafilatura (Apache-2.0)."""
from __future__ import annotations

import hashlib
import re
from typing import Any

import trafilatura
from trafilatura import bare_extraction


def _decode(content: bytes | str) -> str:
    if isinstance(content, str):
        return content
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def extract_markdown(
    html: bytes | str,
    *,
    url: str | None = None,
    include_comments: bool = False,
    include_tables: bool = True,
    favor_precision: bool = False,
) -> dict[str, Any]:
    """Return title, text/markdown, metadata fields. Empty markdown if extraction fails."""
    raw_html = _decode(html)
    if not raw_html.strip():
        return {"title": None, "contentMarkdown": "", "language": None, "date": None, "author": None}

    md = trafilatura.extract(
        raw_html,
        url=url,
        output_format="markdown",
        include_comments=include_comments,
        include_tables=include_tables,
        favor_precision=favor_precision,
        with_metadata=False,
    )
    meta: dict[str, Any] = {}
    try:
        doc = bare_extraction(
            raw_html,
            url=url,
            include_comments=include_comments,
            include_tables=include_tables,
            favor_precision=favor_precision,
        )
        if doc is not None:
            if hasattr(doc, "as_dict"):
                meta = doc.as_dict() or {}
            elif isinstance(doc, dict):
                meta = doc
            else:
                meta = {
                    "title": getattr(doc, "title", None),
                    "author": getattr(doc, "author", None),
                    "date": getattr(doc, "date", None),
                    "language": getattr(doc, "language", None),
                }
    except Exception:  # noqa: BLE001
        meta = {}

    text = (md or "").strip()
    title = meta.get("title") or _guess_title(raw_html)
    return {
        "title": title,
        "contentMarkdown": text,
        "language": meta.get("language"),
        "date": meta.get("date"),
        "author": meta.get("author"),
    }


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def _guess_title(html: str) -> str | None:
    m = _TITLE_RE.search(html)
    if not m:
        return None
    t = re.sub(r"\s+", " ", m.group(1)).strip()
    return t[:500] or None


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))
