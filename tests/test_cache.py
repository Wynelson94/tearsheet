import time
from pathlib import Path

import pytest

from tearsheet.cache import Cache, CachedPage


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(tmp_path / "cache.db")


def make_page(url: str = "https://example.com/a", via: str = "httpx", **kw: object) -> CachedPage:
    defaults: dict[str, object] = {
        "url": url,
        "final_url": url,
        "fetched_at": int(time.time()),
        "status": 200,
        "content_type": "text/html",
        "via": via,
        "html": b"<html><body>hi</body></html>",
        "markdown": "hi",
        "title": "Hi",
    }
    defaults.update(kw)
    return CachedPage(**defaults)  # type: ignore[arg-type]


class TestPageRoundtrip:
    def test_put_then_get(self, cache: Cache) -> None:
        cache.put_page(make_page())
        got = cache.get_page("https://example.com/a", ttl_seconds=3600)
        assert got is not None
        assert got.markdown == "hi"
        assert got.title == "Hi"
        assert got.html == b"<html><body>hi</body></html>"
        assert got.via == "httpx"

    def test_missing_returns_none(self, cache: Cache) -> None:
        assert cache.get_page("https://example.com/nope", ttl_seconds=3600) is None

    def test_url_variants_hit_same_entry(self, cache: Cache) -> None:
        cache.put_page(make_page("https://example.com/a?b=2&a=1"))
        assert cache.get_page("https://Example.com/a?a=1&b=2#frag", ttl_seconds=3600) is not None


class TestTtl:
    def test_expired_entry_returns_none(self, cache: Cache) -> None:
        cache.put_page(make_page(fetched_at=int(time.time()) - 7200))
        assert cache.get_page("https://example.com/a", ttl_seconds=3600) is None

    def test_fresh_entry_within_ttl(self, cache: Cache) -> None:
        cache.put_page(make_page(fetched_at=int(time.time()) - 100))
        assert cache.get_page("https://example.com/a", ttl_seconds=3600) is not None


class TestRenderPreference:
    def test_httpx_does_not_overwrite_playwright(self, cache: Cache) -> None:
        cache.put_page(make_page(via="playwright", markdown="rendered"))
        cache.put_page(make_page(via="httpx", markdown="shell"))
        got = cache.get_page("https://example.com/a", ttl_seconds=3600)
        assert got is not None
        assert got.via == "playwright"
        assert got.markdown == "rendered"

    def test_playwright_overwrites_httpx(self, cache: Cache) -> None:
        cache.put_page(make_page(via="httpx", markdown="shell"))
        cache.put_page(make_page(via="playwright", markdown="rendered"))
        got = cache.get_page("https://example.com/a", ttl_seconds=3600)
        assert got is not None
        assert got.via == "playwright"


class TestEviction:
    def test_prune_removes_only_old_pages(self, cache: Cache) -> None:
        now = int(time.time())
        cache.put_page(make_page("https://example.com/old", fetched_at=now - 40 * 86400))
        cache.put_page(make_page("https://example.com/fresh", fetched_at=now - 3600))
        removed = cache.prune(older_than_seconds=30 * 86400)
        assert removed == 1
        assert cache.get_page("https://example.com/fresh", ttl_seconds=86400) is not None
        # even a generous TTL can't resurrect the pruned row
        assert cache.get_page("https://example.com/old", ttl_seconds=10**9) is None

    def test_prune_also_drops_stale_robots(self, cache: Cache) -> None:
        cache.put_robots("https://example.com", "User-agent: *", None)
        removed = cache.prune(older_than_seconds=0)
        assert removed >= 1
        assert cache.get_robots("https://example.com", ttl_seconds=10**9) is None

    def test_stats_counts(self, cache: Cache) -> None:
        cache.put_page(make_page("https://example.com/a"))
        cache.put_page(make_page("https://example.com/b"))
        cache.put_robots("https://example.com", "User-agent: *", None)
        stats = cache.stats()
        assert stats["pages"] == 2
        assert stats["robots"] == 1
        assert stats["db_bytes"] > 0

    def test_clear_empties_everything(self, cache: Cache) -> None:
        cache.put_page(make_page("https://example.com/a"))
        cache.put_robots("https://example.com", "User-agent: *", None)
        cache.clear()
        assert cache.stats()["pages"] == 0
        assert cache.stats()["robots"] == 0


class TestRobots:
    def test_roundtrip(self, cache: Cache) -> None:
        cache.put_robots("https://example.com", "User-agent: *\nDisallow: /admin", 2.5)
        got = cache.get_robots("https://example.com", ttl_seconds=3600)
        assert got is not None
        body, delay = got
        assert "Disallow" in body
        assert delay == 2.5

    def test_missing_host(self, cache: Cache) -> None:
        assert cache.get_robots("https://nope.com", ttl_seconds=3600) is None
