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
