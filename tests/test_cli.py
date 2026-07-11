import pytest

from tearsheet.cli import build_parser, main


class TestParser:
    def test_scrape_defaults(self) -> None:
        args = build_parser().parse_args(["scrape", "https://example.com/a"])
        assert args.command == "scrape"
        assert args.url == "https://example.com/a"
        assert args.max_length == 8000
        assert args.links is False
        assert args.fresh is False
        assert args.render == "auto"

    def test_map_defaults(self) -> None:
        args = build_parser().parse_args(["map", "https://example.com"])
        assert args.command == "map"
        assert args.max_urls == 200
        assert args.search is None

    def test_crawl_flags(self) -> None:
        args = build_parser().parse_args(
            [
                "crawl",
                "https://example.com/docs",
                "--max-pages", "10",
                "--max-depth", "1",
                "--include", "/docs/*",
                "--exclude", "/docs/legacy/*",
                "--output-dir", "/tmp/x",
            ]
        )
        assert args.command == "crawl"
        assert args.max_pages == 10
        assert args.max_depth == 1
        assert args.include == ["/docs/*"]
        assert args.exclude == ["/docs/legacy/*"]
        assert args.output_dir == "/tmp/x"

    def test_extract_defaults(self) -> None:
        args = build_parser().parse_args(["extract", "https://example.com/p"])
        assert args.command == "extract"
        assert args.types is None
        assert args.max_rows == 100

    def test_extract_types(self) -> None:
        args = build_parser().parse_args(
            ["extract", "https://example.com/p", "--types", "tables", "--types", "json-ld"]
        )
        assert args.types == ["tables", "json-ld"]

    def test_cache_subcommands(self) -> None:
        assert build_parser().parse_args(["cache", "stats"]).cache_command == "stats"
        args = build_parser().parse_args(["cache", "prune", "--days", "10"])
        assert args.cache_command == "prune"
        assert args.days == 10
        assert build_parser().parse_args(["cache", "clear"]).cache_command == "clear"

    def test_scrape_flags(self) -> None:
        args = build_parser().parse_args(
            ["scrape", "https://example.com/a", "--max-length", "0", "--links", "--fresh"]
        )
        assert args.max_length == 0
        assert args.links is True
        assert args.fresh is True


class TestMain:
    def test_main_prints_scrape_output(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        async def fake_scrape(url: str, **kw: object) -> str:
            return f"scraped {url} kw={kw['max_length']}"

        monkeypatch.setattr("tearsheet.cli.scrape", fake_scrape)
        main(["scrape", "https://example.com/a", "--max-length", "123"])
        out = capsys.readouterr().out
        assert "scraped https://example.com/a" in out
        assert "kw=123" in out
