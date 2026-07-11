import httpx
import pytest

from tearsheet.config import get_settings
from tearsheet.fetch import fetch_url


def transport_for(handler):  # type: ignore[no-untyped-def]
    return httpx.MockTransport(handler)


class TestFetchUrl:
    async def test_returns_body_and_content_type(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, html="<html><body>hello</body></html>", headers={"content-type": "text/html; charset=utf-8"}
            )

        result = await fetch_url(
            "https://example.com/a", settings=get_settings(), transport=transport_for(handler)
        )
        assert result.status == 200
        assert result.content_type == "text/html"
        assert result.body is not None
        assert b"hello" in result.body
        assert result.via == "httpx"
        assert result.error is None

    async def test_follows_redirects_and_reports_final_url(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/old":
                return httpx.Response(301, headers={"location": "https://example.com/new"})
            return httpx.Response(200, html="<html><body>moved</body></html>")

        result = await fetch_url(
            "https://example.com/old", settings=get_settings(), transport=transport_for(handler)
        )
        assert result.status == 200
        assert result.final_url == "https://example.com/new"

    async def test_sends_configured_user_agent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["ua"] = request.headers["user-agent"]
            return httpx.Response(200, html="<html></html>")

        monkeypatch.setenv("TEARSHEET_UA", "TestAgent/9")
        await fetch_url(
            "https://example.com/a", settings=get_settings(), transport=transport_for(handler)
        )
        assert seen["ua"] == "TestAgent/9"

    async def test_oversize_response_aborts_with_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"x" * 2000, headers={"content-type": "text/html"})

        settings = get_settings()
        small = settings.__class__(**{**settings.__dict__, "max_response_bytes": 1000})
        result = await fetch_url(
            "https://example.com/big", settings=small, transport=transport_for(handler)
        )
        assert result.body is None
        assert result.error is not None
        assert "large" in result.error.lower()

    async def test_network_error_captured_not_raised(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        result = await fetch_url(
            "https://example.com/a", settings=get_settings(), transport=transport_for(handler)
        )
        assert result.status == 0
        assert result.error is not None
        assert "boom" in result.error
