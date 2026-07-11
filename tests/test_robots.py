from pathlib import Path

import httpx
import pytest

from tearsheet.cache import Cache
from tearsheet.config import get_settings
from tearsheet.robots import get_policy

ROBOTS_BODY = """User-agent: *
Disallow: /admin
Disallow: /private/
Crawl-delay: 2.5
"""

SLOW_ROBOTS = """User-agent: *
Crawl-delay: 99
"""


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(tmp_path / "cache.db")


def robots_transport(body: str | None, calls: dict[str, int] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls["count"] = calls.get("count", 0) + 1
        if request.url.path == "/robots.txt":
            if body is None:
                return httpx.Response(404, text="not found")
            return httpx.Response(200, text=body)
        return httpx.Response(200, html="<html></html>")

    return httpx.MockTransport(handler)


class TestPolicy:
    async def test_disallowed_path_blocked(self, cache: Cache) -> None:
        policy = await get_policy(
            "https://example.com/docs", cache=cache, settings=get_settings(),
            transport=robots_transport(ROBOTS_BODY),
        )
        assert policy.allowed("https://example.com/admin/panel") is False
        assert policy.allowed("https://example.com/private/x") is False

    async def test_other_paths_allowed(self, cache: Cache) -> None:
        policy = await get_policy(
            "https://example.com/docs", cache=cache, settings=get_settings(),
            transport=robots_transport(ROBOTS_BODY),
        )
        assert policy.allowed("https://example.com/docs/intro") is True

    async def test_missing_robots_allows_everything(self, cache: Cache) -> None:
        policy = await get_policy(
            "https://example.com", cache=cache, settings=get_settings(),
            transport=robots_transport(None),
        )
        assert policy.allowed("https://example.com/anything") is True
        assert policy.crawl_delay is None

    async def test_crawl_delay_parsed(self, cache: Cache) -> None:
        policy = await get_policy(
            "https://example.com", cache=cache, settings=get_settings(),
            transport=robots_transport(ROBOTS_BODY),
        )
        assert policy.crawl_delay == 2.5

    async def test_crawl_delay_capped_at_ten(self, cache: Cache) -> None:
        policy = await get_policy(
            "https://example.com", cache=cache, settings=get_settings(),
            transport=robots_transport(SLOW_ROBOTS),
        )
        assert policy.crawl_delay == 10.0

    async def test_second_call_uses_cache(self, cache: Cache) -> None:
        calls: dict[str, int] = {}
        transport = robots_transport(ROBOTS_BODY, calls)
        await get_policy("https://example.com", cache=cache, settings=get_settings(), transport=transport)
        policy = await get_policy(
            "https://example.com", cache=cache, settings=get_settings(), transport=transport
        )
        assert calls["count"] == 1
        assert policy.allowed("https://example.com/admin") is False
