"""Wayback CDX → snapshot HTML → trafilatura Markdown (RAG-ready)."""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any
from urllib.parse import unquote

import httpx
from apify import Actor

from cdx import (
    archive_url,
    cdx_query_url_for_domain,
    fetch_snapshot_bytes_async,
    filter_snapshots,
    make_session,
    search_snapshots_async,
    select_snapshots,
)
from charging import Charger
from chunking import chunk_markdown
from extract import content_hash, extract_markdown, word_count
from inputs import collect_domains, collect_urls

EVENT = "snapshot-item"  # must match .actor/pay_per_event.json
DEFAULT_UA = (
    "waybackpack/0.6.4 (+https://github.com/jsvine/waybackpack; "
    "apify-actor wayback-cdx-markdown/0.1; contact via Apify console)"
)

_DATE_PREFIX_RE = re.compile(r"^\d{4}(\d{2}){0,5}$")


def _normalize_wayback_date(label: str, raw: str | None) -> str | None:
    """Strip empty dates; warn on non-prefix-looking values (still pass through)."""
    val = (raw or "").strip()
    if not val:
        return None
    if not _DATE_PREFIX_RE.match(val):
        Actor.log.warning(
            f"{label}={val!r} is not a Wayback timestamp prefix "
            f"(expected YYYY / YYYYMM / YYYYMMDD / YYYYMMDDhhmmss). Passing through to CDX anyway."
        )
    return val


def _original_from_row(row: dict[str, Any], fallback: str) -> str:
    """Prefer CDX `original` field; fall back to the query URL."""
    orig = row.get("original") or row.get("url") or ""
    if orig:
        return unquote(str(orig))
    # urlkey is often "com,example)/path" — not ideal; use fallback
    return fallback


async def main() -> None:
    async with Actor:
        t0 = time.monotonic()
        inp = await Actor.get_input() or {}
        charger = Charger(EVENT)

        ua = (inp.get("userAgent") or "").strip() or DEFAULT_UA
        timeout = int(inp.get("requestTimeoutSecs") or 60)
        max_retries = int(inp.get("maxRetries") or 3)
        delay = float(inp.get("delaySecs") if inp.get("delaySecs") is not None else 0.5)
        collapse = inp.get("collapse") or "timestamp:8"
        selection = inp.get("selection") or "latest"
        max_per = int(inp.get("maxSnapshotsPerTarget") or 3)
        max_items = int(inp.get("maxItems") or 0) or None
        fetch_raw = bool(inp.get("fetchRaw", True))
        output_format = inp.get("outputFormat") or "items"
        want_items = output_format in ("items", "items_and_chunks")
        want_chunks = output_format in ("chunks", "items_and_chunks")
        status_codes = [str(x) for x in (inp.get("statusCodes") or ["200"])]
        mime_types = [str(x) for x in (inp.get("mimeTypes") or ["text/html", "html"])]
        from_date = _normalize_wayback_date("fromDate", inp.get("fromDate"))
        to_date = _normalize_wayback_date("toDate", inp.get("toDate"))
        if from_date and to_date and from_date > to_date:
            Actor.log.warning(
                f"fromDate={from_date!r} is after toDate={to_date!r}; CDX may return empty results."
            )
        uniques_only = bool(inp.get("uniquesOnly", False))
        include_comments = bool(inp.get("includeComments", False))
        include_tables = bool(inp.get("includeTables", True))
        favor_precision = bool(inp.get("favorPrecision", False))
        chunk_size = int(inp.get("chunkSize") or 1000)
        chunk_overlap = int(inp.get("chunkOverlap") or 150)
        chunk_unit = inp.get("chunkUnit") or "tokens"

        async with httpx.AsyncClient(headers={"User-Agent": ua}, timeout=timeout) as client:
            urls, warns = await collect_urls(inp.get("urls"), client=client)
            domains, dwarns = collect_domains(inp.get("domains"))
            for w in warns + dwarns:
                Actor.log.warning(w)

        targets: list[tuple[str, str, str]] = []  # (label, cdx_query, fallback_original)
        for u in urls:
            targets.append((u, u, u))
        for d in domains:
            q = cdx_query_url_for_domain(d)
            targets.append((d, q, f"https://{d}/"))

        if not targets:
            raise ValueError("Provide at least one URL in `urls` or domain in `domains`.")

        session = make_session(user_agent=ua, max_retries=max_retries)
        # waybackpack Session uses requests; timeout is handled via retries/delay inside

        cdx_report: list[dict[str, Any]] = []
        items_out = chunks_out = fetch_errors = 0
        total_cdx = 0

        for label, query, fallback_orig in targets:
            if charger.limit_reached:
                Actor.log.warning("Spending limit reached; stopping.")
                break
            if max_items is not None and items_out >= max_items:
                break

            report: dict[str, Any] = {
                "target": label,
                "cdxQuery": query,
                "status": "ok",
                "cdxHits": 0,
                "selected": 0,
                "fetchedOk": 0,
                "fetchedFailed": 0,
                "error": None,
            }
            try:
                Actor.log.info(f"CDX search: {query}")
                rows = await search_snapshots_async(
                    query,
                    session=session,
                    from_date=from_date,
                    to_date=to_date,
                    collapse=collapse,
                    uniques_only=uniques_only,
                )
            except Exception as e:  # noqa: BLE001
                report["status"] = "error"
                report["error"] = str(e)[:500]
                cdx_report.append(report)
                await charger.push_free(
                    {"kind": "error", "status": "error", "originalUrl": label, "error": str(e)[:500]}
                )
                fetch_errors += 1
                continue

            filtered, fstats = filter_snapshots(
                rows, status_codes=status_codes, mime_substrings=mime_types
            )
            chosen = select_snapshots(filtered, selection=selection, limit=max_per)
            report["cdxHits"] = len(rows)
            report["filteredHits"] = len(filtered)
            report["selected"] = len(chosen)
            report["filterStats"] = fstats
            total_cdx += len(rows)
            Actor.log.info(
                f"CDX {query}: {len(rows)} raw → {len(filtered)} filtered → {len(chosen)} selected"
            )
            if fstats.get("emptyMimeKept"):
                Actor.log.warning(
                    f"CDX {query}: kept {fstats['emptyMimeKept']} row(s) with empty MIME "
                    f"(Wayback often omits mimetype on older captures)."
                )
            if fstats.get("emptyMimeSkipped"):
                Actor.log.warning(
                    f"CDX {query}: skipped {fstats['emptyMimeSkipped']} row(s) with empty MIME."
                )
            if fstats.get("emptyTimestampSkipped"):
                Actor.log.warning(
                    f"CDX {query}: skipped {fstats['emptyTimestampSkipped']} row(s) with empty timestamp."
                )
            if rows and not filtered:
                Actor.log.warning(
                    f"CDX {query}: {len(rows)} hit(s) but filters left 0 "
                    f"(statusSkipped={fstats.get('statusSkipped', 0)}, "
                    f"mimeSkipped={fstats.get('mimeSkipped', 0)}, "
                    f"emptyMimeSkipped={fstats.get('emptyMimeSkipped', 0)}, "
                    f"emptyTimestampSkipped={fstats.get('emptyTimestampSkipped', 0)}). "
                    f"Relax statusCodes/mimeTypes or date range."
                )
            elif filtered and not chosen:
                Actor.log.warning(
                    f"CDX {query}: {len(filtered)} filtered hit(s) but selection returned 0 "
                    f"(selection={selection!r}, maxSnapshotsPerTarget={max_per})."
                )

            if not chosen:
                report["status"] = "empty"
                cdx_report.append(report)
                continue

            for row in chosen:
                if charger.limit_reached:
                    break
                if max_items is not None and items_out >= max_items:
                    break

                ts = str(row.get("timestamp") or "")
                original = _original_from_row(row, fallback_orig)
                if not ts:
                    report["fetchedFailed"] += 1
                    fetch_errors += 1
                    await charger.push_free(
                        {
                            "kind": "error",
                            "status": "error",
                            "originalUrl": original,
                            "error": "CDX row missing timestamp",
                        }
                    )
                    continue

                try:
                    if delay > 0:
                        await asyncio.sleep(delay)
                    body = await fetch_snapshot_bytes_async(
                        original, ts, session=session, raw=fetch_raw
                    )
                    if body is None:
                        raise RuntimeError("Empty response from Wayback snapshot fetch")
                    # Asset.fetch may return str in some paths; normalize
                    if isinstance(body, str):
                        body_bytes: bytes | str = body
                    else:
                        body_bytes = body

                    extracted = extract_markdown(
                        body_bytes,
                        url=original,
                        include_comments=include_comments,
                        include_tables=include_tables,
                        favor_precision=favor_precision,
                    )
                    md = extracted.get("contentMarkdown") or ""
                    if not md.strip():
                        raise RuntimeError("trafilatura returned empty Markdown")

                    arch = archive_url(original, ts, raw=fetch_raw)
                    item = {
                        "kind": "snapshot",
                        "status": "ok",
                        "originalUrl": original,
                        "archiveUrl": arch,
                        "timestamp": ts,
                        "title": extracted.get("title"),
                        "author": extracted.get("author"),
                        "date": extracted.get("date"),
                        "language": extracted.get("language"),
                        "contentMarkdown": md,
                        "contentHash": content_hash(md),
                        "wordCount": word_count(md),
                        "charCount": len(md),
                        "mimeType": row.get("mimetype") or row.get("mime"),
                        "statusCode": row.get("statuscode") or row.get("status"),
                        "digest": row.get("digest"),
                        "length": row.get("length"),
                        "cdxQuery": query,
                        "target": label,
                    }

                    charged = 0
                    if want_items:
                        charged = await charger.push_and_charge([item])
                        items_out += charged
                    elif want_chunks:
                        # still charge once per snapshot when only emitting chunks
                        summary = {
                            **{k: v for k, v in item.items() if k != "contentMarkdown"},
                            "kind": "snapshot_summary",
                            "contentMarkdown": md[:500] + ("…" if len(md) > 500 else ""),
                        }
                        charged = await charger.push_and_charge([summary])
                        items_out += charged

                    if want_chunks and charged:
                        chunks = chunk_markdown(
                            md,
                            chunk_size=chunk_size,
                            chunk_overlap=chunk_overlap,
                            unit=chunk_unit,
                        )
                        chunk_rows = []
                        for c in chunks:
                            chunk_rows.append(
                                {
                                    "kind": "chunk",
                                    "status": "ok",
                                    "originalUrl": original,
                                    "archiveUrl": arch,
                                    "timestamp": ts,
                                    "title": extracted.get("title"),
                                    "chunkIndex": c["chunkIndex"],
                                    "chunkCount": c["chunkCount"],
                                    "text": c["text"],
                                    "headingPath": c["headingPath"],
                                    "charCount": c["charCount"],
                                    "tokenEstimate": c["tokenEstimate"],
                                    "contentHash": content_hash(c["text"]),
                                    "cdxQuery": query,
                                    "target": label,
                                }
                            )
                        if chunk_rows:
                            await charger.push_free(chunk_rows)
                            chunks_out += len(chunk_rows)

                    report["fetchedOk"] += 1
                except Exception as e:  # noqa: BLE001
                    report["fetchedFailed"] += 1
                    fetch_errors += 1
                    await charger.push_free(
                        {
                            "kind": "error",
                            "status": "error",
                            "originalUrl": original,
                            "timestamp": ts,
                            "archiveUrl": archive_url(original, ts, raw=fetch_raw),
                            "error": str(e)[:500],
                            "target": label,
                        }
                    )

            cdx_report.append(report)

        duration = round(time.monotonic() - t0, 3)
        summary = {
            "targets": len(targets),
            "cdxHits": total_cdx,
            "itemsOutput": items_out,
            "chunksOutput": chunks_out,
            "fetchErrors": fetch_errors,
            "durationSecs": duration,
            "charged": charger.counts,
            "outputFormat": output_format,
            "collapse": collapse,
            "selection": selection,
            "ppeEvent": EVENT,
            "note": "Charged events: snapshot-item per successfully extracted snapshot. Chunks free.",
        }
        await Actor.set_value("CDX_REPORT", cdx_report)
        await Actor.set_value("OUTPUT", summary)
        msg = (
            f"Done: {items_out} snapshots, {chunks_out} chunks, "
            f"{fetch_errors} fetch errors, CDX hits {total_cdx}. "
            f"Charged: {charger.counts or 'nothing'}."
        )
        Actor.log.info(msg)
        await Actor.set_status_message(msg, is_terminal=True)


if __name__ == "__main__":
    asyncio.run(main())
