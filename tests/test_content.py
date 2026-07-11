from collections.abc import Callable

from tearsheet.content import extract_content


class TestArticleExtraction:
    def test_extracts_body_text_as_markdown(self, fixture_bytes: Callable[[str], bytes]) -> None:
        result = extract_content(fixture_bytes("article.html"), url="https://example.com/essay")
        assert result is not None
        assert "linden trees bloom in the courtyard" in result.markdown
        assert "## Why Extraction Matters" in result.markdown

    def test_drops_boilerplate(self, fixture_bytes: Callable[[str], bytes]) -> None:
        result = extract_content(fixture_bytes("article.html"), url="https://example.com/essay")
        assert result is not None
        assert "Subscribe to our newsletter" not in result.markdown
        assert "save 40%" not in result.markdown

    def test_extracts_title(self, fixture_bytes: Callable[[str], bytes]) -> None:
        result = extract_content(fixture_bytes("article.html"), url="https://example.com/essay")
        assert result is not None
        assert result.title == "The Quiet Art of Web Scraping"

    def test_links_excluded_by_default(self, fixture_bytes: Callable[[str], bytes]) -> None:
        result = extract_content(fixture_bytes("article.html"), url="https://example.com/essay")
        assert result is not None
        assert "https://example.com/related" not in result.markdown
        assert "related essay" in result.markdown

    def test_links_included_on_request(self, fixture_bytes: Callable[[str], bytes]) -> None:
        result = extract_content(
            fixture_bytes("article.html"), url="https://example.com/essay", include_links=True
        )
        assert result is not None
        assert "https://example.com/related" in result.markdown


class TestKnownUpstreamManglingDocumented:
    """Documents trafilatura 2.1.0's markdown-serializer bug with nested emphasis
    (<strong><em>word </em></strong> mid-sentence): the emphasized word is torn out
    and glued to the START of the next paragraph, and the remainder of its sentence
    is wrongly bolded. Found in the wild 2026-07-11 (burr.com CMMC article) during
    the probation audit; reported upstream.

    THESE ASSERTIONS PIN THE BROKEN BEHAVIOR ON PURPOSE: when a trafilatura upgrade
    fixes the serializer, this test FAILS — that's the signal to drop the README
    known-issue entry and this test, not a regression.
    """

    def test_nested_emphasis_displacement_still_present(
        self, fixture_bytes: Callable[[str], bytes]
    ) -> None:
        result = extract_content(
            fixture_bytes("emphasis_mangle.html"), url="https://example.com/repro"
        )
        assert result is not None
        # "verify" is displaced onto the start of the NEXT paragraph
        assert "*verify*Starting November 10" in result.markdown
        # and its original sentence is left broken mid-phrase
        assert "plan to \n" in result.markdown or "plan to\n" in result.markdown


class TestDegenerateInput:
    def test_spa_shell_yields_none_or_tiny(self, fixture_bytes: Callable[[str], bytes]) -> None:
        result = extract_content(fixture_bytes("spa_shell.html"), url="https://example.com/app")
        assert result is None or len(result.markdown) < 250

    def test_empty_bytes_yield_none(self) -> None:
        assert extract_content(b"", url="https://example.com/x") is None

    def test_non_html_garbage_yields_none(self) -> None:
        assert extract_content(b"\x00\x01\x02binary", url="https://example.com/x") is None
