"""Thin CLI over the same core functions the MCP server uses."""

import argparse
import asyncio

from tearsheet.crawl import crawl
from tearsheet.mapper import map_site
from tearsheet.scrape import scrape
from tearsheet.search import search
from tearsheet.structured import extract_page


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tearsheet", description="Local web-to-markdown for LLM research.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scrape = sub.add_parser("scrape", help="Fetch one URL and print clean markdown")
    p_scrape.add_argument("url")
    p_scrape.add_argument("--max-length", type=int, default=8000, help="chars shown; 0 = unlimited")
    p_scrape.add_argument("--links", action="store_true", help="keep hyperlinks in markdown")
    p_scrape.add_argument("--fresh", action="store_true", help="bypass cache")
    p_scrape.add_argument("--render", choices=["auto", "never", "always"], default="auto")
    p_scrape.add_argument(
        "--raw",
        action="store_true",
        help="skip the extractor; print the page's visible text (recovers tables/prices)",
    )

    p_map = sub.add_parser("map", help="List a site's URLs without scraping them")
    p_map.add_argument("url")
    p_map.add_argument("--max-urls", type=int, default=200)
    p_map.add_argument("--search", default=None, help="substring filter")
    p_map.add_argument("--no-sitemap", action="store_true", help="skip sitemap.xml")
    p_map.add_argument("--subdomains", action="store_true", help="include sibling subdomains")

    p_crawl = sub.add_parser("crawl", help="Crawl a site to markdown files + index")
    p_crawl.add_argument("url")
    p_crawl.add_argument("--max-pages", type=int, default=30)
    p_crawl.add_argument("--max-depth", type=int, default=2)
    p_crawl.add_argument("--include", action="append", default=None, help="path glob, repeatable")
    p_crawl.add_argument("--exclude", action="append", default=None, help="path glob, repeatable")
    p_crawl.add_argument("--subdomains", action="store_true")
    p_crawl.add_argument("--output-dir", default=None)
    p_crawl.add_argument("--render", choices=["auto", "never", "always"], default="auto")

    p_extract = sub.add_parser(
        "extract", help="Structured data (JSON-LD/OG/microdata/tables) as JSON"
    )
    p_extract.add_argument("url")
    p_extract.add_argument(
        "--types",
        action="append",
        default=None,
        choices=["json-ld", "opengraph", "microdata", "tables"],
        help="repeatable; default all",
    )
    p_extract.add_argument("--max-rows", type=int, default=100)
    p_extract.add_argument("--render", choices=["auto", "never", "always"], default="auto")

    p_search = sub.add_parser("search", help="Keyless web metasearch")
    p_search.add_argument("query")
    p_search.add_argument("--max-results", type=int, default=8)
    p_search.add_argument("--backend", default="auto")

    p_cache = sub.add_parser("cache", help="Inspect or clean the local cache")
    cache_sub = p_cache.add_subparsers(dest="cache_command", required=True)
    cache_sub.add_parser("stats", help="Entry counts and database size")
    p_prune = cache_sub.add_parser("prune", help="Delete entries older than --days")
    p_prune.add_argument("--days", type=int, default=30)
    cache_sub.add_parser("clear", help="Delete everything")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "scrape":
        out = asyncio.run(
            scrape(
                args.url,
                max_length=args.max_length,
                include_links=args.links,
                fresh=args.fresh,
                render=args.render,
                raw=args.raw,
            )
        )
    elif args.command == "map":
        out = asyncio.run(
            map_site(
                args.url,
                max_urls=args.max_urls,
                search=args.search,
                use_sitemap=not args.no_sitemap,
                include_subdomains=args.subdomains,
            )
        )
    elif args.command == "crawl":
        out = asyncio.run(
            crawl(
                args.url,
                max_pages=args.max_pages,
                max_depth=args.max_depth,
                include_patterns=args.include,
                exclude_patterns=args.exclude,
                allow_subdomains=args.subdomains,
                output_dir=args.output_dir,
                render=args.render,
            )
        )
    elif args.command == "extract":
        out = asyncio.run(
            extract_page(
                args.url,
                types=args.types,
                max_rows=args.max_rows,
                render=args.render,
            )
        )
    elif args.command == "search":
        out = asyncio.run(
            search(args.query, max_results=args.max_results, backend=args.backend)
        )
    elif args.command == "cache":
        out = _run_cache_command(args)
    print(out)


def _run_cache_command(args: argparse.Namespace) -> str:
    from tearsheet.cache import Cache
    from tearsheet.config import get_settings

    cache = Cache(get_settings().cache_db)
    try:
        if args.cache_command == "stats":
            s = cache.stats()
            return (
                f"pages: {s['pages']}  robots: {s['robots']}  crawls: {s['crawls']}"
                f"  size: {s['db_bytes'] / 1024:.0f} KiB"
            )
        if args.cache_command == "prune":
            removed = cache.prune(older_than_seconds=args.days * 86400)
            return f"pruned {removed} entries older than {args.days} days"
        cache.clear()
        return "cache cleared"
    finally:
        cache.close()


if __name__ == "__main__":
    main()
