from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from tearsheet.scrape import scrape


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "tearsheet-home"
    monkeypatch.setenv("TEARSHEET_HOME", str(home))
    return home


@pytest.fixture
def article_transport(fixture_bytes: Callable[[str], bytes]) -> httpx.MockTransport:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            200, content=fixture_bytes("article.html"), headers={"content-type": "text/html"}
        )

    transport = httpx.MockTransport(handler)
    transport.calls = calls  # type: ignore[attr-defined]
    return transport


class TestScrapeHappyPath:
    async def test_returns_header_and_markdown(self, article_transport: httpx.MockTransport) -> None:
        out = await scrape("https://example.com/essay", transport=article_transport)
        assert out.startswith("url: https://example.com/essay")
        assert "title: The Quiet Art of Web Scraping" in out
        assert "live | via: httpx" in out
        assert "\n---\n" in out
        assert "linden trees bloom" in out

    async def test_reports_token_counts(self, article_transport: httpx.MockTransport) -> None:
        out = await scrape("https://example.com/essay", transport=article_transport)
        assert "tokens: ~" in out


class TestScrapeCache:
    async def test_second_call_hits_cache(self, article_transport: httpx.MockTransport) -> None:
        await scrape("https://example.com/essay", transport=article_transport)
        out = await scrape("https://example.com/essay", transport=article_transport)
        assert article_transport.calls["count"] == 1  # type: ignore[attr-defined]
        assert "cache" in out

    async def test_fresh_bypasses_cache(self, article_transport: httpx.MockTransport) -> None:
        await scrape("https://example.com/essay", transport=article_transport)
        out = await scrape("https://example.com/essay", fresh=True, transport=article_transport)
        assert article_transport.calls["count"] == 2  # type: ignore[attr-defined]
        assert "live" in out


class TestScrapeTruncation:
    async def test_truncates_and_points_at_full_copy(
        self, article_transport: httpx.MockTransport, isolated_home: Path
    ) -> None:
        out = await scrape("https://example.com/essay", max_length=300, transport=article_transport)
        assert "truncated" in out
        assert "full copy:" in out
        # the referenced file exists and holds the complete markdown
        path_line = next(line for line in out.splitlines() if "full copy:" in line)
        full_path = Path(path_line.rsplit("full copy:", 1)[1].strip().rstrip(")"))
        assert full_path.exists()
        assert "old, boring, and almost always correct" in full_path.read_text()

    async def test_unlimited_when_zero(self, article_transport: httpx.MockTransport) -> None:
        out = await scrape("https://example.com/essay", max_length=0, transport=article_transport)
        assert "truncated" not in out
        assert "old, boring, and almost always correct" in out


class TestScrapeErrors:
    async def test_http_error_status_reported(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="nope")

        out = await scrape("https://example.com/gone", transport=httpx.MockTransport(handler))
        assert "404" in out

    async def test_unextractable_page_reports_hint(
        self, fixture_bytes: Callable[[str], bytes]
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=fixture_bytes("spa_shell.html"), headers={"content-type": "text/html"}
            )

        # render="never": with auto, the shell would (correctly) go to the real renderer
        out = await scrape(
            "https://example.com/app", render="never", transport=httpx.MockTransport(handler)
        )
        assert "no extractable content" in out.lower()

    async def test_json_pretty_printed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=b'{"b":1,"a":[1,2]}', headers={"content-type": "application/json"}
            )

        out = await scrape("https://example.com/api", transport=httpx.MockTransport(handler))
        assert '"a"' in out
        assert "\n" in out.split("---", 1)[1]
