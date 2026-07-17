"""Trafilatura wrapper: HTML bytes -> main-content markdown + metadata, plus quality guards."""

import html as html_module
import re
from dataclasses import dataclass, field
from itertools import groupby

_SCRIPT_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")
_MONEY = re.compile(r"[$€£][0-9][0-9,]*(?:\.[0-9]{2})?")

# Strong phrases + a size guard, mirroring fetch.looks_blocked: a page that merely
# DISCUSSES cookie consent is long; a page that IS a consent wall is short.
_CONSENT_PHRASES = (
    "we use cookies",
    "do not sell or share my personal information",
    "save my preferences",
    "accept all cookies",
    "manage preferences",
    "your privacy choices",
)
_CONSENT_MAX_CHARS = 2_000

# Post-extraction bot-wall backstop. fetch.looks_blocked guards the RAW body and
# deliberately bails above 30 KB (articles about captchas are long) — but real
# challenge pages CAN exceed 30 KB once their JS is inlined, sail past that guard,
# extract to a short wall message, and get cached as "content" for the whole TTL.
# Same lesson as the consent wall: when the extraction IS the wall, catch it here,
# regardless of body size. Keep phrases in sync with fetch._BLOCK_MARKERS.
_BLOCK_PHRASES = (
    "complete the captcha",
    "solve the captcha",
    "flagged as potentially automated",
    "attention required",
    "verify you are a human",
    "are you a robot",
    "enable javascript and cookies to continue",
    "checking your browser",
)
# Tighter than the consent threshold on purpose: real challenge pages extract to a
# few hundred chars (the whole page IS the message), while even a SHORT legitimate
# article that quotes captcha phrasing runs well past this (article.html fixture with
# an added captcha sentence extracts to ~1,576 chars). Calibrated between those.
_BLOCK_MAX_CHARS = 600

# A page whose markup is huge but whose visible text is a rounding error never
# rendered its content (smith.ai: 96 KB of markup, 1,267 chars of text).
_GATED_MIN_HTML = 50_000
_GATED_MAX_TEXT = 2_000

# Dropped-price guard. Calibrated on real pages: quo kept 17% of 24 prices (bad),
# heyrosie kept 100% of 5 (good). Arming requires a price CLUSTER, not a page-wide
# count: pricing pages carry figures in a grid (quo max 17 distinct in one 1,500-char
# window, smith.ai 7, heyrosie 5), while articles scatter real-but-peripheral dollar
# amounts through prose and related-content cards (the 2026-07-14 LinkedIn false
# positive: 4 figures page-wide, never more than 3 near each other). Page-wide counts
# cannot tell those apart; clusters separate the calibration set with margin (3 vs 5).
_MONEY_MIN_CLUSTERED = 4
_MONEY_CLUSTER_WINDOW = 1_500
_MONEY_MIN_RETAINED = 0.5

# A collapsed table column reads as a run of identical consecutive rows
# (quo: `Unlimited* / Unlimited* / Unlimited*`). One run happens naturally; two is a pattern.
_COLLAPSE_RUN_LEN = 3
_COLLAPSE_MIN_RUNS = 2
_COLLAPSE_MAX_LINE = 80


@dataclass
class ExtractedContent:
    markdown: str
    title: str | None
    description: str | None


@dataclass
class ExtractionQuality:
    """Post-extraction verdict. `consent_wall`/`block_wall` are fatal; `warnings` ride along."""

    consent_wall: bool = False
    block_wall: bool = False
    warnings: list[str] = field(default_factory=list)


def html_to_text(html: bytes) -> str:
    """Visible text of a page: scripts/styles gone, tags dropped, entities decoded.

    Doubles as the `raw` escape hatch — it is the curl-plus-strip recovery that
    repeatedly beat trafilatura on JS-tabbed and grid-rendered pricing pages.
    """
    if not html:
        return ""
    text = _SCRIPT_STYLE.sub(" ", html.decode("utf-8", errors="replace"))
    text = html_module.unescape(_TAG.sub(" ", text))
    return _WHITESPACE.sub(" ", text).strip()


def _has_price_cluster(page_text: str) -> bool:
    """True when some 1,500-char window of visible text holds >= 4 distinct figures."""
    hits = [(m.start(), m.group()) for m in _MONEY.finditer(page_text)]
    if len(hits) < _MONEY_MIN_CLUSTERED:
        return False
    left = 0
    window: dict[str, int] = {}
    for pos, figure in hits:
        window[figure] = window.get(figure, 0) + 1
        while pos - hits[left][0] > _MONEY_CLUSTER_WINDOW:
            gone = hits[left][1]
            window[gone] -= 1
            if not window[gone]:
                del window[gone]
            left += 1
        if len(window) >= _MONEY_MIN_CLUSTERED:
            return True
    return False


def _has_collapsed_columns(markdown: str) -> bool:
    lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    runs = sum(
        1
        for line, group in groupby(lines)
        if len(line) < _COLLAPSE_MAX_LINE and len(list(group)) >= _COLLAPSE_RUN_LEN
    )
    return runs >= _COLLAPSE_MIN_RUNS


def assess_extraction(html: bytes, extracted: ExtractedContent | None) -> ExtractionQuality:
    """Judge an extraction against the page it came from.

    Catches the two failure classes that reached real research (2026-07-14): a consent
    banner served as content, and a pricing table whose figures never survived. Deliberately
    NOT a markdown/text yield ratio — measured against both real failures, a ratio fires on
    neither (smith.ai yields 34%, quo 21%) and would only add false positives.
    """
    quality = ExtractionQuality()
    if extracted is None:
        return quality
    markdown = extracted.markdown
    page_text = html_to_text(html)
    lowered = markdown.lower()

    if len(markdown) < _CONSENT_MAX_CHARS and any(p in lowered for p in _CONSENT_PHRASES):
        quality.consent_wall = True
        return quality

    if len(markdown) < _BLOCK_MAX_CHARS and any(p in lowered for p in _BLOCK_PHRASES):
        quality.block_wall = True
        return quality

    if len(html) > _GATED_MIN_HTML and len(page_text) < _GATED_MAX_TEXT:
        quality.warnings.append(
            f"page markup is {len(html) // 1024} KB but holds only ~{len(page_text)} chars of "
            "visible text — content is likely gated or never rendered. Try raw=true, or fetch "
            "independently."
        )

    on_page = set(_MONEY.findall(page_text))
    if _has_price_cluster(page_text):
        kept = on_page & set(_MONEY.findall(markdown))
        if len(kept) / len(on_page) < _MONEY_MIN_RETAINED:
            quality.warnings.append(
                f"extraction dropped {len(on_page) - len(kept)} of {len(on_page)} distinct prices "
                "present on the page — the figures you want are probably missing. "
                "Use raw=true and read the numbers yourself."
            )

    if _has_collapsed_columns(markdown):
        quality.warnings.append(
            "repeated identical rows suggest a multi-column table collapsed; which value "
            "belongs to which plan is NOT reliable here. Use raw=true for the real table."
        )
    return quality


def extract_content(
    html: bytes, url: str | None = None, include_links: bool = False
) -> ExtractedContent | None:
    """Extract main content as markdown. Returns None when nothing extractable.

    Takes bytes (not str) so trafilatura's charset detection handles mislabeled pages.
    """
    import trafilatura  # deferred: heavy import (lxml) would stall MCP server startup

    if not html:
        return None
    markdown = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_links=include_links,
        include_tables=True,
    )
    if not markdown or not markdown.strip():
        return None
    title = description = None
    try:
        meta = trafilatura.extract_metadata(html, default_url=url)
        if meta is not None:
            title = meta.title or None
            description = meta.description or None
    except Exception:
        pass  # metadata is best-effort; the markdown is the product
    return ExtractedContent(markdown=markdown, title=title, description=description)
