"""FastMCP stdio server: token-efficient web tools for Claude Code."""

from fastmcp import FastMCP

from tearsheet.scrape import scrape as scrape_page
from tearsheet.search import search as search_web

mcp: FastMCP = FastMCP("tearsheet")


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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
