from tearsheet.urls import normalize_url, url_hash


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
