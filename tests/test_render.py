"""Real render.py coverage — the module every other test monkeypatches away.

Runs REAL chromium against a local 127.0.0.1 server (loopback is exempt from the
offline socket guard; networkidle needs real requests, so no file:// shortcuts).
Marked `playwright`, deselected by default:  pytest -m playwright
"""

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import tearsheet.render as render_mod
from tearsheet.config import get_settings
from tearsheet.render import render_page

# One event loop for the whole module: render.py holds a global browser bound to
# the loop that launched it; per-test loops would deadlock every test after the first.
pytestmark = [pytest.mark.playwright, pytest.mark.asyncio(loop_scope="module")]


@pytest.fixture(scope="module", autouse=True)
async def _close_browser_after_module() -> "Iterator[None]":  # type: ignore[misc]
    yield
    if render_mod._browser is not None and render_mod._browser.is_connected():
        await render_mod._browser.close()
    if render_mod._playwright is not None:
        await render_mod._playwright.stop()
    render_mod._browser = None
    render_mod._playwright = None
    render_mod._lock = None

DELAYED_JS_PAGE = b"""<html><head><title>Delayed</title></head><body>
<div id="out">EMPTY_SHELL</div>
<script>setTimeout(function () {
  document.getElementById('out').textContent = 'RENDERED_CONTENT_TOKEN';
}, 300);</script>
</body></html>"""

NEVER_IDLE_PAGE = b"""<html><head><title>Busy</title></head><body>
<div id="out">BUSY_PAGE_DOM</div>
<script>setInterval(function () { fetch('/ping').catch(function () {}); }, 150);</script>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        routes = {
            "/delayed": (200, "text/html", DELAYED_JS_PAGE),
            "/busy": (200, "text/html", NEVER_IDLE_PAGE),
            "/ping": (200, "text/plain", b"pong"),
        }
        status, ctype, body = routes.get(self.path, (404, "text/plain", b"nope"))
        self.send_response(status)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # silence request logging
        pass


@pytest.fixture(scope="module")
def local_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


class TestRenderHappyPath:
    async def test_js_injected_content_is_captured(self, local_server: str) -> None:
        result = await render_page(f"{local_server}/delayed", settings=get_settings())
        assert result.error is None
        assert result.via == "playwright"
        assert result.status == 200
        assert result.body is not None
        assert b"RENDERED_CONTENT_TOKEN" in result.body  # post-JS DOM, not the shell

    async def test_content_type_parsed_from_response(self, local_server: str) -> None:
        result = await render_page(f"{local_server}/delayed", settings=get_settings())
        assert result.content_type == "text/html"


class TestNetworkidleTimeout:
    async def test_never_idle_page_still_returns_dom(
        self, local_server: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """networkidle never settles on a polling page; the goto times out and the
        DOM must still come back usable (the documented degradation path)."""
        monkeypatch.setattr(render_mod, "_GOTO_TIMEOUT_MS", 1_500)
        result = await render_page(f"{local_server}/busy", settings=get_settings())
        assert result.error is None
        assert result.body is not None
        assert b"BUSY_PAGE_DOM" in result.body


class TestBrowserLifecycle:
    async def test_browser_is_reused_across_renders(self, local_server: str) -> None:
        await render_page(f"{local_server}/delayed", settings=get_settings())
        first = render_mod._browser
        await render_page(f"{local_server}/delayed", settings=get_settings())
        assert render_mod._browser is first  # one browser, not one per call

    async def test_relaunch_after_disconnect(self, local_server: str) -> None:
        await render_page(f"{local_server}/delayed", settings=get_settings())
        assert render_mod._browser is not None
        await render_mod._browser.close()
        result = await render_page(f"{local_server}/delayed", settings=get_settings())
        assert result.error is None
        assert result.body is not None and b"RENDERED_CONTENT_TOKEN" in result.body

    async def test_soak_thirty_renders_no_context_leak(self, local_server: str) -> None:
        """Heavy-usage soak: contexts must be closed per render, browser reused.
        A leak here is how a week-long MCP session dies."""
        for _ in range(30):
            result = await render_page(f"{local_server}/delayed", settings=get_settings())
            assert result.error is None
        assert render_mod._browser is not None
        assert render_mod._browser.is_connected()
        assert len(render_mod._browser.contexts) == 0  # every context closed
