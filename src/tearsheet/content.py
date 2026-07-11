"""Trafilatura wrapper: HTML bytes -> main-content markdown + metadata."""

from dataclasses import dataclass


@dataclass
class ExtractedContent:
    markdown: str
    title: str | None
    description: str | None


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
