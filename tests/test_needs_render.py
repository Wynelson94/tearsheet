from collections.abc import Callable

from tearsheet.fetch import needs_render


class TestNeedsRender:
    def test_spa_root_shell_needs_render(self, fixture_bytes: Callable[[str], bytes]) -> None:
        html = fixture_bytes("spa_shell.html")
        assert needs_render(html, "You need to enable JavaScript to run this app.") is True

    def test_noscript_shell_needs_render(self, fixture_bytes: Callable[[str], bytes]) -> None:
        html = fixture_bytes("noscript_shell.html")
        assert needs_render(html, None) is True

    def test_real_article_does_not(self, fixture_bytes: Callable[[str], bytes]) -> None:
        html = fixture_bytes("article.html")
        long_extraction = "x" * 400
        assert needs_render(html, long_extraction) is False

    def test_long_extraction_wins_even_with_spa_markers(self) -> None:
        html = b'<html><body><div id="root">server-side rendered app</div></body></html>'
        assert needs_render(html, "y" * 400) is False

    def test_short_extraction_without_markers_is_fine(self) -> None:
        # a genuinely tiny static page is not a shell
        html = b"<html><body><p>Short and sweet.</p></body></html>"
        assert needs_render(html, "Short and sweet.") is False

    def test_script_dominated_page_needs_render(self) -> None:
        html = (
            b"<html><body><p>hi</p><script>" + b"window.x=1;" * 500 + b"</script></body></html>"
        )
        assert needs_render(html, "hi") is True
