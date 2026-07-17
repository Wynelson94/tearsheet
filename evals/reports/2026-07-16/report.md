# Tearsheet Trust Report — 2026-07-16 18:35 — PARTIAL RUN (--only)

**VERDICT: GREEN**

- tearsheet 0.1.0 · trafilatura 2.1.0 · httpx 0.28.1 · lxml 6.1.1 · python 3.14.2
- corpus 2026-07-16 (sha 717f782d9d82) · 1 items scored · burst: skipped

## Gates

| gate | status | detail |
|---|---|---|
| fabrication (0 tolerated) | PASS | 0 pages fabricated figures |
| guard calibration (0 regressions) | PASS | known-bad warns, known-good silent |
| silent omission (<=1) | PASS | 0 pages omitted without warning |
| unhandled exceptions (0) | PASS | 0 |
| cache poison (0) | PASS | none served |
| timeouts (<=2) | PASS | 0 |
| baseline drift (0) | PASS | stable |
| hard failures (<=1 beyond the above) | PASS | none |

## Items

| id | category | status | detail |
|---|---|---|---|
| quo | pricing_grid | warn-correct | warning riding with content; 23 figures flagged |

## Reading this report

- `pass` — figures/content verified against the independent oracle.
- `warn-correct` — the tool flagged its own extraction; the warning was warranted.
- `walled` — honest refusal (bot wall / consent wall / HTTP error reported as such).
- `FAIL` — a trust property was violated; see evidence/ for the raw bytes.
- Every item's raw evidence is under `evidence/<id>/` for re-adjudication.