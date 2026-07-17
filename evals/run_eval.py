#!/usr/bin/env python3
"""Tearsheet live trust evaluation.

Answers one question with evidence: does the tool ever fail SILENTLY?

    .venv/bin/python evals/run_eval.py                 # full corpus + burst
    .venv/bin/python evals/run_eval.py --skip-burst
    .venv/bin/python evals/run_eval.py --only quo,heyrosie

Design (see the trust-suite plan):
- ISOLATED home per run: a fresh cache under the report dir — no contamination.
- INDEPENDENT oracle: lxml text_content with script/style/template/comments removed.
  Never the tool's own html_to_text (shared-fate flaw).
- Invariants over pinned values on volatile pages: every money figure the page's own
  body carries must reach the returned string, be recoverable from the truncation
  full-copy, or ride with a warning. Fabrication = a figure in the output that the
  producing body never contained. Scored on the RETURNED STRING, post-truncation.
- Baselines pin exact figure sets for immutable pages on first run (evals/baselines/).
- Evidence per item under the report dir so any verdict can be re-adjudicated later.
- Retry policy: transport errors retry once after 30s; content failures and walls
  are NEVER retried — they are the signal.
- Count-based gates; the run REFUSES a verdict if <70% of the corpus is reachable.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

EVALS_DIR = Path(__file__).parent
REPO = EVALS_DIR.parent
sys.path.insert(0, str(REPO / "src"))

MONEY = re.compile(r"[$€£][0-9][0-9,]*(?:\.[0-9]{2})?")
ITEM_TIMEOUT_S = 120
PACING_S = 1.5


def oracle_text(html: bytes) -> str:
    """Independent visible-text oracle — NOT the tool's html_to_text."""
    from lxml import etree
    from lxml import html as lxml_html

    try:
        tree = lxml_html.fromstring(html)
    except etree.ParserError:
        return ""
    for el in tree.xpath("//script | //style | //template | //noscript"):
        if el.getparent() is not None:
            el.drop_tree()
    for comment in tree.xpath("//comment()"):
        if comment.getparent() is not None:  # top-level comments have no parent to drop from
            comment.drop_tree()
    return re.sub(r"\s+", " ", tree.text_content()).strip()


def money_set(text: str) -> set[str]:
    return set(MONEY.findall(text))


@dataclass
class ItemResult:
    id: str
    category: str
    check: str
    status: str = "pending"  # pass | warn-correct | walled | unreachable | timeout | FAIL
    detail: str = ""
    fabricated: set[str] = field(default_factory=set)
    silently_omitted: set[str] = field(default_factory=set)
    warned: bool = False
    retried: bool = False


class Eval:
    def __init__(self, corpus: dict, report_dir: Path, only: set[str] | None) -> None:
        self.corpus = corpus
        self.report_dir = report_dir
        self.evidence_dir = report_dir / "evidence"
        self.baselines = EVALS_DIR / "baselines"
        self.only = only
        self.results: list[ItemResult] = []
        self.exceptions: list[str] = []
        self.poison_failures: list[str] = []
        self.baseline_drift: list[str] = []
        self.burst_summary = "skipped"

    # ---------- plumbing ----------

    async def scrape(self, url: str, **kw: object) -> str:
        from tearsheet.scrape import scrape

        return await asyncio.wait_for(scrape(url, **kw), timeout=ITEM_TIMEOUT_S)  # type: ignore[arg-type]

    def producing_body(self, url: str) -> bytes | None:
        """The exact bytes the served extraction came from — the run cache's row."""
        from tearsheet.cache import Cache
        from tearsheet.config import get_settings

        cache = Cache(get_settings().cache_db)
        try:
            row = cache.get_page(url, ttl_seconds=10**9)
            return row.html if row else None
        finally:
            cache.close()

    def save_evidence(self, item_id: str, **files: object) -> None:
        d = self.evidence_dir / item_id
        d.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            if content is None:
                continue
            if isinstance(content, bytes):
                (d / f"{name}.gz").write_bytes(gzip.compress(content))
            elif isinstance(content, str):
                (d / f"{name}.txt").write_text(content)
            else:
                (d / f"{name}.json").write_text(json.dumps(content, indent=2, default=sorted))

    @staticmethod
    def is_wall_report(out: str) -> bool:
        return (
            "blocked by bot protection" in out
            or "consent/cookie wall" in out
            or "error fetching" in out
            or "HTTP 4" in out
            or "HTTP 5" in out
        )

    @staticmethod
    def shown_body(out: str) -> str:
        return out.split("---", 1)[1] if "---" in out else out

    # ---------- checks ----------

    async def run_item(self, item: dict) -> ItemResult:
        r = ItemResult(id=item["id"], category=item["category"], check=item["check"])
        try:
            handler = getattr(self, f"check_{item['check']}")
            await handler(item, r)
        except TimeoutError:
            r.status = "timeout"
            r.detail = f"exceeded {ITEM_TIMEOUT_S}s"
        except Exception as exc:  # noqa: BLE001 - an unhandled exception IS the finding
            r.status = "FAIL"
            r.detail = f"unhandled exception: {type(exc).__name__}: {exc}"
            self.exceptions.append(f"{item['id']}: {exc}")
        return r

    async def check_content(self, item: dict, r: ItemResult) -> None:
        out = await self.scrape(item["url"], max_length=6000)
        if "error fetching" in out:
            r.retried = True
            await asyncio.sleep(30)
            out = await self.scrape(item["url"], max_length=6000, fresh=True)
        if self.is_wall_report(out):
            r.status = "walled"
            r.detail = out.splitlines()[0][:120]
            self.save_evidence(item["id"], returned=out)
            return

        body = self.producing_body(item["url"])
        shown = self.shown_body(out)
        r.warned = "warning:" in out
        oracle_figs = money_set(oracle_text(body)) if body else set()
        shown_figs = money_set(shown)

        r.fabricated = shown_figs - oracle_figs if body else set()
        missing = oracle_figs - shown_figs
        recovered = set()
        if missing and "truncated" in out and "full copy: " in out:
            full_path = out.split("full copy: ", 1)[1].split(")", 1)[0]
            try:
                full_text = Path(full_path).read_text()
                recovered = {m for m in missing if m in full_text}
            except OSError:
                pass
        truly_missing = missing - recovered
        if truly_missing and not r.warned:
            r.silently_omitted = truly_missing

        if item.get("baseline"):
            self.check_baseline(item["id"], oracle_figs, shown)

        if r.fabricated:
            r.status = "FAIL"
            r.detail = f"FABRICATED figures: {sorted(r.fabricated)}"
        elif item.get("expect_warning") and not r.warned and truly_missing:
            r.status = "FAIL"
            r.detail = "known-bad page: figures missing and no warning fired"
        elif item.get("expect_no_price_warning") and any(
            "price" in line for line in out.splitlines() if line.startswith("warning:")
        ):
            r.status = "FAIL"
            r.detail = "false-positive price warning on a page that must stay silent"
        elif r.silently_omitted:
            r.status = "FAIL"
            r.detail = f"SILENT omission: {sorted(r.silently_omitted)[:8]}"
        elif r.warned:
            r.status = "warn-correct" if missing else "pass"
            r.detail = "warning riding with content" + (
                f"; {len(missing)} figures flagged" if missing else ""
            )
        else:
            r.status = "pass"
            r.detail = f"{len(shown_figs)}/{len(oracle_figs)} figures shown" if oracle_figs else "clean"

        self.save_evidence(
            item["id"], returned=out, body=body,
            oracle={"oracle_figures": oracle_figs, "shown_figures": shown_figs,
                    "missing": missing, "recovered_from_full_copy": recovered},
        )

    def check_baseline(self, item_id: str, oracle_figs: set[str], shown: str) -> None:
        self.baselines.mkdir(exist_ok=True)
        path = self.baselines / f"{item_id}.json"
        snapshot = {"oracle_figures": sorted(oracle_figs), "shown_sha": hashlib.sha256(shown.encode()).hexdigest()}
        if not path.exists():
            path.write_text(json.dumps(snapshot, indent=2))
            return
        pinned = json.loads(path.read_text())
        if pinned["oracle_figures"] != snapshot["oracle_figures"]:
            self.baseline_drift.append(
                f"{item_id}: figure set drifted from baseline (immutable page changed?)"
            )

    async def check_consent_or_content(self, item: dict, r: ItemResult) -> None:
        out = await self.scrape(item["url"], max_length=4000)
        shown = self.shown_body(out)
        if self.is_wall_report(out):
            r.status = "walled"
            r.detail = "honest wall/consent/error report"
        elif len(shown) < 600 and "cookie" in shown.lower():
            r.status = "FAIL"
            r.detail = "looks like a consent banner served as content without a wall label"
        else:
            r.status = "pass"
            r.detail = f"content served ({len(shown)} chars)"
        self.save_evidence(item["id"], returned=out)

    async def check_wall(self, item: dict, r: ItemResult) -> None:
        out = await self.scrape(item["url"], max_length=4000)
        shown = self.shown_body(out)
        wall_text_served = any(
            p in shown.lower()
            for p in ("verify you are a human", "complete the captcha", "checking your browser")
        )
        if self.is_wall_report(out) or "app shell" in out:
            r.status = "walled"
            r.detail = "honest refusal"
            # poison gate: the refusal must hold on an immediate second pass (no cache serve)
            out2 = await self.scrape(item["url"], max_length=4000)
            if not (self.is_wall_report(out2) or "app shell" in out2):
                shown2 = self.shown_body(out2)
                if any(p in shown2.lower() for p in ("captcha", "verify you are a human")):
                    self.poison_failures.append(item["id"])
        elif wall_text_served:
            r.status = "FAIL"
            r.detail = "wall text served AS CONTENT without a block label"
        else:
            r.status = "pass"
            r.detail = "wall absent today; real content served"
        self.save_evidence(item["id"], returned=out)

    async def check_shell(self, item: dict, r: ItemResult) -> None:
        out = await self.scrape(item["url"], max_length=4000)
        shown = self.shown_body(out)
        if "JavaScript app shell" in out or "app shell" in out:
            r.status = "walled"
            r.detail = "honest shell report"
        elif len(shown.strip()) > 400:
            r.status = "pass"
            r.detail = "rendered content captured"
        else:
            r.status = "FAIL"
            r.detail = f"tiny output ({len(shown.strip())} chars) with no shell hint"
        self.save_evidence(item["id"], returned=out)

    async def check_json(self, item: dict, r: ItemResult) -> None:
        out = await self.scrape(item["url"])
        if '"full_name"' in out or ('"' in out and "{" in out):
            r.status = "pass"
            r.detail = "JSON pretty-printed"
        else:
            r.status = "FAIL"
            r.detail = "JSON endpoint did not round-trip"
        self.save_evidence(item["id"], returned=out)

    async def check_pdf(self, item: dict, r: ItemResult) -> None:
        out = await self.scrape(item["url"], max_length=6000)
        if "via: pypdf" not in out:
            r.status = "unreachable" if self.is_wall_report(out) else "FAIL"
            r.detail = out.splitlines()[0][:120]
        elif len(self.shown_body(out)) > 500:
            figs = money_set(out)
            r.status = "pass"
            r.detail = f"pdf text extracted; {len(figs)} money figures visible"
        else:
            r.status = "FAIL"
            r.detail = "pdf extraction suspiciously tiny"
        self.save_evidence(item["id"], returned=out)

    async def check_map(self, item: dict, r: ItemResult) -> None:
        from tearsheet.mapper import map_site

        out = await asyncio.wait_for(map_site(item["url"], max_urls=50), timeout=ITEM_TIMEOUT_S)
        urls = [line for line in out.splitlines() if line.strip().startswith("http")]
        if len(urls) >= 5:
            r.status = "pass"
            r.detail = f"{len(urls)} urls mapped"
        else:
            r.status = "FAIL"
            r.detail = f"only {len(urls)} urls mapped"
        self.save_evidence(item["id"], returned=out)

    async def check_crawl(self, item: dict, r: ItemResult) -> None:
        from tearsheet.crawl import crawl

        out = await asyncio.wait_for(
            crawl(item["url"], max_pages=item.get("max_pages", 5), max_depth=1),
            timeout=ITEM_TIMEOUT_S * 2,
        )
        if "pages" in out.lower() or "crawl" in out.lower():
            r.status = "pass"
            r.detail = out.splitlines()[0][:120]
        else:
            r.status = "FAIL"
            r.detail = "crawl produced no recognizable summary"
        self.save_evidence(item["id"], returned=out)

    async def check_search(self, item: dict, r: ItemResult) -> None:
        from tearsheet.search import search

        out = await asyncio.wait_for(search(item["url"], max_results=5), timeout=ITEM_TIMEOUT_S)
        if "http" in out:
            r.status = "pass"
            r.detail = "results returned"
        else:
            r.status = "walled"  # ddgs backends are third-party; no-crash is the bar
            r.detail = out[:120]
        self.save_evidence(item["id"], returned=out)

    # ---------- burst ----------

    async def run_burst(self, spec: dict) -> None:
        outcomes = {"ok": 0, "honest_refusal": 0, "FAIL": 0, "exception": 0}
        n = 0
        for i in range(spec["count"]):
            domain = spec["domains"][i % len(spec["domains"])]
            path = spec["paths"][(i // len(spec["domains"])) % len(spec["paths"])]
            url = domain + path
            n += 1
            try:
                out = await self.scrape(url, max_length=800, fresh=True)
                if self.is_wall_report(out):
                    outcomes["honest_refusal"] += 1
                elif len(self.shown_body(out).strip()) > 100:
                    outcomes["ok"] += 1
                else:
                    outcomes["FAIL"] += 1
            except Exception:  # noqa: BLE001
                outcomes["exception"] += 1
            await asyncio.sleep(0.5)
        self.burst_summary = f"{n} scrapes across {len(spec['domains'])} domains: {outcomes}"

    # ---------- orchestration + report ----------

    async def run(self, skip_burst: bool) -> None:
        for item in self.corpus["items"]:
            if self.only and item["id"] not in self.only:
                continue
            print(f"[{item['check']:>18}] {item['id']:<16}", end=" ", flush=True)
            result = await self.run_item(item)
            self.results.append(result)
            print(f"{result.status:<12} {result.detail[:90]}")
            await asyncio.sleep(PACING_S)
        if not skip_burst and not self.only:
            print("burst mode ...", flush=True)
            await self.run_burst(self.corpus["burst"])
            print(f"burst: {self.burst_summary}")

    def gates(self) -> tuple[dict[str, tuple[bool, str]], str]:
        reachable = [r for r in self.results if r.status not in ("unreachable", "timeout")]
        reach_ratio = len(reachable) / max(1, len(self.results))
        fabrications = [r for r in self.results if r.fabricated]
        omissions = [r for r in self.results if r.silently_omitted]
        fails = [r for r in self.results if r.status == "FAIL"]
        timeouts = [r for r in self.results if r.status == "timeout"]
        calibration_regressions = [
            r for r in fails
            if "known-bad page" in r.detail or "false-positive price warning" in r.detail
        ]

        gates = {
            "fabrication (0 tolerated)": (len(fabrications) == 0, f"{len(fabrications)} pages fabricated figures"),
            "guard calibration (0 regressions)": (
                len(calibration_regressions) == 0,
                "; ".join(f"{r.id}: {r.detail[:60]}" for r in calibration_regressions) or "known-bad warns, known-good silent",
            ),
            "silent omission (<=1)": (len(omissions) <= 1, f"{len(omissions)} pages omitted without warning"),
            "unhandled exceptions (0)": (len(self.exceptions) == 0, f"{len(self.exceptions)}"),
            "cache poison (0)": (len(self.poison_failures) == 0, f"{self.poison_failures or 'none served'}"),
            "timeouts (<=2)": (len(timeouts) <= 2, f"{len(timeouts)}"),
            "baseline drift (0)": (len(self.baseline_drift) == 0, f"{self.baseline_drift or 'stable'}"),
            "hard failures (<=1 beyond the above)": (
                len([f for f in fails if not f.fabricated and not f.silently_omitted]) <= 1,
                "; ".join(f"{f.id}: {f.detail[:60]}" for f in fails) or "none",
            ),
        }
        if reach_ratio < 0.7 and not self.only:
            verdict = f"NO VERDICT — only {reach_ratio:.0%} of corpus reachable today"
        elif (
            not gates["fabrication (0 tolerated)"][0]
            or not gates["cache poison (0)"][0]
            or not gates["guard calibration (0 regressions)"][0]
        ):
            verdict = "RED"
        elif all(ok for ok, _ in gates.values()):
            verdict = "GREEN"
        else:
            verdict = "YELLOW"
        return gates, verdict

    def write_report(self) -> Path:
        from importlib.metadata import version as v

        gates, verdict = self.gates()
        corpus_sha = hashlib.sha256((EVALS_DIR / "corpus.json").read_bytes()).hexdigest()[:12]
        lines = [
            f"# Tearsheet Trust Report — {datetime.now():%Y-%m-%d %H:%M}"
            + (" — PARTIAL RUN (--only)" if self.only else ""),
            "",
            f"**VERDICT: {verdict}**",
            "",
            f"- tearsheet {v('tearsheet')} · trafilatura {v('trafilatura')} · httpx {v('httpx')} "
            f"· lxml {v('lxml')} · python {sys.version.split()[0]}",
            f"- corpus {self.corpus['version']} (sha {corpus_sha}) · "
            f"{len(self.results)} items scored · burst: {self.burst_summary}",
            "",
            "## Gates",
            "",
            "| gate | status | detail |",
            "|---|---|---|",
        ]
        for name, (ok, detail) in gates.items():
            lines.append(f"| {name} | {'PASS' if ok else '**FAIL**'} | {detail} |")
        lines += ["", "## Items", "", "| id | category | status | detail |", "|---|---|---|---|"]
        for r in self.results:
            status = r.status if r.status != "FAIL" else "**FAIL**"
            lines.append(f"| {r.id} | {r.category} | {status} | {r.detail[:100]} |")
        lines += [
            "",
            "## Reading this report",
            "",
            "- `pass` — figures/content verified against the independent oracle.",
            "- `warn-correct` — the tool flagged its own extraction; the warning was warranted.",
            "- `walled` — honest refusal (bot wall / consent wall / HTTP error reported as such).",
            "- `FAIL` — a trust property was violated; see evidence/ for the raw bytes.",
            "- Every item's raw evidence is under `evidence/<id>/` for re-adjudication.",
        ]
        path = self.report_dir / "report.md"
        path.write_text("\n".join(lines))
        return path


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-burst", action="store_true")
    parser.add_argument("--only", help="comma-separated item ids")
    args = parser.parse_args()

    report_dir = EVALS_DIR / "reports" / datetime.now().strftime("%Y-%m-%d")
    report_dir.mkdir(parents=True, exist_ok=True)
    os.environ["TEARSHEET_HOME"] = str(report_dir / "home")  # isolated cache per run

    corpus = json.loads((EVALS_DIR / "corpus.json").read_text())
    ev = Eval(corpus, report_dir, set(args.only.split(",")) if args.only else None)
    await ev.run(skip_burst=args.skip_burst)
    path = ev.write_report()
    gates, verdict = ev.gates()
    print(f"\nVERDICT: {verdict}\nreport: {path}")


if __name__ == "__main__":
    asyncio.run(main())
