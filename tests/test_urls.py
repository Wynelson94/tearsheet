from tearsheet.urls import is_crawlable_url, normalize_url, url_hash


class TestIsCrawlableUrl:
    def test_plain_page_is_crawlable(self) -> None:
        assert is_crawlable_url("https://example.com/docs/getting-started") is True

    def test_too_many_query_params_rejected(self) -> None:
        assert is_crawlable_url("https://example.com/search?a=1&b=2&c=3&d=4") is False

    def test_three_params_still_allowed(self) -> None:
        assert is_crawlable_url("https://example.com/search?a=1&b=2&c=3") is True

    def test_repeating_path_segments_rejected(self) -> None:
        assert is_crawlable_url("https://example.com/a/b/a/b/a/b") is False

    def test_non_content_extensions_rejected(self) -> None:
        for ext in ("jpg", "png", "css", "js", "zip", "mp4", "woff2", "svg", "ico"):
            assert is_crawlable_url(f"https://example.com/asset.{ext}") is False, ext

    def test_html_and_extensionless_allowed(self) -> None:
        assert is_crawlable_url("https://example.com/page.html") is True
        assert is_crawlable_url("https://example.com/page") is True

    def test_non_http_schemes_rejected(self) -> None:
        assert is_crawlable_url("mailto:a@b.com") is False
        assert is_crawlable_url("javascript:void(0)") is False


class TestNormalizeUrl:
    def test_lowercases_host_keeps_path_case(self) -> None:
        assert normalize_url("https://Example.COM/Some/Path") == "https://example.com/Some/Path"

    def test_strips_fragment(self) -> None:
        assert normalize_url("https://example.com/page#section-2") == "https://example.com/page"

    def test_strips_tracking_params(self) -> None:
        url = "https://example.com/a?utm_source=x&utm_medium=y&fbclid=123&gclid=9&ref=hn&id=7"
        assert normalize_url(url) == "https://example.com/a?id=7"

    def test_sorts_query_params(self) -> None:
        assert normalize_url("https://example.com/a?b=2&a=1") == "https://example.com/a?a=1&b=2"

    def test_collapses_trailing_slash(self) -> None:
        assert normalize_url("https://example.com/docs/") == "https://example.com/docs"

    def test_root_path_kept_canonical(self) -> None:
        assert normalize_url("https://example.com") == normalize_url("https://example.com/")


class TestUrlHash:
    def test_stable_and_hex32(self) -> None:
        h = url_hash("https://example.com/a")
        assert h == url_hash("https://example.com/a")
        assert len(h) == 32
        int(h, 16)  # raises if not hex

    def test_normalized_variants_share_hash(self) -> None:
        assert url_hash("https://Example.com/a?b=2&a=1#x") == url_hash("https://example.com/a?a=1&b=2")
