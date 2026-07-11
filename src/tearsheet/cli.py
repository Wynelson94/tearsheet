"""Thin CLI over the same core functions the MCP server uses."""

import argparse
import asyncio

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
        print(out)


if __name__ == "__main__":
    main()
