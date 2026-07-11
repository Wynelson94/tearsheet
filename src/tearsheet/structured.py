"""Deterministic structured extraction: JSON-LD, OpenGraph, microdata, HTML tables.

No LLM involved — semantic extraction is the caller's job (Claude reads the markdown).
"""

import json
import time
from typing import Any

import httpx
from lxml import etree
from lxml import html as lxml_html

from tearsheet.cache import Cache, CachedPage
from tearsheet.config import Settings, get_settings
from tearsheet.fetch import fetch_url
from tearsheet.render import RenderUnavailableError, render_page

DEFAULT_TYPES = ["json-ld", "opengraph", "microdata", "tables"]
_EXTRUCT_SYNTAXES = {"json-ld", "opengraph", "microdata"}


async def extract_page(
    url: str,
    *,
    types: list[str] | None = None,
    max_rows: int = 100,
    render: str = "auto",
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """Structured data for a URL, reusing HTML cached by a prior scrape when available."""
    settings = settings or get_settings()
    cache = Cache(settings.cache_db)
    try:
        cached = cache.get_page(url, settings.page_ttl_seconds)
        if cached is not None and cached.html:
            return extract_structured(cached.html, cached.final_url or url, types, max_rows)

        if render == "always":
            try:
                result = await render_page(url, settings=settings)
            except RenderUnavailableError as exc:
                return json.dumps({"url": url, "error": f"rendering unavailable: {exc}"})
        else:
            result = await fetch_url(url, settings=settings, transport=transport)
        if result.error:
            return json.dumps({"url": url, "error": result.error})
        if result.status >= 400:
            return json.dumps({"url": url, "error": f"HTTP {result.status}"})
        body = result.body or b""
        cache.put_page(
            CachedPage(
                url=url,
                final_url=result.final_url,
                fetched_at=int(time.time()),
                status=result.status,
                content_type=result.content_type,
                via=result.via,
                html=body,
                markdown=None,
                title=None,
            )
        )
        return extract_structured(body, result.final_url, types, max_rows)
    finally:
        cache.close()


def extract_structured(
    html: bytes,
    url: str,
    types: list[str] | None = None,
    max_rows: int = 100,
) -> str:
    """JSON text with only the non-empty keys among json_ld/opengraph/microdata/tables."""
    types = types or DEFAULT_TYPES
    out: dict[str, Any] = {"url": url}

    syntaxes = [t for t in types if t in _EXTRUCT_SYNTAXES]
    if syntaxes:
        import extruct  # deferred: heavy import, only needed for this tool

        try:
            data = extruct.extract(html, base_url=url, syntaxes=syntaxes)
        except Exception:
            data = {}
        if data.get("json-ld"):
            out["json_ld"] = data["json-ld"]
        if data.get("opengraph"):
            og: dict[str, str] = {}
            for block in data["opengraph"]:
                og.update(dict(block.get("properties", [])))
            if og:
                out["opengraph"] = og
        if data.get("microdata"):
            out["microdata"] = data["microdata"]

    if "tables" in types:
        tables = _extract_tables(html, max_rows)
        if tables:
            out["tables"] = tables

    if len(out) == 1:  # url only
        out["note"] = "no structured data found"
    return json.dumps(out, indent=1, ensure_ascii=False)


def _extract_tables(html: bytes, max_rows: int) -> list[dict[str, Any]]:
    try:
        tree = lxml_html.fromstring(html)
    except etree.ParserError:
        return []
    tables: list[dict[str, Any]] = []
    for table in tree.xpath("//table"):
        caption = table.xpath("string(.//caption)").strip() or None
        headers = [h.strip() for h in table.xpath(".//th//text()") if h.strip()]
        rows: list[list[str]] = []
        truncated = False
        for tr in table.xpath(".//tr"):
            cells = [
                " ".join(td.xpath("string()").split()) for td in tr.xpath("./td")
            ]
            if not cells:
                continue
            if len(rows) >= max_rows:
                truncated = True
                break
            rows.append(cells)
        if rows or headers:
            tables.append(
                {"caption": caption, "headers": headers, "rows": rows, "truncated": truncated}
            )
    return tables
