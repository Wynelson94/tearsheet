"""Playwright rendering: lazy import, one reused browser, graceful degradation."""

import asyncio
from typing import Any

from tearsheet.config import Settings
from tearsheet.fetch import FetchResult

_GOTO_TIMEOUT_MS = 15000


class RenderUnavailableError(RuntimeError):
    """Playwright (or its chromium binary) is not installed."""


_playwright: Any = None
_browser: Any = None
_lock: asyncio.Lock | None = None


async def render_page(url: str, *, settings: Settings) -> FetchResult:
    """Render a page in headless chromium and return its post-JS HTML."""
    try:
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import TimeoutError as PlaywrightTimeout
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RenderUnavailableError("playwright is not installed") from exc

    global _playwright, _browser, _lock
    if _lock is None:
        _lock = asyncio.Lock()
    async with _lock:
        if _browser is None or not _browser.is_connected():
            try:
                _playwright = await async_playwright().start()
                _browser = await _playwright.chromium.launch(headless=True)
            except PlaywrightError as exc:
                raise RenderUnavailableError(f"chromium launch failed: {exc}") from exc

    context = await _browser.new_context()
    try:
        page = await context.new_page()
        status = 200
        content_type = "text/html"
        try:
            try:
                response = await page.goto(url, wait_until="networkidle", timeout=_GOTO_TIMEOUT_MS)
            except PlaywrightTimeout:
                response = None  # networkidle never settled; the DOM is often still usable
            if response is not None:
                status = response.status
                header = response.headers.get("content-type", "")
                content_type = header.split(";")[0].strip().lower() or "text/html"
            html = await page.content()
            return FetchResult(
                url=url,
                final_url=page.url,
                status=status,
                content_type=content_type,
                body=html.encode(),
                via="playwright",
            )
        except PlaywrightError as exc:
            return FetchResult(
                url=url,
                final_url=url,
                status=0,
                content_type="",
                body=None,
                via="playwright",
                error=f"render failed: {exc}",
            )
    finally:
        await context.close()
