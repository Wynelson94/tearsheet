# Security Policy

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue for anything exploitable.

- **Preferred:** GitHub's private vulnerability reporting — the **Security** tab →
  **Report a vulnerability** (if enabled on this repo).
- **Or:** email the maintainer at **nmnslr@gmail.com** with details and, if possible, a
  reproduction.

Please allow a reasonable window for a fix before any public disclosure. As personal research
tooling maintained by one person, response is best-effort — but security reports are taken
seriously and are prioritized over feature work.

## Supported versions

Only the latest `main` is supported. There are no backports; fixes land on `main` and in the next
version. tearsheet is not published to PyPI — you run it from source, so *updating* means pulling
`main` and re-installing.

## Scope & threat model

tearsheet is a **local, self-hosted** tool. It has no server, no accounts, no telemetry, and
requires no API keys; nothing you scrape leaves your machine except the outbound HTTP(S) request
to the site you pointed it at. It handles no secrets or credentials.

Security-relevant surface, for reporters:

- **Fetches arbitrary URLs** you give it (`httpx`) and, on the render path, loads them in a
  **headless Chromium** (Playwright). Treat scraped sites as untrusted input.
- **Parses untrusted content** — HTML (trafilatura / lxml / extruct), PDFs (pypdf), sitemaps.
  Parser-level issues (resource exhaustion, XML entity handling, crashes on malformed input) are
  in scope.
- **Writes to disk** under `~/.tearsheet` (override with `TEARSHEET_HOME`): a SQLite cache and
  extracted markdown/crawl files. Path-handling issues are in scope.
- Follows and rate-limits per `robots.txt`; strips tracking parameters. It is **not** designed to
  evade paywalls or bot defenses, and reports bot/consent walls rather than bypassing them.

Out of scope: vulnerabilities in third-party sites you scrape, and upstream bugs in dependencies
(please report those to the relevant project — e.g. trafilatura — though a heads-up here is welcome).
