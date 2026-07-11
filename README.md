# tearsheet

Local, self-hosted web-to-markdown for LLM research. A Firecrawl-style toolset — scrape,
crawl, map, search, extract — that runs entirely on your machine, built to feed Claude Code
(or any MCP client) **clean content with minimal context tokens**. No API keys, no SaaS,
no telemetry.

> *tearsheet (n.): a page torn from a publication and filed as proof it ran.*

## Why

A language model pays for every token of nav, ads, and footer it reads. tearsheet extracts
main content only (via [trafilatura](https://github.com/adbar/trafilatura)), truncates with
a disk spillover instead of dumping whole pages into context, and returns **indexes instead
of content** for site crawls. The consuming model decides what to read next.

## Install

```bash
git clone <this-repo> ~/Projects/tearsheet
cd ~/Projects/tearsheet
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

JS rendering (optional, for SPA fallback): `playwright install chromium`.
Without it, tearsheet degrades gracefully and tells you when a page needed rendering.

### Register with Claude Code

```bash
claude mcp add --scope user tearsheet -- ~/Projects/tearsheet/.venv/bin/tearsheet-mcp
```

## MCP tools

| Tool | What it does | Token shape |
|---|---|---|
| `scrape(url, max_length, render, include_links, fresh)` | One URL → clean markdown | Header + markdown, truncated at `max_length` chars; full copy always at `~/.tearsheet/pages/<hash>.md` |
| `crawl(url, max_pages, max_depth, include/exclude_patterns, …)` | Site section → markdown files on disk | Compact index only (filename, ~tokens, title, path). Content never enters context |
| `map(url, max_urls, search, …)` | List a site's URLs (sitemap + links) without scraping | One path per line |
| `search(query, max_results, backend)` | Keyless metasearch (ddgs: Bing/Brave/DDG/Google…) | Numbered title — url + one snippet line |
| `extract(url, types, max_rows, render)` | Deterministic JSON-LD / OpenGraph / microdata / tables | JSON, empty keys omitted; reuses scrape-cached HTML |

The intended research flow: **`map` → pick URLs → `scrape`**, or **`crawl` → read files**.

## CLI

The same five verbs, plus cache management:

```bash
tearsheet scrape https://example.com/article --max-length 4000
tearsheet map https://docs.example.com --search auth
tearsheet crawl https://docs.example.com --max-pages 20 --include "/docs/*"
tearsheet extract https://store.example.com/product --types json-ld
tearsheet cache stats | prune --days 30 | clear
```

## How it works

- **Fetching**: httpx fast path. When a page looks like a JS shell (SPA root markers,
  noscript "enable JavaScript", script-dominated bytes) or returns a bot-challenge
  (403 "Just a moment"), it retries once through headless Chromium and keeps whichever
  result extracts more text. `render="always"` forces the browser; `"never"` forbids it.
- **Cache**: SQLite (`~/.tearsheet/cache.db`, WAL). Pages 7 days, robots.txt 24 h.
  Raw HTML is kept so `extract` never refetches what `scrape` already saw. Rendered
  entries outrank plain-HTTP entries. `fresh=true` bypasses.
- **Crawler**: async BFS, bounded by `max_pages`/`max_depth`. Obeys robots.txt
  (crawl-delay capped at 10 s), max 2 concurrent per domain + 1 s delay, and refuses
  crawler traps: >3 query params, repeating path segments (`/a/b/a/b`), asset extensions.
  Tracking params (`utm_*`, `fbclid`, `gclid`, `ref`) are stripped everywhere.
- **PDFs**: `scrape` extracts PDF text via pypdf (`via: pypdf` in the header). Crawls
  don't follow PDF links.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `TEARSHEET_HOME` | `~/.tearsheet` | Cache DB, page spillover, crawl output |
| `TEARSHEET_UA` | `tearsheet/0.1 (+…; research tool)` | User-Agent for plain fetches |
| `TEARSHEET_TTL` | `604800` (7 d) | Page cache TTL, seconds |

## Politeness & scope

`crawl` and `map` obey robots.txt strictly. Single-URL `scrape` does not (it is
user-initiated, equivalent to opening the page in your browser). The default UA
identifies the tool honestly; Chromium fallback presents a real browser UA. This is
a research tool for reading the public web — not for evading paywalls or bot defenses.

## Limitations & known issues

- **Emphasis mangling (upstream)**: trafilatura 2.1.0's markdown serializer displaces
  nested-emphasis words (`<strong><em>word</em></strong>` mid-sentence) onto the next
  paragraph and can drop characters around inline `<em>` (observed: "i.e." → "e.").
  Facts survive; verbatim quotes should be re-verified against the source before reuse.
  Pinned by `tests/test_content.py::TestKnownUpstreamManglingDocumented` (fails when
  upstream fixes it). Reported: [adbar/trafilatura#882](https://github.com/adbar/trafilatura/issues/882).
- Bot-walled sites (eCFR, DoD, Cloudflare in strict mode) are reported as
  `blocked by bot protection …` — deliberately not evaded; use the site's official API.
- Wikipedia extractions can include maintenance-hatnote table noise ("This article
  needs more citations") — cosmetic.
- Paywalled/login-gated content is out of scope; a suspiciously low token count is the tell.
- `search` depends on ddgs backends, which occasionally break upstream; `backend="auto"`
  rotates around failures.

## Development

```bash
.venv/bin/ruff check src tests && .venv/bin/mypy && .venv/bin/python -m pytest
```

TDD throughout; the suite (150+ tests) runs entirely offline — `httpx.MockTransport`
and fixture HTML, no network. Playwright-dependent tests are marked and skip when no
chromium binary is present.
