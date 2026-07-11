import dataclasses
import json
from pathlib import Path

import httpx
import pytest

from tearsheet.config import get_settings
from tearsheet.crawl import crawl

BODY = (
    "This page holds a healthy paragraph of real prose so the extractor has something "
    "substantial to work with. It talks about configuration, deployment, and the quiet "
    "satisfaction of documentation that answers the question you actually asked. "
    "Nothing here is boilerplate; every sentence is load-bearing for the tests."
)


def page(title: str, links: list[str]) -> bytes:
    anchors = "".join(f'<a href="{href}">{href}</a> ' for href in links)
    return (
        f"<html><head><title>{title}</title></head><body>"
        f"<main><h1>{title}</h1><p>{BODY}</p><p>{anchors}</p></main>"
        f"</body></html>"
    ).encode()


SITE: dict[str, bytes] = {
    "/": page("Home", ["/docs/a", "/docs/b", "/admin/secret", "/asset.png", "/docs/a", "/docs/broken", "https://other.com/offsite"]),
    "/docs/a": page("Docs A", ["/docs/a1", "/docs/a2"]),
    "/docs/b": page("Docs B", ["/docs/b1"]),
    "/docs/a1": page("Docs A1", ["/docs/deep"]),
    "/docs/a2": page("Docs A2", []),
    "/docs/b1": page("Docs B1", []),
    "/docs/deep": page("Deep Page", []),
    "/admin/secret": page("Secret", []),
    "/blog/post": page("Blog Post", []),
}

ROBOTS = b"User-agent: *\nDisallow: /admin\n"


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    monkeypatch.setenv("TEARSHEET_HOME", str(home))
    return home


@pytest.fixture
def requests_seen() -> list[str]:
    return []


@pytest.fixture
def site(requests_seen: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host != "docs.example.com":
            raise AssertionError(f"crawler left the site: {request.url}")
        path = request.url.path
        requests_seen.append(path)
        if path == "/robots.txt":
            return httpx.Response(200, content=ROBOTS, headers={"content-type": "text/plain"})
        body = SITE.get(path)
        if body is None:
            return httpx.Response(404, text="nope")
        return httpx.Response(200, content=body, headers={"content-type": "text/html"})

    return httpx.MockTransport(handler)


def fast_settings():  # type: ignore[no-untyped-def]
    return dataclasses.replace(get_settings(), per_domain_delay_seconds=0.0)


async def run_crawl(transport: httpx.MockTransport, **kw: object) -> str:
    return await crawl(
        "https://docs.example.com/",
        settings=fast_settings(),
        transport=transport,
        **kw,  # type: ignore[arg-type]
    )


def crawl_dir_of(out: str) -> Path:
    dir_line = next(line for line in out.splitlines() if line.startswith("dir: "))
    return Path(dir_line.removeprefix("dir: ").strip())


class TestCrawlCoverage:
    async def test_reaches_all_pages_within_depth(self, site: httpx.MockTransport) -> None:
        out = await run_crawl(site, max_pages=30, max_depth=3)
        d = crawl_dir_of(out)
        files = sorted(p.name for p in d.glob("[0-9]*.md"))
        assert len(files) == 7  # home, a, b, a1, a2, b1, deep — not admin/asset/offsite/blog
        assert "pages: 7" in out

    async def test_max_depth_respected(self, site: httpx.MockTransport) -> None:
        out = await run_crawl(site, max_depth=1)
        assert "docs-a1" not in out and "docs-b1" not in out
        assert "Docs A" in out  # depth-1 pages present

    async def test_max_pages_respected(self, site: httpx.MockTransport) -> None:
        out = await run_crawl(site, max_pages=3, max_depth=3)
        d = crawl_dir_of(out)
        assert len(list(d.glob("[0-9]*.md"))) == 3

    async def test_offsite_never_fetched(self, site: httpx.MockTransport) -> None:
        # the site fixture raises AssertionError on any non-docs.example.com request
        await run_crawl(site, max_pages=30, max_depth=3)


class TestCrawlPoliteness:
    async def test_robots_disallowed_not_fetched(
        self, site: httpx.MockTransport, requests_seen: list[str]
    ) -> None:
        out = await run_crawl(site, max_pages=30, max_depth=3)
        assert "/admin/secret" not in requests_seen
        assert "skipped" in out

    async def test_asset_urls_not_fetched(
        self, site: httpx.MockTransport, requests_seen: list[str]
    ) -> None:
        await run_crawl(site, max_pages=30, max_depth=3)
        assert "/asset.png" not in requests_seen


class TestCrawlPatterns:
    async def test_include_patterns_limit_frontier(
        self, site: httpx.MockTransport, requests_seen: list[str]
    ) -> None:
        out = await run_crawl(site, include_patterns=["/docs/*"], max_pages=30, max_depth=3)
        assert "pages: " in out
        assert "/blog/post" not in requests_seen

    async def test_exclude_patterns(
        self, site: httpx.MockTransport, requests_seen: list[str]
    ) -> None:
        await run_crawl(site, exclude_patterns=["/docs/b*"], max_pages=30, max_depth=3)
        assert "/docs/b" not in requests_seen
        assert "/docs/b1" not in requests_seen


class TestCrawlOutput:
    async def test_files_have_front_matter(self, site: httpx.MockTransport) -> None:
        out = await run_crawl(site, max_pages=5)
        d = crawl_dir_of(out)
        first = sorted(d.glob("[0-9]*.md"))[0].read_text()
        assert first.startswith("---\n")
        assert "url: https://docs.example.com" in first
        assert "title:" in first
        assert "tokens:" in first

    async def test_index_files_written(self, site: httpx.MockTransport) -> None:
        out = await run_crawl(site, max_pages=5)
        d = crawl_dir_of(out)
        assert (d / "INDEX.md").exists()
        index = json.loads((d / "index.json").read_text())
        assert len(index) >= 3
        assert {"url", "title", "file", "tokens"} <= set(index[0])

    async def test_returned_index_is_compact_not_content(
        self, site: httpx.MockTransport
    ) -> None:
        out = await run_crawl(site, max_pages=30, max_depth=3)
        assert out.splitlines()[0].startswith("crawl: docs.example.com")
        assert "~" in out  # token estimates
        assert BODY[:40] not in out  # page content never enters the return value

    async def test_errors_reported(self, site: httpx.MockTransport) -> None:
        out = await run_crawl(site, max_pages=30, max_depth=3)
        assert "errors: 1" in out
        assert "/docs/broken (404)" in out

    async def test_custom_output_dir(self, site: httpx.MockTransport, tmp_path: Path) -> None:
        target = tmp_path / "my-research"
        out = await run_crawl(site, max_pages=3, output_dir=str(target))
        assert crawl_dir_of(out) == target
        assert list(target.glob("[0-9]*.md"))
