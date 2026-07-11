import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from tearsheet.scrape import scrape
from tearsheet.structured import extract_page, extract_structured


class TestExtractPage:
    @pytest.fixture(autouse=True)
    def isolated_home(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("TEARSHEET_HOME", str(tmp_path / "home"))

    async def test_fetches_and_extracts(self, fixture_bytes: Callable[[str], bytes]) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=fixture_bytes("jsonld.html"), headers={"content-type": "text/html"}
            )

        out = json.loads(
            await extract_page(
                "https://store.example.com/widget-pro", transport=httpx.MockTransport(handler)
            )
        )
        assert out["json_ld"][0]["sku"] == "AWP-9000"

    async def test_reuses_html_cached_by_scrape(
        self, fixture_bytes: Callable[[str], bytes]
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=fixture_bytes("jsonld.html"), headers={"content-type": "text/html"}
            )

        await scrape("https://store.example.com/widget-pro", transport=httpx.MockTransport(handler))

        def refuse(request: httpx.Request) -> httpx.Response:
            raise AssertionError("extract must reuse cached HTML, not refetch")

        out = json.loads(
            await extract_page(
                "https://store.example.com/widget-pro", transport=httpx.MockTransport(refuse)
            )
        )
        assert out["opengraph"]["og:title"] == "Acme Widget Pro"

    async def test_fetch_error_reported_as_json(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        out = json.loads(
            await extract_page("https://example.com/x", transport=httpx.MockTransport(handler))
        )
        assert "error" in out
        assert "500" in out["error"]


class TestJsonLd:
    def test_product_schema_extracted(self, fixture_bytes: Callable[[str], bytes]) -> None:
        out = json.loads(
            extract_structured(fixture_bytes("jsonld.html"), "https://store.example.com/widget-pro")
        )
        assert out["url"] == "https://store.example.com/widget-pro"
        product = out["json_ld"][0]
        assert product["@type"] == "Product"
        assert product["sku"] == "AWP-9000"


class TestOpengraph:
    def test_og_tags_extracted(self, fixture_bytes: Callable[[str], bytes]) -> None:
        out = json.loads(
            extract_structured(fixture_bytes("jsonld.html"), "https://store.example.com/widget-pro")
        )
        assert out["opengraph"]["og:title"] == "Acme Widget Pro"


class TestMicrodata:
    def test_itemscope_extracted(self, fixture_bytes: Callable[[str], bytes]) -> None:
        out = json.loads(
            extract_structured(fixture_bytes("jsonld.html"), "https://store.example.com/widget-pro")
        )
        assert any("Acme Corporation" in json.dumps(item) for item in out["microdata"])


class TestTables:
    def test_table_with_headers(self, fixture_bytes: Callable[[str], bytes]) -> None:
        out = json.loads(
            extract_structured(fixture_bytes("tables.html"), "https://example.com/pricing")
        )
        table = out["tables"][0]
        assert table["caption"] == "Plan comparison"
        assert table["headers"] == ["Plan", "Price", "Seats"]
        assert ["Pro", "$29", "5"] in table["rows"]
        assert table["truncated"] is False

    def test_headerless_table(self, fixture_bytes: Callable[[str], bytes]) -> None:
        out = json.loads(
            extract_structured(fixture_bytes("tables.html"), "https://example.com/pricing")
        )
        assert len(out["tables"]) == 2
        assert out["tables"][1]["headers"] == []

    def test_max_rows_truncates(self, fixture_bytes: Callable[[str], bytes]) -> None:
        out = json.loads(
            extract_structured(
                fixture_bytes("tables.html"), "https://example.com/pricing", max_rows=1
            )
        )
        table = out["tables"][0]
        assert len(table["rows"]) == 1
        assert table["truncated"] is True


class TestShape:
    def test_empty_syntaxes_omitted(self, fixture_bytes: Callable[[str], bytes]) -> None:
        # tables.html has no JSON-LD/OG/microdata — those keys must be absent, not empty
        out = json.loads(
            extract_structured(fixture_bytes("tables.html"), "https://example.com/pricing")
        )
        assert "json_ld" not in out
        assert "opengraph" not in out
        assert "microdata" not in out

    def test_types_filter(self, fixture_bytes: Callable[[str], bytes]) -> None:
        out = json.loads(
            extract_structured(
                fixture_bytes("jsonld.html"),
                "https://store.example.com/widget-pro",
                types=["json-ld"],
            )
        )
        assert "json_ld" in out
        assert "opengraph" not in out

    def test_nothing_found_message(self) -> None:
        out = json.loads(extract_structured(b"<html><body><p>plain</p></body></html>", "https://x.com"))
        assert out.get("note") == "no structured data found"
