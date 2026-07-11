import pytest
from fastmcp import Client

from tearsheet import server


def text_of(result: object) -> str:
    content = result.content  # type: ignore[attr-defined]
    return str(content[0].text)


class TestToolRegistry:
    async def test_scrape_and_search_registered_with_guidance(self) -> None:
        async with Client(server.mcp) as client:
            tools = {t.name: t for t in await client.list_tools()}
        assert "scrape" in tools
        assert "search" in tools
        # docstrings are Claude-facing: must carry the token-economy workflow hint
        assert "markdown" in (tools["scrape"].description or "").lower()


class TestToolRegistryM3:
    async def test_map_and_crawl_registered(self) -> None:
        async with Client(server.mcp) as client:
            tools = {t.name for t in await client.list_tools()}
        assert {"scrape", "search", "map", "crawl"} <= tools


class TestMapTool:
    async def test_routes_to_mapper(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_map(url: str, **kw: object) -> str:
            return f"MAP {url} max={kw['max_urls']} search={kw['search']}"

        monkeypatch.setattr("tearsheet.server.map_site", fake_map)
        async with Client(server.mcp) as client:
            result = await client.call_tool(
                "map", {"url": "https://example.com", "max_urls": 50, "search": "auth"}
            )
        assert "MAP https://example.com max=50 search=auth" in text_of(result)


class TestCrawlTool:
    async def test_routes_to_crawler(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_crawl(url: str, **kw: object) -> str:
            return f"CRAWL {url} pages={kw['max_pages']} depth={kw['max_depth']} inc={kw['include_patterns']}"

        monkeypatch.setattr("tearsheet.server.crawl_site", fake_crawl)
        async with Client(server.mcp) as client:
            result = await client.call_tool(
                "crawl",
                {
                    "url": "https://example.com/docs",
                    "max_pages": 10,
                    "max_depth": 1,
                    "include_patterns": ["/docs/*"],
                },
            )
        out = text_of(result)
        assert "CRAWL https://example.com/docs pages=10 depth=1" in out
        assert "inc=['/docs/*']" in out


class TestScrapeTool:
    async def test_routes_to_scrape_core(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_scrape(url: str, **kw: object) -> str:
            return f"MD for {url} max_length={kw['max_length']} fresh={kw['fresh']}"

        monkeypatch.setattr("tearsheet.server.scrape_page", fake_scrape)
        async with Client(server.mcp) as client:
            result = await client.call_tool(
                "scrape", {"url": "https://example.com/a", "max_length": 500, "fresh": True}
            )
        out = text_of(result)
        assert "MD for https://example.com/a" in out
        assert "max_length=500" in out
        assert "fresh=True" in out


class TestSearchTool:
    async def test_routes_to_search_core(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_search(query: str, **kw: object) -> str:
            return f"RESULTS {query} n={kw['max_results']}"

        monkeypatch.setattr("tearsheet.server.search_web", fake_search)
        async with Client(server.mcp) as client:
            result = await client.call_tool("search", {"query": "rust crawlers", "max_results": 3})
        out = text_of(result)
        assert "RESULTS rust crawlers n=3" in out
