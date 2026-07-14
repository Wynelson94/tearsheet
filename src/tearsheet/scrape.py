"""High-level scrape: cache -> fetch (render fallback) -> extract -> token-shaped text."""

import json
import time
from datetime import datetime

import httpx

from tearsheet.cache import Cache, CachedPage
from tearsheet.config import Settings, get_settings
from tearsheet.content import (
    ExtractedContent,
    assess_extraction,
    extract_content,
    html_to_text,
)
from tearsheet.fetch import FetchResult, fetch_url, looks_blocked, needs_render
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


def _consent_message(final_url: str) -> str:
    return (
        f"consent/cookie wall (final url: {final_url}); the extractor saw only a cookie "
        "banner, not the page. The content is likely behind that gate — try raw=true, or "
        "fetch the page independently. Reporting this rather than passing the banner off "
        "as the page."
    )


async def scrape(
    url: str,
    *,
    max_length: int = 8000,
    render: str = "auto",
    include_links: bool = False,
    fresh: bool = False,
    raw: bool = False,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    settings = settings or get_settings()
    cache = Cache(settings.cache_db)
    try:
        if not fresh:
            cached = cache.get_page(url, settings.page_ttl_seconds)
            if cached is not None:
                day = datetime.fromtimestamp(cached.fetched_at).strftime("%Y-%m-%d")
                if cached.html and raw:
                    return _format(
                        url=cached.final_url or url,
                        title=cached.title,
                        fetched_label=f"cache {day} | via: {cached.via} | raw",
                        markdown=html_to_text(cached.html),
                        max_length=max_length,
                        settings=settings,
                    )
                if cached.html:
                    extracted = extract_content(
                        cached.html, url=cached.final_url, include_links=include_links
                    )
                    quality = assess_extraction(cached.html, extracted)
                    # a poisoned row (banner cached as content) must not be served: fall
                    # through to a live fetch rather than replay the bad extraction.
                    if extracted is not None and not quality.consent_wall:
                        return _format(
                            url=cached.final_url or url,
                            title=extracted.title or cached.title,
                            fetched_label=f"cache {day} | via: {cached.via}",
                            markdown=extracted.markdown,
                            max_length=max_length,
                            settings=settings,
                            warnings=quality.warnings,
                        )
                elif cached.markdown:  # html-less entries (e.g. PDFs) keep only markdown
                    return _format(
                        url=cached.final_url or url,
                        title=cached.title,
                        fetched_label=f"cache {day} | via: {cached.via}",
                        markdown=cached.markdown,
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
            if render == "auto" and result.status in (403, 503) and _is_challenge(result.body):
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

        if ct.startswith("text/") and looks_blocked(body):
            return (
                f"blocked by bot protection (final url: {result.final_url});"
                " the site may offer an official API — try that or a manual fetch"
            )

        if ct == "application/pdf":
            text = _extract_pdf_text(body)
            if text is None:
                return f"could not extract text from PDF at {url}"
            cache.put_page(
                CachedPage(
                    url=url,
                    final_url=result.final_url,
                    fetched_at=int(time.time()),
                    status=result.status,
                    content_type=ct,
                    via="pypdf",
                    html=None,
                    markdown=text,
                    title=None,
                )
            )
            return _format(
                url=result.final_url,
                title=None,
                fetched_label="live | via: pypdf",
                markdown=text,
                max_length=max_length,
                settings=settings,
            )
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

        if raw:
            # Deliberately NOT auto-rendered: on smith.ai the rendered DOM was strictly
            # WORSE than the plain fetch (a consent overlay replaced the pricing table the
            # httpx body still carried). raw is the curl-equivalent escape hatch; pass
            # render="always" to force a browser. Never cached — raw text is not markdown.
            text = html_to_text(body)
            if not text:
                return f"no text found at {result.final_url}"
            return _format(
                url=result.final_url,
                title=None,
                fetched_label=f"live | via: {result.via} | raw",
                markdown=text,
                max_length=max_length,
                settings=settings,
            )

        extracted = extract_content(body, url=result.final_url, include_links=include_links)
        # tiny extraction triggers a render attempt even without shell markers (custom
        # SPA mounts); keep-whichever-extracts-more decides. crawl stays marker-based.
        should_attempt = _needs_more(body, extracted) or _tiny(extracted)
        if should_attempt and render == "auto" and result.via != "playwright":
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

        quality = assess_extraction(body, extracted)
        if quality.consent_wall:
            return _consent_message(result.final_url)  # never cached: it isn't the page

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
        warnings = list(quality.warnings)
        if warning:
            warnings.append(warning)
        return _format(
            url=result.final_url,
            title=extracted.title,
            fetched_label=f"live | via: {result.via}",
            markdown=extracted.markdown,
            max_length=max_length,
            settings=settings,
            warnings=warnings,
        )
    finally:
        cache.close()


def _needs_more(body: bytes, extracted: ExtractedContent | None) -> bool:
    return extracted is None or needs_render(body, extracted.markdown)


def _tiny(extracted: ExtractedContent | None) -> bool:
    return extracted is None or len(extracted.markdown) < 250


def _extract_pdf_text(body: bytes) -> str | None:
    from io import BytesIO

    from pypdf import PdfReader  # deferred: only needed for PDF responses

    try:
        reader = PdfReader(BytesIO(body))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception:
        return None
    text = "\n\n".join(p.strip() for p in pages if p.strip())
    return text or None


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
    warnings: list[str] | None = None,
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
    lines.extend([f"fetched: {fetched_label}", tokens_line])
    lines.extend(f"warning: {w}" for w in warnings or [])
    lines.extend(["---", shown])
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
