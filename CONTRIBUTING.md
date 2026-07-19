# Contributing to tearsheet

Issues and pull requests are welcome. tearsheet is personal research tooling shared as-is —
there's no roadmap and no support promise — but it is tested like it matters, and contributions
that keep it that way are appreciated.

For the full contributor deep-dive (the trust model, how the guards are calibrated against real
pages, and how the live-eval flywheel works), see the wiki:
**[Development & Testing](https://github.com/Wynelson94/tearsheet/wiki/Development-and-Testing)**.

## Setup

```bash
git clone https://github.com/Wynelson94/tearsheet.git
cd tearsheet
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Requires Python >= 3.12. Optional, for the browser-render path and its tests:
`playwright install chromium`.

## The gate

Every change must pass the same gate CI runs. Run it before you push:

```bash
.venv/bin/ruff check src tests && .venv/bin/mypy && .venv/bin/python -m pytest
```

- **`ruff check`** — lint. **`mypy`** — strict type-checking. **`pytest`** — the offline suite.
- The default suite runs **fully offline**: a `conftest.py` socket guard fails any test that
  reaches a non-loopback address, so tests stay deterministic. HTTP is faked with
  `httpx.MockTransport` and fixture HTML.
- Extras (not in the default gate): `pytest -m playwright` (real Chromium against a local server)
  and `pytest -m live` (real network).

CI (`.github/workflows/ci.yml`) runs `ruff` + `mypy` + `pytest` on every push and PR, matrixed
over Python 3.12 and 3.13. A red gate blocks the merge.

## Conventions

- **TDD.** Write the failing test first, then the code that passes it.
- **Guards answer to real pages.** tearsheet's contract is *no figure a page carries may go
  missing silently*. If you touch the extraction guards, your change must still satisfy the
  permanent fixtures in `tests/fixtures/probation/` — the real pages that defined the tool's
  original failures. Every new guard adds a new permanent fixture. See
  [Development & Testing](https://github.com/Wynelson94/tearsheet/wiki/Development-and-Testing)
  and [Trust & Evaluation](https://github.com/Wynelson94/tearsheet/wiki/Trust-and-Evaluation).
- **Keep it offline-deterministic.** New tests must not reach the network unless explicitly
  marked `@pytest.mark.live`.
- **Update the docs.** User-facing changes get a `CHANGELOG.md` entry (see
  [Keep a Changelog](https://keepachangelog.com/)); behavior changes that touch the guards get a
  note in the wiki.

## Pull requests

1. Branch off `main`.
2. Make the change with tests; keep the gate green.
3. Open the PR with a clear description of the behavior change and how you verified it.

Security issues: please see [SECURITY.md](SECURITY.md) rather than opening a public issue.
