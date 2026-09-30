"""Wayback CDX search + snapshot fetch via waybackpack (MIT)."""
from __future__ import annotations

import asyncio
from typing import Any

from waybackpack.asset import Asset
from waybackpack.cdx import search as cdx_search
from waybackpack.session import Session


def make_session(*, user_agent: str, max_retries: int = 3) -> Session:
    return Session(user_agent=user_agent, follow_redirects=True, max_retries=max_retries)


def cdx_query_url_for_domain(domain: str) -> str:
    """Prefix-style CDX query covering paths under a host."""
    d = domain.strip().lower().rstrip("/")
    return f"{d}/*"


def search_snapshots(
    query: str,
    *,
    session: Session,
    from_date: str | None = None,
    to_date: str | None = None,
    collapse: str | None = "timestamp:8",
    uniques_only: bool = False,
) -> list[dict[str, Any]]:
    """Synchronous CDX search (call via asyncio.to_thread)."""
    collapse_arg = None if not collapse or collapse == "none" else [collapse]
    return cdx_search(
        query,
        session=session,
        from_date=from_date or None,
        to_date=to_date or None,
        uniques_only=uniques_only,
        collapse=collapse_arg,
    )


async def search_snapshots_async(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    return await asyncio.to_thread(search_snapshots, *args, **kwargs)


def filter_snapshots(
    rows: list[dict[str, Any]],
    *,
    status_codes: list[str] | None = None,
    mime_substrings: list[str] | None = None,
    keep_empty_mime: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Filter CDX rows by status / MIME.

    Empty MIME: when a MIME filter is set and `keep_empty_mime` is True (default),
    rows with missing mimetype are kept (Wayback often omits MIME on older captures)
    and counted in stats so callers can warn. Empty timestamps are dropped and counted.
    """
    out: list[dict[str, Any]] = []
    codes = {c.strip() for c in (status_codes or []) if str(c).strip()}
    mimes = [m.lower().strip() for m in (mime_substrings or []) if str(m).strip()]
    stats = {
        "emptyMimeKept": 0,
        "emptyMimeSkipped": 0,
        "emptyTimestampSkipped": 0,
        "statusSkipped": 0,
        "mimeSkipped": 0,
    }
    for row in rows:
        ts = str(row.get("timestamp") or "").strip()
        if not ts:
            stats["emptyTimestampSkipped"] += 1
            continue
        sc = str(row.get("statuscode") or row.get("status") or "").strip()
        if codes and sc not in codes:
            stats["statusSkipped"] += 1
            continue
        mime = str(row.get("mimetype") or row.get("mime") or "").lower().strip()
        if mimes:
            if not mime:
                if keep_empty_mime:
                    stats["emptyMimeKept"] += 1
                    out.append(row)
                else:
                    stats["emptyMimeSkipped"] += 1
                continue
            if not any(m in mime for m in mimes):
                stats["mimeSkipped"] += 1
                continue
        out.append(row)
    return out, stats


def select_snapshots(
    rows: list[dict[str, Any]],
    *,
    selection: str = "latest",
    limit: int = 3,
) -> list[dict[str, Any]]:
    if not rows or limit <= 0:
        return []
    # Sort by timestamp ascending for sampling / oldest
    keyed = sorted(rows, key=lambda r: str(r.get("timestamp") or ""))
    if selection == "oldest":
        return keyed[:limit]
    if selection == "sample":
        if len(keyed) <= limit:
            return keyed
        if limit == 1:
            return [keyed[len(keyed) // 2]]
        step = (len(keyed) - 1) / (limit - 1)
        idxs = sorted({int(round(i * step)) for i in range(limit)})
        return [keyed[i] for i in idxs]
    # latest
    return list(reversed(keyed))[:limit]


def archive_url(original_url: str, timestamp: str, *, raw: bool = True) -> str:
    flag = "id_" if raw else ""
    return Asset(original_url, timestamp).get_archive_url(raw=bool(flag))


def fetch_snapshot_bytes(
    original_url: str,
    timestamp: str,
    *,
    session: Session,
    raw: bool = True,
) -> bytes | None:
    """Synchronous body fetch via waybackpack Asset (call via to_thread)."""
    asset = Asset(original_url, timestamp)
    return asset.fetch(session=session, raw=raw)


async def fetch_snapshot_bytes_async(*args: Any, **kwargs: Any) -> bytes | None:
    return await asyncio.to_thread(fetch_snapshot_bytes, *args, **kwargs)
