"""FastMCP stdio server: token-efficient web tools for Claude Code."""

from fastmcp import FastMCP

from tearsheet.crawl import crawl as crawl_site
from tearsheet.mapper import map_site
from tearsheet.scrape import scrape as scrape_page
from tearsheet.search import search as search_web
from tearsheet.structured import extract_page

mcp: FastMCP = FastMCP("tearsheet")


@mcp.tool
async def extract(
    url: str,
    types: list[str] | None = None,
    max_rows: int = 100,
    render: str = "auto",
) -> str:
    """Deterministic structured data from a page as JSON: JSON-LD, OpenGraph, microdata, HTML tables.

    No LLM involved — this returns what the page itself declares. Reuses HTML cached by a
    prior scrape of the same URL (no refetch). For semantic extraction, scrape the page and
    read the markdown instead.

    Args:
        url: Absolute http(s) URL.
        types: Subset of ["json-ld", "opengraph", "microdata", "tables"] (default: all).
        max_rows: Per-table row cap.
        render: "auto", "never", or "always" (headless browser).
    """
    return await extract_page(url, types=types, max_rows=max_rows, render=render)


@mcp.tool
async def scrape(
    url: str,
    max_length: int = 8000,
    render: str = "auto",
    include_links: bool = False,
    fresh: bool = False,
) -> str:
    """Fetch one URL and return clean main-content markdown (boilerplate stripped).

    Output starts with a header (final url, title, cache status, token counts), then the
    markdown. When truncated, the full markdown is on disk at the path shown in the header —
    Read that file instead of re-scraping with a larger max_length. Results are cached
    (pass fresh=true to force a refetch). For whole sites, prefer map -> pick URLs -> scrape,
    or crawl, which writes files to disk and returns only an index.

    Args:
        url: Absolute http(s) URL to fetch.
        max_length: Max characters of markdown returned in-context; 0 = unlimited.
        render: "auto" (headless browser only when the page looks JS-rendered),
            "never", or "always".
        include_links: Keep hyperlinks in the markdown (token-heavy; off by default).
        fresh: Bypass the cache and refetch.
    """
    return await scrape_page(
        url, max_length=max_length, render=render, include_links=include_links, fresh=fresh
    )


@mcp.tool
async def search(query: str, max_results: int = 8, backend: str = "auto") -> str:
    """Web search (keyless metasearch). Returns numbered results: title, url, one snippet line.

    Use the snippets to decide which results are worth scraping, then call scrape on those
    URLs. No API key required; backends rotate automatically.

    Args:
        query: Search query.
        max_results: Number of results to return.
        backend: Search backend ("auto" rotates; or e.g. "duckduckgo", "brave", "bing").
    """
    return await search_web(query, max_results=max_results, backend=backend)


@mcp.tool
async def map(  # noqa: A001 - tool name mirrors Firecrawl's API
    url: str,
    max_urls: int = 200,
    search: str | None = None,
    use_sitemap: bool = True,
    include_subdomains: bool = False,
) -> str:
    """List a site's URLs (sitemap.xml first, plus links found on the given page) WITHOUT scraping them.

    Cheapest way to see what a site contains: map first, pick the URLs that matter, then
    scrape only those. Returns one path per line (root shown once in the summary line).

    Args:
        url: Site root or any page on the site.
        max_urls: Cap on URLs returned.
        search: Case-insensitive substring filter (e.g. "auth" to find auth-related pages).
        use_sitemap: Try sitemap.xml (and sitemap indexes) before link discovery.
        include_subdomains: Also keep URLs on sibling subdomains.
    """
    return await map_site(
        url,
        max_urls=max_urls,
        search=search,
        use_sitemap=use_sitemap,
        include_subdomains=include_subdomains,
    )


@mcp.tool
async def crawl(
    url: str,
    max_pages: int = 30,
    max_depth: int = 2,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    allow_subdomains: bool = False,
    output_dir: str | None = None,
    render: str = "auto",
) -> str:
    """Crawl a site breadth-first and save each page as a markdown file on disk.

    Page content NEVER enters this tool's output: you get a compact index (filename,
    ~token estimate, title, path) plus the output directory. Read the files you need
    afterwards. Obeys robots.txt and rate-limits itself. Use include_patterns like
    ["/docs/*"] to stay inside one section.

    Args:
        url: Start URL (its host bounds the crawl).
        max_pages: Hard cap on pages saved.
        max_depth: Link-following depth from the start URL.
        include_patterns: Glob patterns on URL paths; discovered links must match one.
        exclude_patterns: Glob patterns on URL paths to skip; wins over include.
        allow_subdomains: Follow links onto sibling subdomains.
        output_dir: Where to write files (default: ~/.tearsheet/crawls/<site>-<date>-<id>/).
        render: Reserved for JS rendering ("auto"/"never"/"always").
    """
    return await crawl_site(
        url,
        max_pages=max_pages,
        max_depth=max_depth,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
        allow_subdomains=allow_subdomains,
        output_dir=output_dir,
        render=render,
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
