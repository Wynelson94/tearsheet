"""Async fetching: httpx fast path, streaming size cap, JS-shell detection."""

import re
from dataclasses import dataclass

import httpx

from tearsheet.config import Settings

_SPA_MARKERS = (
    b'id="root"',
    b'id="app"',
    b'id="__next"',
    b"__NUXT__",
    b"data-reactroot",
)
_NOSCRIPT_RE = re.compile(rb"<noscript[^>]*>.{0,400}?(enable\s+javascript|javascript\s+is\s+required)", re.IGNORECASE | re.DOTALL)


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str
    body: bytes | None
    via: str = "httpx"
    error: str | None = None


async def fetch_url(
    url: str,
    *,
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FetchResult:
    headers = {
        "User-Agent": settings.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=settings.timeout_seconds,
            headers=headers,
            transport=transport,
        ) as client, client.stream("GET", url) as response:
            content_type = (
                response.headers.get("content-type", "").split(";")[0].strip().lower()
            )
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > settings.max_response_bytes:
                    return FetchResult(
                        url=url,
                        final_url=str(response.url),
                        status=response.status_code,
                        content_type=content_type,
                        body=None,
                        error=f"response too large (>{settings.max_response_bytes} bytes)",
                    )
                chunks.append(chunk)
            return FetchResult(
                url=url,
                final_url=str(response.url),
                status=response.status_code,
                content_type=content_type,
                body=b"".join(chunks),
            )
    except httpx.HTTPError as exc:
        return FetchResult(
            url=url,
            final_url=url,
            status=0,
            content_type="",
            body=None,
            error=f"{type(exc).__name__}: {exc}",
        )


def needs_render(html: bytes, extracted_text: str | None) -> bool:
    """True when a fetched page looks like an empty JS shell worth re-rendering."""
    if extracted_text is not None and len(extracted_text) >= 250:
        return False
    if _NOSCRIPT_RE.search(html):
        return True
    if any(marker in html for marker in _SPA_MARKERS):
        return True
    if html:
        script_bytes = sum(len(m) for m in re.findall(rb"<script\b.*?</script>", html, re.DOTALL))
        if script_bytes / len(html) > 0.6:
            return True
    return False
