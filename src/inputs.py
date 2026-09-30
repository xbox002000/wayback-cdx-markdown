"""Input helpers: normalize URL lists and bare domains for CDX queries."""
from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx

_URL_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)
_HOST_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$",
    re.I,
)


def normalize_url(raw: str, default_scheme: str = "https") -> str | None:
    """Trim, add a scheme to bare hostnames, drop fragments. Returns None for junk."""
    s = (raw or "").strip().strip("\"'<>")
    if not s or s.startswith("#"):
        return None
    if not _URL_RE.match(s):
        if " " in s or "." not in s:
            return None
        s = f"{default_scheme}://{s}"
    if not s.lower().startswith(("http://", "https://")):
        return None
    return s.split("#", 1)[0]


def normalize_domain(raw: str) -> str | None:
    """Return a bare hostname suitable for CDX `host/*` queries, or None."""
    s = (raw or "").strip().strip("\"'<>").lower()
    if not s or s.startswith("#"):
        return None
    if _URL_RE.match(s):
        host = urlparse(s).hostname
        return host.lower() if host else None
    s = s.split("/")[0].split("?")[0].split("#")[0]
    if s.startswith("www."):
        # keep www — CDX is path-sensitive; caller may prefer either form
        pass
    if " " in s or not _HOST_RE.match(s):
        return None
    return s


def _split(text: str) -> list[str]:
    return [p for p in re.split(r"[\s,]+", text) if p]


async def collect_urls(
    values: Iterable[Any] | str | None,
    *,
    client: httpx.AsyncClient | None = None,
    max_remote_list_bytes: int = 5_000_000,
) -> tuple[list[str], list[str]]:
    """Return (urls, warnings). Deduplicates while preserving order."""
    warnings: list[str] = []
    raw: list[str] = []
    if values is None:
        values = []
    if isinstance(values, str):
        values = [values]
    for v in values:
        if isinstance(v, dict):
            if v.get("url"):
                raw.append(str(v["url"]))
            elif v.get("requestsFromUrl"):
                if client is None:
                    warnings.append(f"Remote URL list ignored (no HTTP client): {v['requestsFromUrl']}")
                    continue
                try:
                    r = await client.get(v["requestsFromUrl"], follow_redirects=True, timeout=30)
                    r.raise_for_status()
                    raw.extend(re.findall(r"https?://[^\s\"'<>]+", r.text[:max_remote_list_bytes]))
                except Exception as e:  # noqa: BLE001
                    warnings.append(f"Could not load remote URL list {v['requestsFromUrl']}: {e}")
        elif isinstance(v, str):
            raw.extend(_split(v))
    seen: set[str] = set()
    out: list[str] = []
    for r in raw:
        u = normalize_url(r)
        if u is None:
            warnings.append(f"Ignored invalid URL: {r[:200]}")
            continue
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out, warnings


def collect_domains(values: Iterable[Any] | str | None) -> tuple[list[str], list[str]]:
    """Return (domains, warnings) for CDX prefix queries."""
    warnings: list[str] = []
    if values is None:
        values = []
    if isinstance(values, str):
        values = [values]
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if isinstance(v, dict):
            v = v.get("url") or v.get("domain") or ""
        for part in _split(str(v)):
            d = normalize_domain(part)
            if d is None:
                warnings.append(f"Ignored invalid domain: {part[:200]}")
                continue
            if d not in seen:
                seen.add(d)
                out.append(d)
    return out, warnings
