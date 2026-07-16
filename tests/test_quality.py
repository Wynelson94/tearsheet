"""Extraction-quality guards.

Thresholds here are calibrated against REAL pages captured 2026-07-14
(cached HTML measured directly, see memory/project_tearsheet.md audit log):

    page                            page_$  cluster  retained  consent  collapsed_runs  md_chars
    quo.com/pricing        (BAD)        24       17       17%       no               7      3716
    smith.ai/../receptionists (BAD)     17        7       18%       no               0      1452
    heyrosie.com/pricing   (GOOD)        5        5      100%       no               1     12128
    linkedin.com post      (GOOD)        4        3        0%       no               0     ~3500

The guards must fire on the bad pages and stay SILENT on the good ones.

`cluster` = max distinct price figures within any 1,500-char window of visible
text. It is the arming condition for the dropped-price guard: pricing pages
carry their figures in a grid/table (quo 17, smith 7 clustered), while article
pages scatter real-but-peripheral dollar amounts through prose and related-post
cards (the LinkedIn false positive of 2026-07-14: 4 figures page-wide, never
more than 3 near each other). A page-wide count cannot tell those apart; a
cluster can, with margin on both sides (3 vs 5).

An earlier design used a markdown/visible-text yield ratio; it is kept out on
purpose because it provably fires on neither bad page (smith.ai yields 34%,
quo 21%) while risking false positives on legitimately terse pages.
"""

from tearsheet.content import ExtractedContent, assess_extraction, html_to_text

CONSENT_BANNER = (
    "Opt-out Preferences We use cookies to analyze site traffic and measure our "
    "marketing efforts. This helps us improve our website and services. However, you "
    'can opt out of these cookies by checking "Do Not Sell or Share My Personal '
    'Information" and clicking the "Save My Preferences" button.'
)


def page(body: str, *, pad: int = 0) -> bytes:
    """An HTML page whose visible text is `body`, padded with inert markup."""
    filler = "<div class='x' data-a='y'></div>" * pad
    return f"<html><body>{filler}<main>{body}</main></body></html>".encode()


def extracted(markdown: str) -> ExtractedContent:
    return ExtractedContent(markdown=markdown, title=None, description=None)


class TestHtmlToText:
    def test_strips_scripts_styles_and_tags(self) -> None:
        html = b"<html><script>var a='hidden';</script><style>i{}</style><p>Real &amp; visible</p>"
        text = html_to_text(html)
        assert "Real & visible" in text
        assert "hidden" not in text
        assert "<p>" not in text

    def test_collapses_whitespace(self) -> None:
        assert html_to_text(b"<p>a</p>\n\n\n   <p>b</p>") == "a b"


class TestConsentWall:
    def test_cookie_banner_as_content_is_reported_not_served(self) -> None:
        """The smith.ai failure: a 428-char consent banner served as page content."""
        quality = assess_extraction(page(CONSENT_BANNER, pad=3000), extracted(CONSENT_BANNER))
        assert quality.consent_wall is True

    def test_article_merely_mentioning_cookies_is_not_flagged(self) -> None:
        """Mirrors the captcha true-negative guard: discussing cookies != being a wall."""
        article = (
            "Cookie consent banners are everywhere since GDPR. We use cookies on this "
            "site, and so does nearly every publisher. " + "The history is long. " * 120
        )
        quality = assess_extraction(page(article), extracted(article))
        assert quality.consent_wall is False

    def test_ordinary_page_is_not_a_consent_wall(self) -> None:
        quality = assess_extraction(page("A normal essay about trees."), extracted("A normal essay about trees."))
        assert quality.consent_wall is False


class TestGatedPage:
    def test_large_markup_with_almost_no_visible_text_warns(self) -> None:
        """smith.ai: 96 KB of markup, 1,267 chars of visible text — content never rendered."""
        quality = assess_extraction(page("Plans & Pricing", pad=4000), extracted("Plans & Pricing"))
        assert any("visible text" in w for w in quality.warnings)


class TestMoneyRetention:
    def test_dropped_prices_warn(self) -> None:
        """The quo failure: 24 prices on the page, 4 survived extraction."""
        prices = " ".join(f"${n}" for n in (15, 19, 23, 25, 33, 35, 47, 49, 99, 120, 144, 180))
        body = f"Compare plans. {prices}. Setup fee $19.50 applies."
        quality = assess_extraction(page(body), extracted("Setup fee $19.50 applies."))
        warning = next((w for w in quality.warnings if "price" in w), None)
        assert warning is not None
        assert "12 of 13" in warning  # 13 distinct on page, 1 kept

    def test_page_that_keeps_its_prices_is_silent(self) -> None:
        """The heyrosie regression guard: a good pricing page must not warn."""
        body = "Professional $49/mo. Scale $149/mo. Growth $299/mo. Overage $0.70/call. Setup $1."
        quality = assess_extraction(page(body), extracted(body))
        assert not any("price" in w for w in quality.warnings)

    def test_few_prices_on_page_does_not_warn(self) -> None:
        """A blog with one footer price must not trip the guard."""
        body = "An essay about pricing psychology. Plans from $29/mo in the footer."
        quality = assess_extraction(page(body), extracted("An essay about pricing psychology."))
        assert not any("price" in w for w in quality.warnings)

    def test_scattered_peripheral_prices_do_not_warn(self) -> None:
        """The LinkedIn false positive (2026-07-14): four REAL dollar figures spread
        across related-post cards on an article page. The extraction correctly kept
        only the main post (which has no prices) — the guard must not punish it.
        Page-wide there are >= 4 distinct figures, but never enough near each other
        to look like a pricing region."""
        spacer = "More thoughtful commentary about the industry and its people. " * 30
        body = (
            "The main post announces a merger and contains no dollar figures at all. "
            + "It is a substantial piece of writing. " * 40
            + f"Related: community groups halted $130 billion of projects. {spacer}"
            + f"Related: intelligence crashed from $17 to $2 per million tokens. {spacer}"
            + f"Related: Big Tech's $8 trillion AI bet is reshaping costs. {spacer}"
        )
        main_post = (
            "The main post announces a merger and contains no dollar figures at all. "
            + "It is a substantial piece of writing. " * 40
        )
        quality = assess_extraction(page(body), extracted(main_post))
        assert not any("price" in w for w in quality.warnings)

    def test_clustered_prices_still_arm_the_guard(self) -> None:
        """Do-not-loosen regression: a genuine pricing grid whose figures all sit
        together must still warn when the extraction drops them, even when the
        page-wide total is small (the arming moved to clusters, not away from them)."""
        body = "Plans: Starter $19/mo, Business $33/mo, Scale $47/mo, annual $15/mo. " + (
            "Long marketing prose follows the grid. " * 80
        )
        quality = assess_extraction(page(body), extracted("Long marketing prose follows the grid."))
        assert any("price" in w for w in quality.warnings)


class TestCollapsedColumns:
    def test_repeated_rows_warn(self) -> None:
        """quo: a 3-column matrix flattened to `Unlimited* / Unlimited* / Unlimited*`."""
        markdown = (
            "Calling\n\nUnlimited*\n\nUnlimited*\n\nUnlimited*\n\n"
            "Messaging\n\nUnlimited*\n\nUnlimited*\n\nUnlimited*\n\n"
            "Recording\n\nManual\n\nAutomatic\n\nAutomatic\n"
        )
        quality = assess_extraction(page("Calling Unlimited"), extracted(markdown))
        assert any("column" in w for w in quality.warnings)

    def test_single_repeated_triple_is_tolerated(self) -> None:
        """heyrosie has exactly one such run and is a GOOD page — one run must not warn."""
        markdown = "Included\n\nYes\n\nYes\n\nYes\n\n" + "Real prose about the product. " * 30
        quality = assess_extraction(page("Included"), extracted(markdown))
        assert not any("column" in w for w in quality.warnings)
