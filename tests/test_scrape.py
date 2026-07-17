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


CONSENT_BANNER = (
    "Opt-out Preferences We use cookies to analyze site traffic and measure our marketing "
    "efforts. This helps us improve our website and services. However, you can opt out of "
    'these cookies by checking "Do Not Sell or Share My Personal Information" and clicking '
    'the "Save My Preferences" button. Once you opt out, you can opt in again at any time.'
)
# Reproduces smith.ai/pricing/receptionists (2026-07-14): huge markup, the only real text
# is a cookie banner, and the pricing table never renders. trafilatura happily returns the
# banner, which was then served as page content.
CONSENT_PAGE = (
    "<html><head><title>Plans &amp; Pricing</title></head><body>"
    f"<div id='consent'><p>{CONSENT_BANNER}</p></div>"
    f"{'<div class=grid data-x=1></div>' * 2000}</body></html>"
).encode()

# Prices live in chrome that trafilatura strips as boilerplate; the article keeps none of
# them. This is the quo.com/pricing shape: figures on the page, absent from the extraction.
PRICED_PAGE = (
    "<html><body><nav>Starter $15 Business $23 Scale $47 Enterprise $99 Setup $19.50</nav>"
    "<article><h1>Why we changed our plans</h1><p>"
    + ("A long essay about packaging philosophy and nothing else. " * 40)
    + "</p></article></body></html>"
).encode()


def _serving(content: bytes) -> httpx.MockTransport:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, content=content, headers={"content-type": "text/html"})

    transport = httpx.MockTransport(handler)
    transport.calls = calls  # type: ignore[attr-defined]
    return transport


class TestConsentWall:
    async def test_banner_is_reported_not_served_as_content(self) -> None:
        out = await scrape(
            "https://example.com/pricing", render="never", transport=_serving(CONSENT_PAGE)
        )
        assert "consent/cookie wall" in out
        assert "We use cookies" not in out  # the banner must never be passed off as the page

    async def test_consent_wall_is_not_cached(self) -> None:
        transport = _serving(CONSENT_PAGE)
        await scrape("https://example.com/pricing", render="never", transport=transport)
        await scrape("https://example.com/pricing", render="never", transport=transport)
        # a poisoned row would let the second call "succeed" from cache
        assert transport.calls["count"] == 2  # type: ignore[attr-defined]


class TestDroppedPriceWarning:
    async def test_warns_when_prices_do_not_survive(self) -> None:
        out = await scrape(
            "https://example.com/plans", render="never", transport=_serving(PRICED_PAGE)
        )
        warning = next((ln for ln in out.splitlines() if ln.startswith("warning:")), None)
        assert warning is not None
        assert "prices" in warning
        assert "raw=true" in warning
        assert "packaging philosophy" in out  # content still returned, just flagged

    async def test_warning_survives_a_cache_hit(self) -> None:
        transport = _serving(PRICED_PAGE)
        await scrape("https://example.com/plans", render="never", transport=transport)
        out = await scrape("https://example.com/plans", render="never", transport=transport)
        assert "cache" in out
        assert any(ln.startswith("warning:") for ln in out.splitlines())


class TestRawEscapeHatch:
    async def test_raw_recovers_text_the_extractor_drops(self) -> None:
        out = await scrape(
            "https://example.com/plans", render="never", raw=True, transport=_serving(PRICED_PAGE)
        )
        assert "| raw" in out
        for price in ("$15", "$23", "$47", "$99"):
            assert price in out

    async def test_normal_scrape_drops_those_same_prices(self) -> None:
        """Guards the premise: raw is only worth having because extraction loses these."""
        out = await scrape(
            "https://example.com/plans", render="never", transport=_serving(PRICED_PAGE)
        )
        body = out.split("\n---\n", 1)[1]
        assert "$47" not in body

    async def test_raw_reads_from_cache_without_refetching(self) -> None:
        transport = _serving(PRICED_PAGE)
        await scrape("https://example.com/plans", render="never", transport=transport)
        out = await scrape(
            "https://example.com/plans", render="never", raw=True, transport=transport
        )
        assert transport.calls["count"] == 1  # type: ignore[attr-defined]
        assert "| raw" in out
        assert "$47" in out


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

    async def test_pdf_extracted_via_pypdf(self, pdf_bytes: bytes) -> None:
        calls = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["count"] += 1
            return httpx.Response(
                200, content=pdf_bytes, headers={"content-type": "application/pdf"}
            )

        out = await scrape("https://example.com/paper.pdf", transport=httpx.MockTransport(handler))
        assert "via: pypdf" in out
        assert "Tearsheet PDF extraction works" in out

        out2 = await scrape(
            "https://example.com/paper.pdf", transport=httpx.MockTransport(handler)
        )
        assert calls["count"] == 1
        assert "cache" in out2
        assert "Tearsheet PDF extraction works" in out2

    async def test_corrupt_pdf_reports_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=b"%PDF-not really", headers={"content-type": "application/pdf"}
            )

        out = await scrape("https://example.com/bad.pdf", transport=httpx.MockTransport(handler))
        assert "could not extract text from pdf" in out.lower()

    async def test_botwall_page_reported_blocked_and_never_cached(
        self, fixture_bytes: Callable[[str], bytes]
    ) -> None:
        calls = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["count"] += 1
            # 200-status CAPTCHA wall after a cross-domain redirect, like eCFR's
            if request.url.host == "www.ecfr.example":
                return httpx.Response(
                    302, headers={"location": "https://unblock.example/challenge"}
                )
            return httpx.Response(
                200, content=fixture_bytes("botwall.html"), headers={"content-type": "text/html"}
            )

        transport = httpx.MockTransport(handler)
        out = await scrape("https://www.ecfr.example/title-48", render="never", transport=transport)
        assert "blocked by bot protection" in out
        assert "unblock.example" in out  # final url visible so the wall is obvious
        # nothing cached: a second scrape must hit the network again
        first_fetches = calls["count"]
        out2 = await scrape(
            "https://www.ecfr.example/title-48", render="never", transport=transport
        )
        assert calls["count"] > first_fetches
        assert "blocked by bot protection" in out2

    async def test_article_mentioning_captchas_is_not_flagged(
        self, fixture_bytes: Callable[[str], bytes]
    ) -> None:
        # a large real article ABOUT captchas (e.g. Wikipedia) must not read as a wall
        article = fixture_bytes("article.html").replace(
            b"<h1>The Quiet Art of Web Scraping</h1>",
            b"<h1>The Quiet Art of Web Scraping</h1>"
            b"<p>Sites often ask visitors to complete the CAPTCHA to verify you are a human"
            b" before scraping; this article discusses those countermeasures.</p>",
        ) + b"<!-- " + b"filler " * 6000 + b"-->"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=article, headers={"content-type": "text/html"})

        out = await scrape(
            "https://example.com/captcha-essay", render="never",
            transport=httpx.MockTransport(handler),
        )
        assert "blocked by bot protection" not in out
        assert "linden trees bloom" in out

    async def test_cross_domain_redirect_without_markers_is_not_flagged(
        self, fixture_bytes: Callable[[str], bytes]
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "short.example":
                return httpx.Response(
                    301, headers={"location": "https://real.example/essay"}
                )
            return httpx.Response(
                200, content=fixture_bytes("article.html"), headers={"content-type": "text/html"}
            )

        out = await scrape(
            "https://short.example/x", render="never", transport=httpx.MockTransport(handler)
        )
        assert "blocked" not in out
        assert "linden trees bloom" in out

    async def test_json_pretty_printed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=b'{"b":1,"a":[1,2]}', headers={"content-type": "application/json"}
            )

        out = await scrape("https://example.com/api", transport=httpx.MockTransport(handler))
        assert '"a"' in out
        assert "\n" in out.split("---", 1)[1]


WALL_MAIN = (
    b"<main><h1>Attention Required!</h1><p>Please verify you are a human to continue. "
    b"Complete the CAPTCHA below to access this page.</p></main>"
)


def oversized_wall_html() -> bytes:
    """A challenge page padded past fetch._BLOCK_MAX_BODY (30 KB): the raw-body
    heuristic must skip it, so only a post-extraction backstop can catch it."""
    pad = b"<div class='challenge-asset' data-x='y'></div>" * 800  # ~36 KB of inert markup
    return b"<html><body>" + pad + WALL_MAIN + b"</body></html>"


class TestOversizedBotwall:
    """The >30KB block-cache hole (trust-suite review, 2026-07-16)."""

    async def test_oversized_wall_reported_not_served(self) -> None:
        html = oversized_wall_html()
        assert len(html) > 30_000  # must actually clear the raw-body guard

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=html, headers={"content-type": "text/html"})

        out = await scrape(
            "https://walled.example/page", render="never", transport=httpx.MockTransport(handler)
        )
        assert "blocked by bot protection" in out
        assert "Complete the CAPTCHA" not in out  # the wall text must not be served as content

    async def test_oversized_wall_never_cached(self) -> None:
        html = oversized_wall_html()
        calls = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["count"] += 1
            return httpx.Response(200, content=html, headers={"content-type": "text/html"})

        transport = httpx.MockTransport(handler)
        await scrape("https://walled.example/page", render="never", transport=transport)
        await scrape("https://walled.example/page", render="never", transport=transport)
        assert calls["count"] == 2  # a wall must never be served from cache

    async def test_preseeded_wall_row_not_served_from_cache(
        self, fixture_bytes: Callable[[str], bytes]
    ) -> None:
        """Rows poisoned by pre-fix versions must not be replayed on cache read."""
        import time

        from tearsheet.cache import Cache, CachedPage
        from tearsheet.config import get_settings

        settings = get_settings()
        cache = Cache(settings.cache_db)
        cache.put_page(
            CachedPage(
                url="https://walled.example/old",
                final_url="https://walled.example/old",
                fetched_at=int(time.time()),
                status=200,
                content_type="text/html",
                via="httpx",
                html=oversized_wall_html(),
                markdown="Attention Required! Complete the CAPTCHA.",
                title=None,
            )
        )
        cache.close()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=fixture_bytes("article.html"), headers={"content-type": "text/html"}
            )

        out = await scrape(
            "https://walled.example/old", render="never", transport=httpx.MockTransport(handler)
        )
        assert "linden trees bloom" in out  # fell through to the live fetch
        assert "CAPTCHA" not in out


class TestPoisonedRenderLockIn:
    """put_page's playwright-beats-httpx rule must not lock in a poisoned render
    (the smith.ai lesson inverted): after a poisoned cached row forces a live
    re-fetch, the good replacement must actually be stored."""

    CONSENT_HTML = (
        b"<html><body><main><p>Opt-out Preferences We use cookies to analyze site "
        b"traffic and measure our marketing efforts. However, you can opt out of these "
        b'cookies by checking "Do Not Sell or Share My Personal Information" and '
        b'clicking the "Save My Preferences" button.</p></main></body></html>'
    )

    async def test_good_httpx_content_replaces_poisoned_playwright_row(
        self, fixture_bytes: Callable[[str], bytes]
    ) -> None:
        import time

        from tearsheet.cache import Cache, CachedPage
        from tearsheet.config import get_settings

        settings = get_settings()
        cache = Cache(settings.cache_db)
        cache.put_page(
            CachedPage(
                url="https://locked.example/pricing",
                final_url="https://locked.example/pricing",
                fetched_at=int(time.time()),
                status=200,
                content_type="text/html",
                via="playwright",
                html=self.CONSENT_HTML,
                markdown="We use cookies to analyze site traffic.",
                title=None,
            )
        )
        cache.close()
        calls = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["count"] += 1
            return httpx.Response(
                200, content=fixture_bytes("article.html"), headers={"content-type": "text/html"}
            )

        transport = httpx.MockTransport(handler)
        out = await scrape("https://locked.example/pricing", render="never", transport=transport)
        assert "linden trees bloom" in out  # poison not served

        # The replacement must have been STORED: a second scrape is a cache hit.
        out2 = await scrape("https://locked.example/pricing", render="never", transport=transport)
        assert calls["count"] == 1
        assert "cache" in out2
        assert "linden trees bloom" in out2
