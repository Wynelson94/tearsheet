# Tearsheet Trust Report — 2026-07-16 18:40

**VERDICT: YELLOW**

- tearsheet 0.1.0 · trafilatura 2.1.0 · httpx 0.28.1 · lxml 6.1.1 · python 3.14.2
- corpus 2026-07-16 (sha 717f782d9d82) · 40 items scored · burst: 45 scrapes across 3 domains: {'ok': 40, 'honest_refusal': 5, 'FAIL': 0, 'exception': 0}

## Gates

| gate | status | detail |
|---|---|---|
| fabrication (0 tolerated) | PASS | 0 pages fabricated figures |
| guard calibration (0 regressions) | PASS | known-bad warns, known-good silent |
| silent omission (<=1) | **FAIL** | 6 pages omitted without warning |
| unhandled exceptions (0) | PASS | 0 |
| cache poison (0) | PASS | none served |
| timeouts (<=2) | PASS | 0 |
| baseline drift (0) | PASS | stable |
| hard failures (<=1 beyond the above) | **FAIL** | notion: SILENT omission: ['$0', '$20', '$8']; tailscale: SILENT omission: ['$5']; basecamp: SILENT omission: ['$15', '$299', '$50']; scaleway: SILENT omission: ['€1,000', '€36,000', '€4,99', '€4.99', '€9; linkedin_fp: SILENT omission: ['$130', '$17', '$2']; wiki_idaho: SILENT omission: ['$74,900']; todomvc: tiny output (300 chars) with no shell hint; map_uv: only 0 urls mapped; map_fastapi: only 0 urls mapped |

## Items

| id | category | status | detail |
|---|---|---|---|
| quo | pricing_grid | warn-correct | warning riding with content; 23 figures flagged |
| slack | pricing_grid | warn-correct | warning riding with content; 7 figures flagged |
| notion | pricing_grid | **FAIL** | SILENT omission: ['$0', '$20', '$8'] |
| zapier | pricing_grid | warn-correct | warning riding with content; 9 figures flagged |
| tailscale | pricing_grid | **FAIL** | SILENT omission: ['$5'] |
| zoom | pricing_tabbed | walled | error fetching https://www.zoom.com/en/pricing/: HTTP 404 |
| ringcentral | pricing_tabbed | pass | 4/4 figures shown |
| heyrosie | plan_cards | pass | 5/5 figures shown |
| calendly | plan_cards | pass | 3/5 figures shown |
| basecamp | plan_cards | **FAIL** | SILENT omission: ['$15', '$299', '$50'] |
| hetzner | pricing_non_usd | pass | clean |
| scaleway | pricing_non_usd | **FAIL** | SILENT omission: ['€1,000', '€36,000', '€4,99', '€4.99', '€9,000'] |
| giffgaff | pricing_non_usd | pass | 11/11 figures shown |
| linkedin_fp | article_peripheral | **FAIL** | SILENT omission: ['$130', '$17', '$2'] |
| rfc9110 | pinned_immutable | pass | clean |
| rfc2616_txt | pinned_immutable | pass | clean |
| gutenberg_alice | pinned_immutable | pass | clean |
| w3c_css2 | pinned_immutable | pass | clean |
| gh_raw_pep8 | pinned_immutable | walled | error fetching https://raw.githubusercontent.com/python/peps/4c7dfb59e6a89e6f21a5f184f26722a11eae8f1 |
| wiki_idaho | reference_table | **FAIL** | SILENT omission: ['$74,900'] |
| fed_h15 | data_table | pass | clean |
| pg_essay | control_prose | pass | clean |
| py_docs | control_docs | pass | clean |
| fastapi_docs | control_docs | pass | clean |
| guardian | consent_heavy | pass | content served (455 chars) |
| lemonde | consent_heavy | pass | content served (3940 chars) |
| zeit | consent_heavy | pass | content served (3997 chars) |
| ecfr | botwall | walled | honest refusal |
| dodcio | botwall | walled | honest refusal |
| crunchbase | botwall | walled | honest refusal |
| todomvc | spa_shell | **FAIL** | tiny output (300 chars) with no shell hint |
| aozora | charset_shift_jis | pass | clean |
| wiki_ja | charset_utf8_ja | pass | clean |
| gh_api | json_endpoint | pass | JSON pretty-printed |
| berkshire_pdf | pdf_figures | pass | pdf text extracted; 3 money figures visible |
| irs_p15 | pdf_tables | pass | pdf text extracted; 7 money figures visible |
| map_uv | map | **FAIL** | only 0 urls mapped |
| map_fastapi | map | **FAIL** | only 0 urls mapped |
| crawl_ruff | crawl | pass | crawl: docs.astral.sh  pages: 5  errors: 0  skipped(robots/dupe/type): 0 |
| search_smoke | search | pass | results returned |

## Reading this report

- `pass` — figures/content verified against the independent oracle.
- `warn-correct` — the tool flagged its own extraction; the warning was warranted.
- `walled` — honest refusal (bot wall / consent wall / HTTP error reported as such).
- `FAIL` — a trust property was violated; see evidence/ for the raw bytes.
- Every item's raw evidence is under `evidence/<id>/` for re-adjudication.