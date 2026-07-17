"""Adversarial trust suite: truncation honesty, robustness, charset, structure.

Every test here answers one question — does the tool ever fail SILENTLY? A crash
is acceptable to catch; a wrong-but-confident answer is not. Where current behavior
is an accepted limitation, the test PINS it and says so, mirroring the trafilatura
#882 canary pattern: the pin fails loudly the day the behavior changes.
"""

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from tearsheet.content import extract_content, html_to_text
from tearsheet.scrape import scrape


@pytest.fixture(autouse=True)
def _home(isolated_home: Path) -> Path:
    return isolated_home


def transport_for(body: bytes, content_type: str = "text/html") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": content_type})

    return httpx.MockTransport(handler)


class TestTruncationHonesty:
    """Truncation is a silent-omission vector the guards never see: a figure can
    survive extraction and still never reach the model. The defense is honesty —
    the returned string must SAY it truncated and point at the full copy."""

    async def test_figure_beyond_cut_is_flagged_and_recoverable(self, tmp_path: Path) -> None:
        prose = "<p>" + "Long paragraph of filler prose. " * 40 + "</p>"
        html = (
            "<html><body><main><h1>Report</h1>"
            + prose * 10
            + "<p>The final invoice totals $4,321 exactly.</p></main></body></html>"
        ).encode()
        out = await scrape(
            "https://example.com/report",
            max_length=500,
            render="never",
            transport=transport_for(html),
        )
        shown = out.split("---", 1)[1]
        assert "$4,321" not in shown  # the figure fell below the cut...
        assert "truncated" in out  # ...so the output MUST say so
        assert "full copy:" in out
        full_path = out.split("full copy: ", 1)[1].split(")", 1)[0]
        assert "$4,321" in Path(full_path).read_text()  # ...and the full copy has it

    async def test_untruncated_output_carries_no_truncation_claim(self) -> None:
        html = b"<html><body><main><p>Short honest page.</p></main></body></html>"
        out = await scrape(
            "https://example.com/short", render="never", transport=transport_for(html)
        )
        assert "truncated" not in out


class TestRobustness:
    async def test_large_page_just_under_limit_completes(self) -> None:
        filler = b"<p>Real sentence content for the extractor to keep. </p>" * 20_000  # ~1.1 MB
        html = b"<html><body><main>" + filler + b"</main></body></html>"
        out = await scrape(
            "https://example.com/big", max_length=200, render="never",
            transport=transport_for(html),
        )
        assert "Real sentence" in out or "tokens" in out  # completed, no exception

    async def test_over_limit_page_reports_honestly(self) -> None:
        from dataclasses import replace

        from tearsheet.config import get_settings

        settings = replace(get_settings(), max_response_bytes=10_000)
        html = b"<html><body>" + b"x" * 50_000 + b"</body></html>"
        out = await scrape(
            "https://example.com/huge", render="never",
            settings=settings, transport=transport_for(html),
        )
        assert "error" in out.lower() or "too large" in out.lower()

    async def test_deeply_malformed_html_does_not_crash(self) -> None:
        html = (b"<html><body><div><p>Broken " * 500) + b"<main>salvage me</main>"
        out = await scrape(
            "https://example.com/broken", render="never", transport=transport_for(html)
        )
        assert isinstance(out, str) and out  # honest output, no exception

    async def test_html_served_as_text_plain_is_not_extracted_silently(self) -> None:
        html = b"<html><body><main><p>Actually HTML with $19 $29 $39 $49 prices.</p></main></body></html>"
        out = await scrape(
            "https://example.com/mislabeled", render="never",
            transport=transport_for(html, "text/plain"),
        )
        # text/plain path returns the body verbatim — tags visible = honest, not silent
        assert "<main>" in out or "$19" in out

    async def test_json_served_as_html_reports_shell_not_garbage(self) -> None:
        body = b'{"plans": [{"name": "starter", "price": 19}]}'
        out = await scrape(
            "https://example.com/api-as-html", render="never", transport=transport_for(body)
        )
        assert "no extractable content" in out or "error" in out.lower()

    async def test_empty_200_body_reports_honestly(self) -> None:
        out = await scrape(
            "https://example.com/empty", render="never", transport=transport_for(b"")
        )
        assert "no extractable content" in out or "error" in out.lower()

    async def test_500_with_body_is_an_error_not_content(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                500, content=b"<html><body>Fancy error page $99</body></html>",
                headers={"content-type": "text/html"},
            )

        out = await scrape(
            "https://example.com/down", render="never", transport=httpx.MockTransport(handler)
        )
        assert "HTTP 500" in out
        assert "$99" not in out

    async def test_redirect_chain_reports_final_url(
        self, fixture_bytes: Callable[[str], bytes]
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            host = request.url.host
            if host == "a.example":
                return httpx.Response(301, headers={"location": "https://b.example/x"})
            if host == "b.example":
                return httpx.Response(302, headers={"location": "https://c.example/final"})
            return httpx.Response(
                200, content=fixture_bytes("article.html"), headers={"content-type": "text/html"}
            )

        out = await scrape(
            "https://a.example/start", render="never", transport=httpx.MockTransport(handler)
        )
        assert "url: https://c.example/final" in out

    async def test_transport_timeout_is_an_honest_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("simulated timeout")

        out = await scrape(
            "https://example.com/slow", render="never", transport=httpx.MockTransport(handler)
        )
        assert "error fetching" in out


class TestCharset:
    def test_shift_jis_with_meta_charset_survives_extraction(self) -> None:
        text = "東京の物価は上昇している。データは公式統計から引用した。"
        html = (
            '<html><head><meta charset="shift_jis"></head><body><main><h1>報告</h1><p>'
            + text * 8
            + "</p></main></body></html>"
        ).encode("shift_jis")
        extracted = extract_content(html)
        assert extracted is not None
        assert "東京の物価" in extracted.markdown  # charset detection held

    def test_latin1_with_meta_charset_survives_extraction(self) -> None:
        text = "Le café coûte 3€ près de la gare. Détails à l'intérieur. "
        html = (
            '<html><head><meta charset="iso-8859-1"></head><body><main><p>'
            + text * 30
            + "</p></main></body></html>"
        ).encode("latin-1", errors="ignore")
        extracted = extract_content(html)
        assert extracted is not None
        assert "café" in extracted.markdown

    def test_utf8_bom_is_clean(self) -> None:
        html = b"\xef\xbb\xbf<html><body><main><p>" + b"BOM page content here. " * 30 + b"</p></main></body></html>"
        extracted = extract_content(html)
        assert extracted is not None
        assert "BOM page content" in extracted.markdown
        assert "﻿" not in extracted.markdown

    def test_raw_path_is_utf8_only_pinned_limitation(self) -> None:
        """PINNED LIMITATION (trust-suite review 2026-07-16): html_to_text — the raw
        escape hatch — decodes utf-8-with-replace only. Non-UTF8 pages come back as
        mojibake through --raw (the extractor path handles them; raw does not).
        When this pin fails, charset detection was added to the raw path: update
        the README known-issues entry and delete this test."""
        html = ("<html><body><p>café £3</p></body></html>").encode("latin-1")
        text = html_to_text(html)
        assert "café" not in text  # mojibake today, documented


class TestStructureTorture:
    def test_colspan_rowspan_table_cell_values_survive(self) -> None:
        html = b"""<html><body><main><p>Quarterly figures below.</p><table>
        <tr><th colspan="2">H1</th><th>Q3</th></tr>
        <tr><td>101</td><td rowspan="2">202</td><td>303</td></tr>
        <tr><td>404</td><td>505</td></tr>
        </table><p>End of report with more prose to satisfy extraction.</p></main></body></html>"""
        extracted = extract_content(html)
        assert extracted is not None
        for value in ("101", "202", "303", "404", "505"):
            assert value in extracted.markdown, f"table cell {value} lost silently"

    def test_iframe_content_is_absent_not_faked(self) -> None:
        html = (
            b"<html><body><main><p>"
            + b"Host page prose around an embedded frame. " * 20
            + b'</p><iframe src="https://frames.example/pricing"></iframe></main></body></html>'
        )
        extracted = extract_content(html)
        assert extracted is not None
        assert "frames.example" not in extracted.markdown or "pricing" not in extracted.markdown
        # nothing invented in place of the frame:
        assert "$" not in extracted.markdown

    def test_pre_block_with_html_ish_text_survives(self) -> None:
        html = (
            b"<html><body><main><p>"
            + b"Documentation for template syntax follows in the code block. " * 10
            + b"</p><pre><code>&lt;div class=\"price\"&gt;$19&lt;/div&gt;</code></pre></main></body></html>"
        )
        extracted = extract_content(html)
        assert extracted is not None
        assert 'class="price"' in extracted.markdown or "$19" in extracted.markdown
