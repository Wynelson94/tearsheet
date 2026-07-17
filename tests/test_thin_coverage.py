"""Coverage for the previously-thin surfaces: looks_blocked units, cli routing for
map/crawl/extract/cache, mapper error branches, crawl throttling, structured render."""

import asyncio
import time
from pathlib import Path

import httpx
import pytest
from lxml import etree

from tearsheet.cli import main
from tearsheet.fetch import looks_blocked
from tearsheet.mapper import extract_links, host_allowed


@pytest.fixture(autouse=True)
def _home(isolated_home: Path) -> Path:
    return isolated_home


class TestLooksBlocked:
    def test_small_wall_with_marker_flags(self) -> None:
        assert looks_blocked(b"<html>Please complete the CAPTCHA to continue</html>")

    def test_marker_is_case_insensitive(self) -> None:
        assert looks_blocked(b"<html>VERIFY YOU ARE A HUMAN</html>")

    def test_oversized_body_is_skipped_by_design(self) -> None:
        """The raw-body guard's documented blind spot — backstopped post-extraction
        by content.assess_extraction (block_wall) since the trust-suite fixes."""
        big = b"<html>complete the captcha" + b"x" * 31_000 + b"</html>"
        assert not looks_blocked(big)

    def test_empty_and_none_bodies_do_not_flag(self) -> None:
        assert not looks_blocked(b"")
        assert not looks_blocked(None)

    def test_plain_article_does_not_flag(self) -> None:
        assert not looks_blocked(b"<html><p>An essay about gardening.</p></html>")


class TestMainRouting:
    """The map/crawl/extract/cache routes were untested — the 'search gap' class."""

    def test_main_routes_map(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        async def fake_map(url: str, **kw: object) -> str:
            return f"MAPPED {url} max={kw['max_urls']} sitemap={kw['use_sitemap']}"

        monkeypatch.setattr("tearsheet.cli.map_site", fake_map)
        main(["map", "https://example.com", "--max-urls", "9", "--no-sitemap"])
        out = capsys.readouterr().out
        assert "MAPPED https://example.com max=9 sitemap=False" in out

    def test_main_routes_crawl(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        async def fake_crawl(url: str, **kw: object) -> str:
            return f"CRAWLED {url} pages={kw['max_pages']} include={kw['include_patterns']}"

        monkeypatch.setattr("tearsheet.cli.crawl", fake_crawl)
        main(["crawl", "https://example.com", "--max-pages", "3", "--include", "/docs/*"])
        out = capsys.readouterr().out
        assert "CRAWLED https://example.com pages=3 include=['/docs/*']" in out

    def test_main_routes_extract(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        async def fake_extract(url: str, **kw: object) -> str:
            return f"EXTRACTED {url} types={kw['types']} rows={kw['max_rows']}"

        monkeypatch.setattr("tearsheet.cli.extract_page", fake_extract)
        main(["extract", "https://example.com", "--types", "tables", "--max-rows", "5"])
        out = capsys.readouterr().out
        assert "EXTRACTED https://example.com types=['tables'] rows=5" in out

    def test_cache_stats_prune_clear_roundtrip(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import tearsheet.cache as cache_mod
        from tearsheet.config import get_settings

        cache = cache_mod.Cache(get_settings().cache_db)
        cache.put_page(
            cache_mod.CachedPage(
                url="https://example.com/x",
                final_url="https://example.com/x",
                fetched_at=int(time.time()) - 90 * 86_400,  # ancient
                status=200,
                content_type="text/html",
                via="httpx",
                html=b"<html><p>old</p></html>",
                markdown="old",
                title=None,
            )
        )
        cache.close()

        main(["cache", "stats"])
        assert "pages: 1" in capsys.readouterr().out

        main(["cache", "prune", "--days", "30"])
        assert "pruned 1" in capsys.readouterr().out.lower()

        main(["cache", "stats"])
        assert "pages: 0" in capsys.readouterr().out

        main(["cache", "clear"])
        out = capsys.readouterr().out.lower()
        assert "cleared" in out or "0" in out


class TestMapperEdges:
    def test_unparseable_html_returns_no_links(self) -> None:
        assert extract_links(b"", "https://example.com") == []

    def test_garbage_sitemap_xml_is_skipped(self) -> None:
        from tearsheet.mapper import _sitemap_locs

        locs, is_index = _sitemap_locs(b"this is not xml at all <<<")
        assert locs == [] and is_index is False

    def test_sitemap_with_default_namespace_still_parses(self) -> None:
        from tearsheet.mapper import _sitemap_locs

        body = (
            b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            b"<url><loc>https://example.com/a</loc></url></urlset>"
        )
        locs, is_index = _sitemap_locs(body)
        assert locs == ["https://example.com/a"] and is_index is False

    def test_three_label_host_subdomain_math(self) -> None:
        assert host_allowed("https://docs.api.example.com/x", "api.example.com", True)
        assert not host_allowed("https://docs.api.example.com/x", "api.example.com", False)
        # Sharp edge, pinned on purpose: without include_subdomains only the EXACT
        # host passes — www.example.com is excluded for a root of example.com. A
        # crawl of a bare domain whose links all point at www. needs --subdomains.
        assert not host_allowed("https://www.example.com/x", "example.com", False)
        assert host_allowed("https://www.example.com/x", "example.com", True)

    def test_xml_entity_bomb_is_not_expanded(self) -> None:
        """A billion-laughs-style sitemap must not hang or explode memory —
        lxml's default resolves no entities in etree.fromstring without a parser
        that enables them; pin that safety here."""
        bomb = (
            b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
            b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
            b"<urlset><url><loc>https://example.com/&lol2;</loc></url></urlset>"
        )
        from tearsheet.mapper import _sitemap_locs

        try:
            locs, _ = _sitemap_locs(bomb)
            joined = "".join(locs)
            assert len(joined) < 10_000
        except etree.XMLSyntaxError:
            pass  # refusing to parse is also safe


class TestCrawlThrottle:
    async def test_per_domain_delay_is_actually_waited(self, tmp_path: Path) -> None:
        from dataclasses import replace

        from tearsheet.config import get_settings
        from tearsheet.crawl import crawl

        pages = {
            "/": b'<html><body><main><p>root page prose here</p><a href="/a">a</a><a href="/b">b</a></main></body></html>',
            "/a": b"<html><body><main><p>page a prose content</p></main></body></html>",
            "/b": b"<html><body><main><p>page b prose content</p></main></body></html>",
            "/robots.txt": b"User-agent: *\nAllow: /",
        }

        def handler(request: httpx.Request) -> httpx.Response:
            body = pages.get(request.url.path, b"<html><body>404</body></html>")
            ct = "text/plain" if request.url.path == "/robots.txt" else "text/html"
            return httpx.Response(200, content=body, headers={"content-type": ct})

        settings = replace(get_settings(), per_domain_delay_seconds=0.15)
        started = time.monotonic()
        out = await crawl(
            "https://example.com/",
            max_pages=3,
            max_depth=1,
            settings=settings,
            transport=httpx.MockTransport(handler),
        )
        elapsed = time.monotonic() - started
        assert "3" in out or "pages" in out
        # 3 same-domain fetches with a 0.15s courtesy gap: at least ~2 gaps must elapse
        assert elapsed >= 0.25, f"throttle not honored: {elapsed:.3f}s for 3 pages"


class TestStructuredRenderPath:
    async def test_render_always_uses_the_renderer(
        self, monkeypatch: pytest.MonkeyPatch, fixture_bytes: object
    ) -> None:
        from tearsheet.fetch import FetchResult
        from tearsheet.structured import extract_page

        html = Path("tests/fixtures/jsonld.html").read_bytes()

        async def fake_render(url: str, **kw: object) -> FetchResult:
            return FetchResult(
                url=url, final_url=url, status=200,
                content_type="text/html", body=html, via="playwright",
            )

        monkeypatch.setattr("tearsheet.structured.render_page", fake_render)

        def handler(request: httpx.Request) -> httpx.Response:  # must not be used
            raise AssertionError("render=always must not fall back to httpx")

        out = await extract_page(
            "https://example.com/product", render="always",
            transport=httpx.MockTransport(handler),
        )
        assert "json-ld" in out.lower() or "product" in out.lower()


class TestEventLoopHygiene:
    async def test_two_scrapes_can_run_concurrently(self, fixture_bytes: object) -> None:
        """Heavy usage means parallel calls sharing one cache file — they must not
        corrupt state or deadlock."""
        from tearsheet.scrape import scrape

        html = Path("tests/fixtures/article.html").read_bytes()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=html, headers={"content-type": "text/html"})

        outs = await asyncio.gather(
            *(
                scrape(
                    f"https://example.com/p{i}", render="never",
                    transport=httpx.MockTransport(handler),
                )
                for i in range(8)
            )
        )
        assert all("linden trees bloom" in o for o in outs)
