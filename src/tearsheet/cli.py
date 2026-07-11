"""Thin CLI over the same core functions the MCP server uses."""

import argparse
import asyncio

from tearsheet.crawl import crawl
from tearsheet.mapper import map_site
from tearsheet.scrape import scrape


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tearsheet", description="Local web-to-markdown for LLM research.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scrape = sub.add_parser("scrape", help="Fetch one URL and print clean markdown")
    p_scrape.add_argument("url")
    p_scrape.add_argument("--max-length", type=int, default=8000, help="chars shown; 0 = unlimited")
    p_scrape.add_argument("--links", action="store_true", help="keep hyperlinks in markdown")
    p_scrape.add_argument("--fresh", action="store_true", help="bypass cache")
    p_scrape.add_argument("--render", choices=["auto", "never", "always"], default="auto")

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
    print(out)


if __name__ == "__main__":
    main()
