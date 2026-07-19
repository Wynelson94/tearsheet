# Changelog

All notable changes to **tearsheet** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

For the *narrative* of how the guard system evolved — which real page broke each
guard, and why — see the wiki page
[How the Guards Evolved](https://github.com/Wynelson94/tearsheet/wiki/How-the-Guards-Evolved).

## [Unreleased]

### Added
- MIT `LICENSE`, project URLs, and a GitHub Actions CI gate (`ruff` + `mypy` + `pytest`,
  matrixed over Python 3.12 and 3.13).
- Synthetic false-positive fixture so the probation corpus republishes no real individual's page.

### Changed
- User-Agent string corrected; live-eval evidence artifacts untracked (only `report.md`
  scorecards are committed).
- Version and test-count references made consistent across the repo.

## [0.1.4] — 2026-07-16

### Added
- **Title-armed dropped-price guard** — the "notion-class" gap: genuine pricing pages whose
  plan cards are diluted by prose so the real figures never share a 1,500-char window. When a
  page's *title* declares it a pricing page, the guard now arms at ≥ 3 distinct figures
  page-wide (instead of requiring a cluster), catching omissions the cluster heuristic missed.
- **€ and £ matching** in the price guard (previously `$` only).
- **Post-extraction bot-wall backstop** — challenge pages too large for the raw-body heuristic
  are now caught after extraction, reported, and never cached; previously poisoned cache rows
  are evicted rather than replayed.

### Changed
- Live-eval harness adjudicated against run-1 evidence; `map` scoring counts relative paths,
  and omissions inside the documented 50%-retention contract are bucketed as minor (not hard fails).

## [0.1.3] — 2026-07-16

### Changed
- **Dropped-price guard now arms on price *clusters*, not page-wide counts.** It fires only
  when some 1,500-char window of visible text holds ≥ 4 distinct price figures (a pricing-grid
  signature). This eliminates the 2026-07-14 false positive on a LinkedIn post page, whose four
  real dollar amounts lived in related-content cards and were correctly excluded by extraction.
  Calibrated against the real cached pages (quo, smith.ai, heyrosie) with a clean separation margin.

## [0.1.2] — 2026-07-14

### Added
- **Silent-failure guards** in `assess_extraction()`, each riding in the output header as a
  `warning:` line: dropped-price warning, collapsed-column warning, and a gated/never-rendered
  warning.
- **Consent-wall detection** — a cookie-consent banner is reported as a `consent/cookie wall`,
  never cached, and never passed off as the page (root cause of the smith.ai 428-byte-banner bug).
- **`raw=` / `--raw` escape hatch** — returns the page's visible text, bypassing the extractor,
  to recover figures the extractor drops. Deliberately uses the plain fetch, not the browser.

### Changed
- Warnings surface on both the live and cache-read paths; poisoned cache rows are no longer replayed.

## [0.1.1] — 2026-07-11

### Added
- **Bot-wall detection** (`looks_blocked()`, strong phrases + 30 KB size guard) — bot walls are
  reported explicitly and never cached.
- **Tiny-extraction render** — `scrape` auto mode attempts a browser render when extraction is
  tiny, so custom SPA mounts (e.g. TodoMVC) upgrade instead of returning near-empty.
- **MCP/CLI parity test** so the "verb available in one interface but not the other" class of gap
  cannot recur.
- Documentation + a pinning test for the upstream trafilatura 2.1.0 emphasis-mangling bug
  ([adbar/trafilatura#882](https://github.com/adbar/trafilatura/issues/882)) — fails loudly if
  upstream fixes it.

## [0.1.0] — 2026-07-11

Initial working toolset (milestones M1–M5).

### Added
- **`scrape`** — httpx fetch, trafilatura main-content extraction, SQLite cache, token-shaped output.
- **FastMCP server** exposing the tools to Claude Code / any MCP client.
- **`map`** and **`crawl`** — robots-obedient async BFS crawler with sitemap discovery and
  crawl-to-disk output.
- **Playwright** headless-Chromium render fallback and the deterministic **`extract`** tool
  (JSON-LD / OpenGraph / microdata / tables).
- **PDF** text extraction (pypdf) and cache eviction.
- **`search`** subcommand added to the CLI (had been MCP-only).

<!-- No git tags are cut yet; links point at the commit that shipped each version. -->
[Unreleased]: https://github.com/Wynelson94/tearsheet/compare/feacd27...main
[0.1.4]: https://github.com/Wynelson94/tearsheet/commit/feacd27
[0.1.3]: https://github.com/Wynelson94/tearsheet/commit/282f71e
[0.1.2]: https://github.com/Wynelson94/tearsheet/commit/45f0e84
[0.1.1]: https://github.com/Wynelson94/tearsheet/commit/87613ec
[0.1.0]: https://github.com/Wynelson94/tearsheet/commit/a5d42db
