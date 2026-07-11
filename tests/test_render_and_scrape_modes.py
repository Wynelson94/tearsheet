from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from tearsheet.fetch import FetchResult
from tearsheet.render import RenderUnavailableError
from tearsheet.scrape import scrape

RENDERED_HTML = (
    b"<html><head><title>Rendered App</title></head><body><main><h1>Rendered App</h1>"
    b"<p>This content only exists after JavaScript runs. It describes the dashboard, "
    b"its filters, and enough prose that the extractor is fully satisfied with what it "
    b"finds here. The renderer earned its keep on this page, no question about it.</p>"
    b"</main></body></html>"
)


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    monkeypatch.setenv("TEARSHEET_HOME", str(home))
    return home


@pytest.fixture
def spa_transport(fixture_bytes: Callable[[str], bytes]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=fixture_bytes("spa_shell.html"), headers={"content-type": "text/html"}
        )

    return httpx.MockTransport(handler)


@pytest.fixture
def fake_renderer(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    calls: dict[str, object] = {"count": 0}

    async def fake_render(url: str, *, settings: object) -> FetchResult:
        calls["count"] = calls["count"] + 1  # type: ignore[operator]
        calls["url"] = url
        return FetchResult(
            url=url, final_url=url, status=200, content_type="text/html",
            body=RENDERED_HTML, via="playwright",
        )

    monkeypatch.setattr("tearsheet.scrape.render_page", fake_render)
    return calls


class TestRenderAuto:
    async def test_spa_shell_triggers_renderer(
        self, spa_transport: httpx.MockTransport, fake_renderer: dict[str, object]
    ) -> None:
        out = await scrape("https://example.com/app", transport=spa_transport)
        assert fake_renderer["count"] == 1
        assert "via: playwright" in out
        assert "Rendered App" in out

    async def test_static_page_never_renders(
        self, fixture_bytes: Callable[[str], bytes], fake_renderer: dict[str, object]
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=fixture_bytes("article.html"), headers={"content-type": "text/html"}
            )

        out = await scrape("https://example.com/essay", transport=httpx.MockTransport(handler))
        assert fake_renderer["count"] == 0
        assert "via: httpx" in out

    async def test_challenge_status_triggers_one_render(
        self, fake_renderer: dict[str, object]
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                403, content=b"<html><body>Just a moment...</body></html>",
                headers={"content-type": "text/html"},
            )

        out = await scrape("https://example.com/guarded", transport=httpx.MockTransport(handler))
        assert fake_renderer["count"] == 1
        assert "Rendered App" in out


CUSTOM_MOUNT_SPA = (
    b"<html><head><title>React \xe2\x80\xa2 TodoMVC</title></head><body>"
    b"<div>This is just a demo banner, quite short.</div>"
    b'<section class="todoapp"></section>'
    b"<footer><p>Double-click to edit a todo</p></footer>"
    b"</body></html>"
)


class TestTinyExtractionRenderAttempt:
    """SPAs with custom mount points have no shell markers — tiny extraction alone
    must trigger one render attempt in auto mode (keep-better logic decides)."""

    @pytest.fixture
    def custom_mount_transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=CUSTOM_MOUNT_SPA, headers={"content-type": "text/html"}
            )

        return httpx.MockTransport(handler)

    async def test_custom_mount_spa_upgrades_to_rendered(
        self, custom_mount_transport: httpx.MockTransport, fake_renderer: dict[str, object]
    ) -> None:
        out = await scrape("https://example.com/todo", transport=custom_mount_transport)
        assert fake_renderer["count"] == 1
        assert "via: playwright" in out
        assert "Rendered App" in out

    async def test_httpx_kept_when_render_is_not_better(
        self,
        custom_mount_transport: httpx.MockTransport,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def render_worse(url: str, *, settings: object) -> FetchResult:
            return FetchResult(
                url=url, final_url=url, status=200, content_type="text/html",
                body=b"<html><body><p>tiny</p></body></html>", via="playwright",
            )

        monkeypatch.setattr("tearsheet.scrape.render_page", render_worse)
        out = await scrape("https://example.com/todo", transport=custom_mount_transport)
        assert "via: httpx" in out
        assert "demo banner" in out

    async def test_never_mode_skips_the_attempt(
        self, custom_mount_transport: httpx.MockTransport, fake_renderer: dict[str, object]
    ) -> None:
        out = await scrape(
            "https://example.com/todo", render="never", transport=custom_mount_transport
        )
        assert fake_renderer["count"] == 0
        assert "via: httpx" in out


class TestRenderNever:
    async def test_never_mode_reports_shell_without_rendering(
        self, spa_transport: httpx.MockTransport, fake_renderer: dict[str, object]
    ) -> None:
        out = await scrape("https://example.com/app", render="never", transport=spa_transport)
        assert fake_renderer["count"] == 0
        assert "no extractable content" in out.lower()


class TestRenderAlways:
    async def test_always_mode_skips_httpx(
        self, fake_renderer: dict[str, object]
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("httpx should not be used when render='always'")

        out = await scrape(
            "https://example.com/app", render="always", transport=httpx.MockTransport(handler)
        )
        assert fake_renderer["count"] == 1
        assert "via: playwright" in out


class TestRendererUnavailable:
    async def test_degrades_with_warning(
        self, spa_transport: httpx.MockTransport, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def unavailable(url: str, *, settings: object) -> FetchResult:
            raise RenderUnavailableError("playwright is not installed")

        monkeypatch.setattr("tearsheet.scrape.render_page", unavailable)
        out = await scrape("https://example.com/app", transport=spa_transport)
        assert "playwright install chromium" in out
        assert "no extractable content" in out.lower()


class TestRenderedResultCached:
    async def test_rendered_page_cached_as_playwright(
        self, spa_transport: httpx.MockTransport, fake_renderer: dict[str, object]
    ) -> None:
        await scrape("https://example.com/app", transport=spa_transport)
        out = await scrape("https://example.com/app", transport=spa_transport)
        assert fake_renderer["count"] == 1  # second call served from cache
        assert "cache" in out
        assert "via: playwright" in out
