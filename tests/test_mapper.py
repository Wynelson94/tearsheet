from collections.abc import Callable

import httpx

from tearsheet.mapper import extract_links, map_site

ROOT_PAGE = b"""<html><body>
<a href="/docs/start">Start</a>
<a href="/docs/config">Config</a>
<a href="https://docs.example.com/docs/linked-only">Linked only</a>
<a href="https://other.com/offsite">Offsite</a>
<a href="mailto:x@y.com">Mail</a>
<a href="javascript:void(0)">JS</a>
<a href="/docs/start">Duplicate</a>
</body></html>"""


def site_transport(
    fixture_bytes: Callable[[str], bytes], routes: dict[str, bytes] | None = None
) -> httpx.MockTransport:
    table: dict[str, bytes] = {
        "/sitemap.xml": fixture_bytes("sitemap.xml"),
        "/": ROOT_PAGE,
    }
    if routes:
        table = routes

    def handler(request: httpx.Request) -> httpx.Response:
        body = table.get(request.url.path)
        if body is None:
            return httpx.Response(404, text="nope")
        content_type = "application/xml" if request.url.path.endswith(".xml") else "text/html"
        return httpx.Response(200, content=body, headers={"content-type": content_type})

    return httpx.MockTransport(handler)


class TestExtractLinks:
    def test_resolves_relative_and_dedupes(self) -> None:
        links = extract_links(ROOT_PAGE, "https://docs.example.com/")
        assert "https://docs.example.com/docs/start" in links
        assert links.count("https://docs.example.com/docs/start") == 1

    def test_skips_non_http_schemes(self) -> None:
        links = extract_links(ROOT_PAGE, "https://docs.example.com/")
        assert not any(link.startswith(("mailto:", "javascript:")) for link in links)


class TestMapSite:
    async def test_combines_sitemap_and_page_links(
        self, fixture_bytes: Callable[[str], bytes]
    ) -> None:
        out = await map_site(
            "https://docs.example.com/", transport=site_transport(fixture_bytes)
        )
        assert out.splitlines()[0].startswith("site: https://docs.example.com")
        assert "sitemap 5" in out  # 6 sitemap urls minus 1 foreign subdomain
        assert "/docs/start" in out
        assert "/docs/linked-only" in out  # discovered from page, not sitemap

    def _lines(self, out: str) -> list[str]:
        return out.splitlines()[1:]

    async def test_excludes_subdomains_by_default(
        self, fixture_bytes: Callable[[str], bytes]
    ) -> None:
        out = await map_site(
            "https://docs.example.com/", transport=site_transport(fixture_bytes)
        )
        assert "external-subdomain-post" not in out

    async def test_includes_subdomains_on_request(
        self, fixture_bytes: Callable[[str], bytes]
    ) -> None:
        out = await map_site(
            "https://docs.example.com/",
            include_subdomains=True,
            transport=site_transport(fixture_bytes),
        )
        assert "https://blog.example.com/external-subdomain-post" in out

    async def test_search_filter(self, fixture_bytes: Callable[[str], bytes]) -> None:
        out = await map_site(
            "https://docs.example.com/", search="auth", transport=site_transport(fixture_bytes)
        )
        body = self._lines(out)
        assert "/docs/auth/login" in body
        assert "/docs/auth/tokens" in body
        assert not any("config" in line for line in body)

    async def test_max_urls_cap(self, fixture_bytes: Callable[[str], bytes]) -> None:
        out = await map_site(
            "https://docs.example.com/", max_urls=2, transport=site_transport(fixture_bytes)
        )
        assert len(self._lines(out)) == 2
        assert "showing 2" in out.splitlines()[0]

    async def test_sitemap_index_follows_children(
        self, fixture_bytes: Callable[[str], bytes]
    ) -> None:
        routes = {
            "/sitemap.xml": fixture_bytes("sitemap_index.xml"),
            "/sitemap-a.xml": b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            b"<url><loc>https://docs.example.com/a1</loc></url></urlset>",
            "/sitemap-b.xml": b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            b"<url><loc>https://docs.example.com/b1</loc></url></urlset>",
            "/": b"<html><body></body></html>",
        }
        out = await map_site(
            "https://docs.example.com/", transport=site_transport(fixture_bytes, routes)
        )
        assert "/a1" in out
        assert "/b1" in out

    async def test_subpath_sitemap_discovered(
        self, fixture_bytes: Callable[[str], bytes]
    ) -> None:
        # sites hosted under a path prefix (docs.astral.sh/ruff/) keep sitemap.xml there
        routes = {
            "/ruff/sitemap.xml": b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            b"<url><loc>https://docs.example.com/ruff/settings</loc></url></urlset>",
            "/ruff/": b"<html><body></body></html>",
        }
        out = await map_site(
            "https://docs.example.com/ruff/", transport=site_transport(fixture_bytes, routes)
        )
        assert "sitemap 1" in out
        assert "/ruff/settings" in out

    async def test_no_sitemap_falls_back_to_links_only(
        self, fixture_bytes: Callable[[str], bytes]
    ) -> None:
        routes = {"/": ROOT_PAGE}
        out = await map_site(
            "https://docs.example.com/", transport=site_transport(fixture_bytes, routes)
        )
        assert "sitemap 0" in out
        assert "/docs/start" in out
