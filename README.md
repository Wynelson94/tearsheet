# tearsheet

Local, self-hosted web-to-markdown for LLM research. A Firecrawl-style toolset — scrape,
crawl, map, search, extract — that runs entirely on your machine, built to feed Claude Code
(or any MCP client) **clean content with minimal context tokens**. No API keys, no SaaS,
no telemetry.

> *tearsheet (n.): a page torn from a publication and filed as proof it ran.*

**Trust status:** qualified for heavy usage 2026-07-16 — 249 tests, a falsifiable live
eval harness (verdict GREEN), and zero fabrications across the tool's entire recorded
history. Its documented failure mode is *omission*, and the guards exist to make every
omission loud. See [Trust](#trust).

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

- **Commercial/tabular pages are the weak spot — use `--raw` there.** Pricing grids, JS-tabbed
  plan matrices, and consent-gated pages defeat the extractor: it returns something that *looks*
  clean while the figures never made it. Measured 2026-07-14 on real pages — `quo.com/pricing`
  kept 4 of 24 prices and flattened a 3-column matrix into repeated rows (`Unlimited* /
  Unlimited* / Unlimited*`), while `heyrosie.com/pricing` came through perfectly. So the failure
  is site-shaped, not universal, and you cannot eyeball it from the output alone.
  Since v0.1.2 the tool says so itself: a `warning:` line reports dropped prices and collapsed
  columns, and a cookie banner is reported as a `consent/cookie wall` instead of being served as
  the page. **Never quote figures from a warned extraction — re-run with `--raw` / `raw=true`.**
  Since v0.1.3 the dropped-price guard arms only when the page carries a price *cluster*
  (>= 4 distinct figures within 1,500 chars of visible text) — a pricing-grid signature — so
  article pages with real-but-peripheral dollar amounts scattered through related-content
  cards no longer trigger a false warning (observed 2026-07-14 on a LinkedIn post page).
  Since v0.1.4 the guard also matches **€/£**, arms at a lower floor (>= 3 distinct figures
  page-wide) when the page *title* declares it a pricing page (the notion-class gap: plan
  cards diluted by prose so figures never share a window), and a post-extraction **bot-wall
  backstop** catches challenge pages too large for the raw-body heuristic — they are
  reported and never cached, and previously poisoned cache rows are evicted, not replayed.
  Note `--raw` deliberately uses the plain fetch, not the browser: a rendered DOM can be *worse*
  (on smith.ai the consent overlay replaced the pricing table the raw fetch still carried).
- **Figures no guard can see**: prices rendered by JS into tabs/RSC payloads (dialpad),
  served as literal `"null"` placeholders (aircall), or drawn in images — invisible to any
  non-interactive fetch, tearsheet included. And a page carrying a **single** figure sits
  below every guard's floor by design (a one-figure floor would warn on every blog footer).
  The rule is procedural: any figure you are going to quote gets `--raw` or independent
  verification.
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

## Trust

"Can it be trusted for heavy usage?" is a measurement here, not a feeling.

- **Offline suite (243 tests, runs in the gate)**: guard boundary pins, cache-poisoning
  regressions, truncation honesty, charset torture, structure torture, adversarial
  robustness — enforced fully offline by a loopback-only socket guard. The five REAL
  pages that defined the tool's probation (quo, smith.ai, dialpad, heyrosie, a LinkedIn
  false-positive page) are archived as permanent fixtures in `tests/fixtures/probation/`:
  every guard change answers to the original failures forever.
- **Real-browser suite (6 tests, `pytest -m playwright`)**: actual chromium against a
  local delayed-JS server — networkidle degradation, browser relaunch, and a 30-render
  soak asserting zero context leaks.
- **Live eval harness (`evals/`)**: ~40-target corpus reweighted toward commercial/tabular
  pages, scored by invariant against an independent oracle — *no figure the producing body
  carries may go missing silently*. Isolated cache per run, per-item evidence archived for
  human re-adjudication, count-based gates, and a verdict that refuses to exist when the
  corpus isn't reachable. **Falsifiability is proven both directions**: neutering the
  guards turns the verdict RED; restoring them turns it GREEN.
- **Findings flywheel**: every live-eval failure gets demoted into a permanent offline
  fixture from its archived bytes. Run 1 (2026-07-16) found one real guard gap and went
  YELLOW; the fix shipped as v0.1.4 and run 2 went GREEN.

Re-run the qualification any time (~15 min):

```bash
.venv/bin/python evals/run_eval.py
```

The standing usage contract, independent of any verdict: heed `warning:` lines, `--raw`
for figures you'll quote, treat a suspiciously small extraction of a rich page as partial.

## Development

```bash
.venv/bin/ruff check src tests && .venv/bin/mypy && .venv/bin/python -m pytest
```

TDD throughout; the default suite (243 tests) runs entirely offline — `httpx.MockTransport`,
fixture HTML, and a conftest socket guard that fails any test reaching for a non-loopback
address. Extras: `pytest -m playwright` (real chromium, local server), `pytest -m live`
(real network). The live trust evaluation lives in `evals/` (see [Trust](#trust)).
