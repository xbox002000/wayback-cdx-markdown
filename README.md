# Wayback CDX → Markdown for RAG

**Query the Wayback Machine CDX index, fetch selected snapshot HTML, and extract clean Markdown for RAG — not just a list of archive URLs.**

Many tools stop after listing CDX captures. This Actor uses open-source **waybackpack** (MIT) for CDX + snapshot fetch and **trafilatura** (Apache-2.0) to turn archived HTML into Markdown dataset rows, with optional heading-aware RAG chunks. Broken captures are reported, not fatal. Default memory: 256 MB. No browser, no AI keys.

## What you get

- 📚 **CDX search** — page URL(s) and/or domain prefix (`example.com/*`) via waybackpack
- 🗓️ **Filters** — date range, collapse (day/month/digest), status codes, MIME substrings
- 🎯 **Selection** — latest, oldest, or even sample; per-target and global caps
- 📝 **Markdown body** — trafilatura extraction (tables optional; comments off by default)
- 🧩 **Optional RAG chunks** — heading-aware chunks with token estimate
- 🧯 **Per-target report** — `CDX_REPORT` in the key-value store; failed fetches are free rows
- 💾 **HTTP only** — 256 MB default

## Measured results

Local + private cloud (2026-09-30 Asia/Taipei). Settled `usageTotalUsd` on own runs.

| Test | Result |
|---|---|
| `example.com/` CDX 2024, collapse month, 2 snapshots + chunks (local) | **2** Markdown items + **2** chunks in **~47 s**; CDX 12→6→2 |
| `example.com/` + `info.cern.ch/` (2020, 1 snap each, local) | **2** Markdown items in **~40 s**; 0 fetch errors |
| Cloud 1 snapshot `bGbenU8jxfkK90zMh` (256 MB) | **1** item; ~66 s; memMax ~97 MB; settled **$0.001083** |
| Cloud 5 URLs × sample, max 10 `N3u4tjN3UeWN4J6hH` (build 0.1.2) | **10** items; ~202 s; memMax ~105 MB; settled **$0.003037** (~$0.00030 / snapshot) |
| Cloud 2 URLs + domain, items+chunks `tnMfOC9kJbluFSncc` | **7** items + **10** free chunks; ~96 s; memMax ~107 MB; settled **$0.001599** |

## Use cases

- **Rebuild historical page text** for RAG / knowledge bases from Wayback captures
- **Sample a site’s archived paths** under a domain and extract readable Markdown
- **Compare snapshots over time** (collapse by day/month, then extract)

## How to use

1. Add page **URLs** and/or **Domains**.
2. Optional: set **From/To date**, **Collapse**, **Max snapshots per URL/domain**, **Output**.
3. Start the Actor. Rows appear in the **Dataset**; `CDX_REPORT` and `OUTPUT` in the **Key-value store**.

### Input example

```json
{
  "urls": [{ "url": "https://example.com/" }],
  "fromDate": "202401",
  "toDate": "202412",
  "maxSnapshotsPerTarget": 2,
  "maxItems": 5,
  "collapse": "timestamp:6",
  "selection": "latest",
  "outputFormat": "items",
  "delaySecs": 0.5
}
```

### Output example (one dataset item per snapshot)

```json
{
  "kind": "snapshot",
  "status": "ok",
  "originalUrl": "https://example.com/",
  "archiveUrl": "https://web.archive.org/web/20241201001928id_/https://example.com/",
  "timestamp": "20241201001928",
  "title": "Example Domain",
  "contentMarkdown": "This domain is for use in documentation examples…",
  "contentHash": "sha256…",
  "wordCount": 26,
  "mimeType": "text/html",
  "statusCode": "200"
}
```

### Key-value store records

| Key | Content |
|---|---|
| `CDX_REPORT` | Per-target CDX hits / selected / fetch ok-fail |
| `OUTPUT` | Run summary (counts, duration, charged events) |

## Pricing

**Pay per event** (private Actor; Store publish pending coordinator):

| Event | Price |
|---|---|
| `snapshot-item` (primary) | **$0.003** per successfully extracted snapshot Markdown |
| `apify-actor-start` | Apify default ($0.00005 / GB) |

Failed CDX queries and failed fetches are never charged. RAG chunk rows do not add extra events. Example: 1,000 snapshots ≈ **$3.00** list (+ actor-start).

## Known limits

- Wayback CDX and snapshot endpoints rate-limit; use **Delay between snapshot fetches** and modest caps.
- Domain prefix queries (`example.com/*`) can return very large CDX sets — keep **Max snapshots per URL/domain** low and prefer date bounds.
- Some captures are redirects, soft-404s, or binary; trafilatura may return empty text (reported as error, not charged).
- waybackpack uses synchronous `requests` under the hood (run in a worker thread); not a headless browser.

## FAQ

**Does this publish captures to a public GitHub repo?** No. This project stays private unless you deliberately publish later.

**Do you copy closed Apify Actors?** No. Stack is waybackpack (MIT) + trafilatura (Apache-2.0) + the in-house Apify Python template patterns.

## Related Actors / See also

- [Sitemap URL Extractor — Find PDF & Document Links](https://apify.com/ingenious_quip_bxq/sitemap-url-discovery) — pick live URLs/domains worth archiving, then query CDX for history.
- [Bulk URL Status Checker — Broken Links & Redirects](https://apify.com/ingenious_quip_bxq/url-status-checker) — when live pages fail, fall back to Wayback Markdown for RAG.
- [RSS & Atom to Markdown — JSON + RAG Chunks](https://apify.com/ingenious_quip_bxq/rss-atom-to-markdown) — current feed items vs historical snapshots of the same URLs.
- [PDF & DOCX to Markdown](https://apify.com/ingenious_quip_bxq/pdf-docx-to-markdown) / [Scanned OCR to Markdown](https://apify.com/ingenious_quip_bxq/scanned-ocr-to-markdown) — live documents; this Actor is for **archived HTML** pages.
- [WHOIS DNS SSL Lookup — Batch Domain Enrichment](https://apify.com/ingenious_quip_bxq/whois-dns-ssl-lookup) — domain age / registrar context next to archive coverage.

## License & source

Actor source: **AGPL-3.0** (see `LICENSE`). Third-party notices: `NOTICE`.
