import pytest

from tearsheet.search import format_results, search


class FakeDDGS:
    results: list[dict[str, str]] = []
    raise_error: Exception | None = None
    seen: dict[str, object] = {}

    def text(self, query: str, **kwargs: object) -> list[dict[str, str]]:
        FakeDDGS.seen = {"query": query, **kwargs}
        if FakeDDGS.raise_error is not None:
            raise FakeDDGS.raise_error
        return FakeDDGS.results


@pytest.fixture(autouse=True)
def fake_ddgs(monkeypatch: pytest.MonkeyPatch) -> type[FakeDDGS]:
    FakeDDGS.results = []
    FakeDDGS.raise_error = None
    FakeDDGS.seen = {}
    monkeypatch.setattr("tearsheet.search.DDGS", FakeDDGS)
    return FakeDDGS


class TestFormatResults:
    def test_numbered_compact_lines(self) -> None:
        out = format_results(
            [
                {"title": "First Hit", "href": "https://a.com/x", "body": "Alpha snippet."},
                {"title": "Second Hit", "href": "https://b.com/y", "body": "Beta snippet."},
            ]
        )
        lines = out.splitlines()
        assert lines[0] == "1. First Hit — https://a.com/x"
        assert lines[1] == "   Alpha snippet."
        assert lines[2] == "2. Second Hit — https://b.com/y"

    def test_snippet_truncated_to_200_chars(self) -> None:
        out = format_results([{"title": "T", "href": "https://a.com", "body": "z" * 500}])
        snippet_line = out.splitlines()[1]
        assert len(snippet_line.strip()) <= 201  # 200 + ellipsis char

    def test_handles_url_key_variant(self) -> None:
        out = format_results([{"title": "T", "url": "https://c.com/z", "body": "s"}])
        assert "https://c.com/z" in out


class TestSearch:
    async def test_passes_query_and_limits(self, fake_ddgs: type[FakeDDGS]) -> None:
        fake_ddgs.results = [{"title": "T", "href": "https://a.com", "body": "s"}]
        out = await search("local llm scraping", max_results=3)
        assert fake_ddgs.seen["query"] == "local llm scraping"
        assert fake_ddgs.seen["max_results"] == 3
        assert "1. T — https://a.com" in out

    async def test_no_results_message(self) -> None:
        out = await search("gibberish qzxv")
        assert "no results" in out.lower()

    async def test_backend_error_becomes_readable_message(self, fake_ddgs: type[FakeDDGS]) -> None:
        fake_ddgs.raise_error = RuntimeError("backend 502")
        out = await search("anything")
        assert "search failed" in out.lower()
        assert "backend 502" in out
