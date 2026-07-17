"""The original sins, pinned forever.

These fixtures are the REAL bytes of the pages that put tearsheet on probation
(captured 2026-07-12/14 from the live cache) plus the two calibration pages.
Every guard change must keep passing against the actual failures, not synthetic
approximations of them. This is the eval flywheel's first deposit: live failures
get demoted into offline fixtures.

    quo_pricing      — CSS-div grid; kept 4/24 figures, columns collapsed  (warn)
    smithai_pricing  — consent banner served as the page                   (warn/wall)
    dialpad_pricing  — JS-tabbed; figures live in RSC JSON, invisible      (documented)
    heyrosie_pricing — the GOOD pricing page                               (silent)
    linkedin_post    — real figures in peripheral cards; the v0.1.2 FP     (silent)
"""

import gzip
from pathlib import Path

import pytest

from tearsheet.content import assess_extraction, extract_content

PROBATION = Path(__file__).parent / "fixtures" / "probation"


def load(name: str) -> bytes:
    return gzip.decompress((PROBATION / f"{name}.html.gz").read_bytes())


def price_warned(html: bytes) -> tuple[bool, bool, bool]:
    """(price_warning, column_warning, any_wall) for a fixture's real extraction."""
    extracted = extract_content(html)
    assert extracted is not None, "fixture must extract — these are real pages"
    quality = assess_extraction(html, extracted)
    return (
        any("price" in w for w in quality.warnings),
        any("column" in w for w in quality.warnings),
        quality.consent_wall or quality.block_wall,
    )


class TestQuoPricing:
    def test_the_original_failure_still_warns(self) -> None:
        price, column, wall = price_warned(load("quo_pricing"))
        assert price, "quo dropped 20/24 prices — the guard MUST fire"
        assert column, "quo collapsed its 3-column matrix — the guard MUST fire"


class TestSmithAiPricing:
    def test_the_banner_page_is_never_silent(self) -> None:
        price, column, wall = price_warned(load("smithai_pricing"))
        assert price or wall, "smith.ai must warn (dropped prices) or report a wall"


class TestDialpadPricing:
    def test_rsc_hidden_figures_documented(self) -> None:
        """Dialpad's prices live in escaped RSC JSON — invisible to ANY text
        extraction. The guard cannot fire (nothing visible to compare); the
        protection is procedural: pricing scrape under ~1k tokens => use raw
        or another tool. Pinned so a change in visibility gets noticed."""
        html = load("dialpad_pricing")
        extracted = extract_content(html)
        assert extracted is not None
        assert "$15" not in extracted.markdown  # the Connect Standard price stays invisible
        quality = assess_extraction(html, extracted)
        # If this starts failing because a warning NOW fires, the guard got
        # smarter than the page — celebrate and update this pin.
        assert not any("price" in w for w in quality.warnings)


class TestHeyrosiePricing:
    def test_the_good_page_stays_silent(self) -> None:
        price, column, wall = price_warned(load("heyrosie_pricing"))
        assert not price, "heyrosie keeps 100% of its figures — a warning here is a false positive"
        assert not wall


class TestLinkedInPost:
    def test_the_false_positive_stays_dead(self) -> None:
        price, column, wall = price_warned(load("linkedin_post"))
        assert not price, "peripheral real figures must not trip the guard (v0.1.3 fix)"
        assert not wall

    def test_the_post_body_still_extracts(self) -> None:
        extracted = extract_content(load("linkedin_post"))
        assert extracted is not None
        assert "Light Heart Labs" in extracted.markdown


@pytest.mark.parametrize(
    "name",
    ["quo_pricing", "smithai_pricing", "dialpad_pricing", "heyrosie_pricing", "linkedin_post"],
)
def test_no_fixture_extraction_crashes(name: str) -> None:
    extracted = extract_content(load(name))
    quality = assess_extraction(load(name), extracted)
    assert quality is not None
