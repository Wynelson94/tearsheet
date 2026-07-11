"""High-level scrape: cache -> fetch (render fallback) -> extract -> token-shaped text."""

import json
import time
from datetime import datetime

import httpx

from tearsheet.cache import Cache, CachedPage
from tearsheet.config import Settings, get_settings
from tearsheet.content import ExtractedContent, extract_content
from tearsheet.fetch import FetchResult, fetch_url, needs_render
from tearsheet.output import estimate_tokens, truncate
from tearsheet.render import RenderUnavailableError, render_page
from tearsheet.urls import url_hash

_JS_HINT = "no extractable content: the page looks like a JavaScript app shell."
_INSTALL_HINT = "run 'playwright install chromium' to enable rendering"
_CHALLENGE_MARKERS = (b"just a moment", b"cf-chl")


def _is_challenge(body: bytes | None) -> bool:
    if not body:
        return False
    lowered = body[:4096].lower()
    return any(marker in lowered for marker in _CHALLENGE_MARKERS)


async def scrape(
    url: str,
    *,
    max_length: int = 8000,
    render: str = "auto",
    include_links: bool = False,
    fresh: bool = False,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    settings = settings or get_settings()
    cache = Cache(settings.cache_db)
    try:
        if not fresh:
            cached = cache.get_page(url, settings.page_ttl_seconds)
            if cached is not None and cached.html:
                extracted = extract_content(
                    cached.html, url=cached.final_url, include_links=include_links
                )
                if extracted is not None:
                    day = datetime.fromtimestamp(cached.fetched_at).strftime("%Y-%m-%d")
                    return _format(
                        url=cached.final_url or url,
                        title=extracted.title or cached.title,
                        fetched_label=f"cache {day} | via: {cached.via}",
                        markdown=extracted.markdown,
                        max_length=max_length,
                        settings=settings,
                    )

        warning: str | None = None
        if render == "always":
            try:
                result = await render_page(url, settings=settings)
            except RenderUnavailableError as exc:
                return f"rendering unavailable ({exc}); {_INSTALL_HINT}"
        else:
            result = await fetch_url(url, settings=settings, transport=transport)
            if (
                render == "auto"
                and result.status in (403, 503)
                and _is_challenge(result.body)
            ):
                rendered = await _try_render(url, settings)
                if isinstance(rendered, FetchResult) and not rendered.error:
                    result = rendered
                elif isinstance(rendered, str):
                    warning = rendered

        if result.error:
            return f"error fetching {url}: {result.error}"
        if result.status >= 400:
            return f"error fetching {url}: HTTP {result.status}"
        body = result.body or b""
        ct = result.content_type

        if ct == "application/json" or ct.endswith("+json"):
            return _format_json(result.final_url, body, max_length, result.via)
        if ct == "text/plain":
            return _format(
                url=result.final_url,
                title=None,
                fetched_label=f"live | via: {result.via}",
                markdown=body.decode("utf-8", errors="replace"),
                max_length=max_length,
                settings=settings,
            )
        if ct and not ct.startswith("text/") and ct != "application/xhtml+xml":
            return f"unsupported content type '{ct}' at {url}"

        extracted = extract_content(body, url=result.final_url, include_links=include_links)
        if _needs_more(body, extracted) and render == "auto" and result.via != "playwright":
            rendered = await _try_render(url, settings)
            if isinstance(rendered, str):
                warning = rendered
            elif rendered.body and not rendered.error:
                re_extracted = extract_content(
                    rendered.body, url=rendered.final_url, include_links=include_links
                )
                if re_extracted is not None and (
                    extracted is None or len(re_extracted.markdown) > len(extracted.markdown)
                ):
                    result, body, extracted = rendered, rendered.body, re_extracted

        if _needs_more(body, extracted) or extracted is None:
            message = f"{_JS_HINT} (url: {result.final_url})"
            if warning:
                message += f"\nwarning: {warning}"
            return message

        cache.put_page(
            CachedPage(
                url=url,
                final_url=result.final_url,
                fetched_at=int(time.time()),
                status=result.status,
                content_type=ct,
                via=result.via,
                html=body,
                markdown=extracted.markdown,
                title=extracted.title,
            )
        )
        return _format(
            url=result.final_url,
            title=extracted.title,
            fetched_label=f"live | via: {result.via}",
            markdown=extracted.markdown,
            max_length=max_length,
            settings=settings,
        )
    finally:
        cache.close()


def _needs_more(body: bytes, extracted: ExtractedContent | None) -> bool:
    return extracted is None or needs_render(body, extracted.markdown)


async def _try_render(url: str, settings: Settings) -> FetchResult | str:
    """A FetchResult on success, or a warning string when rendering is unavailable."""
    try:
        return await render_page(url, settings=settings)
    except RenderUnavailableError:
        return _INSTALL_HINT


def _format(
    *,
    url: str,
    title: str | None,
    fetched_label: str,
    markdown: str,
    max_length: int,
    settings: Settings,
) -> str:
    settings.pages_dir.mkdir(parents=True, exist_ok=True)
    full_path = settings.pages_dir / f"{url_hash(url)[:12]}.md"
    full_path.write_text(markdown)
    shown, truncated = truncate(markdown, max_length)
    total = estimate_tokens(markdown)
    if truncated:
        tokens_line = (
            f"tokens: ~{estimate_tokens(shown)} of ~{total} (truncated; full copy: {full_path})"
        )
    else:
        tokens_line = f"tokens: ~{total}"
    lines = [f"url: {url}"]
    if title:
        lines.append(f"title: {title}")
    lines.extend([f"fetched: {fetched_label}", tokens_line, "---", shown])
    return "\n".join(lines)


def _format_json(url: str, body: bytes, max_length: int, via: str) -> str:
    try:
        pretty = json.dumps(json.loads(body), indent=2, sort_keys=True)
    except ValueError:
        pretty = body.decode("utf-8", errors="replace")
    shown, truncated = truncate(pretty, max_length)
    suffix = " (truncated)" if truncated else ""
    return (
        f"url: {url}\nfetched: live | via: {via}\n"
        f"tokens: ~{estimate_tokens(shown)}{suffix}\n---\n{shown}"
    )
