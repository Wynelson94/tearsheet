"""Trafilatura wrapper: HTML bytes -> main-content markdown + metadata, plus quality guards."""

import html as html_module
import re
from dataclasses import dataclass, field
from itertools import groupby

_SCRIPT_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")
_MONEY = re.compile(r"\$[0-9][0-9,]*(?:\.[0-9]{2})?")

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

# A page whose markup is huge but whose visible text is a rounding error never
# rendered its content (smith.ai: 96 KB of markup, 1,267 chars of text).
_GATED_MIN_HTML = 50_000
_GATED_MAX_TEXT = 2_000

# Dropped-price guard. Calibrated on real pages: quo kept 17% of 24 prices (bad),
# heyrosie kept 100% of 5 (good). Require enough prices that a stray footer figure
# on a blog can't trip it.
_MONEY_MIN_ON_PAGE = 4
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
    """Post-extraction verdict. `consent_wall` is fatal; `warnings` ride along with content."""

    consent_wall: bool = False
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

    if len(html) > _GATED_MIN_HTML and len(page_text) < _GATED_MAX_TEXT:
        quality.warnings.append(
            f"page markup is {len(html) // 1024} KB but holds only ~{len(page_text)} chars of "
            "visible text — content is likely gated or never rendered. Try raw=true, or fetch "
            "independently."
        )

    on_page = set(_MONEY.findall(page_text))
    if len(on_page) >= _MONEY_MIN_ON_PAGE:
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
