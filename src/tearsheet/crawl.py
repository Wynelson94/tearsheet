"""Async BFS crawler: politeness, trap defense, markdown files to disk, compact index return."""

import asyncio
import fnmatch
import json
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from tearsheet.cache import Cache, CachedPage
from tearsheet.config import Settings, get_settings
from tearsheet.content import extract_content
from tearsheet.fetch import fetch_url, needs_render
from tearsheet.mapper import extract_links, host_allowed
from tearsheet.output import estimate_tokens, slugify
from tearsheet.robots import get_policy
from tearsheet.urls import is_crawlable_url, normalize_url

_HTML_TYPES = ("text/html", "application/xhtml+xml", "")


@dataclass
class _PageRecord:
    filename: str
    tokens: int
    title: str
    path: str
    url: str


@dataclass
class _State:
    pages: list[_PageRecord] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    skipped: int = 0
    in_flight: int = 0
    visited: set[str] = field(default_factory=set)


async def crawl(
    url: str,
    *,
    max_pages: int = 30,
    max_depth: int = 2,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    allow_subdomains: bool = False,
    output_dir: str | None = None,
    render: str = "auto",
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    settings = settings or get_settings()
    cache = Cache(settings.cache_db)
    try:
        return await _crawl(
            url,
            max_pages=max_pages,
            max_depth=max_depth,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            allow_subdomains=allow_subdomains,
            output_dir=output_dir,
            settings=settings,
            transport=transport,
            cache=cache,
        )
    finally:
        cache.close()


async def _crawl(
    url: str,
    *,
    max_pages: int,
    max_depth: int,
    include_patterns: list[str] | None,
    exclude_patterns: list[str] | None,
    allow_subdomains: bool,
    output_dir: str | None,
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None,
    cache: Cache,
) -> str:
    start = normalize_url(url)
    root_host = urlsplit(start).netloc
    policy = await get_policy(start, cache=cache, settings=settings, transport=transport)
    delay = max(settings.per_domain_delay_seconds, policy.crawl_delay or 0.0)

    if output_dir:
        out_dir = Path(output_dir).expanduser()
    else:
        stamp = datetime.now().strftime("%Y%m%d")
        out_dir = settings.crawls_dir / f"{slugify(root_host)}-{stamp}-{secrets.token_hex(2)}"
    out_dir.mkdir(parents=True, exist_ok=True)

    state = _State(visited={start})
    lock = asyncio.Lock()
    queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
    queue.put_nowait((start, 0))

    def frontier_ok(link: str) -> bool:
        path = urlsplit(link).path or "/"
        if not host_allowed(link, root_host, allow_subdomains) or not is_crawlable_url(link):
            return False
        if exclude_patterns and any(fnmatch.fnmatch(path, p) for p in exclude_patterns):
            return False
        if include_patterns and not any(fnmatch.fnmatch(path, p) for p in include_patterns):
            return False
        return True

    async def process(current_url: str, depth: int) -> None:
        display_path = urlsplit(current_url).path or "/"
        async with lock:
            if len(state.pages) + state.in_flight >= max_pages:
                return
            state.in_flight += 1
        try:
            if not policy.allowed(current_url):
                async with lock:
                    state.skipped += 1
                return
            result = await fetch_url(current_url, settings=settings, transport=transport)
            if result.error:
                async with lock:
                    state.errors.append((display_path, result.error))
                return
            if result.status >= 400:
                async with lock:
                    state.errors.append((display_path, str(result.status)))
                return
            if result.content_type not in _HTML_TYPES:
                async with lock:
                    state.skipped += 1
                return
            body = result.body or b""
            extracted = extract_content(body, url=result.final_url)
            if extracted is None or needs_render(body, extracted.markdown):
                async with lock:
                    state.skipped += 1
                return

            title = extracted.title or display_path
            tokens = estimate_tokens(extracted.markdown)
            async with lock:
                number = len(state.pages) + 1
                record = _PageRecord(
                    filename=f"{number:03d}-{slugify(title)}.md",
                    tokens=tokens,
                    title=title,
                    path=display_path,
                    url=result.final_url,
                )
                state.pages.append(record)
            front_matter = (
                f"---\nurl: {result.final_url}\ntitle: {title}\n"
                f"fetched: {datetime.now().strftime('%Y-%m-%d')}\ntokens: {tokens}\n---\n\n"
            )
            (out_dir / record.filename).write_text(front_matter + extracted.markdown)
            cache.put_page(
                CachedPage(
                    url=current_url,
                    final_url=result.final_url,
                    fetched_at=int(time.time()),
                    status=result.status,
                    content_type=result.content_type,
                    via="httpx",
                    html=body,
                    markdown=extracted.markdown,
                    title=extracted.title,
                )
            )

            if depth < max_depth:
                for link in extract_links(body, result.final_url):
                    if not frontier_ok(link):
                        continue
                    async with lock:
                        if link in state.visited:
                            continue
                        state.visited.add(link)
                    queue.put_nowait((link, depth + 1))
        finally:
            async with lock:
                state.in_flight -= 1

    async def worker() -> None:
        while True:
            current_url, depth = await queue.get()
            try:
                if delay:
                    await asyncio.sleep(delay)
                await process(current_url, depth)
            finally:
                queue.task_done()

    workers = [
        asyncio.create_task(worker()) for _ in range(settings.per_domain_concurrency)
    ]
    await queue.join()
    for w in workers:
        w.cancel()

    crawl_id = secrets.token_hex(8)
    index_lines = [
        f"{p.filename:<32} ~{p.tokens}tok  {p.title:<28} {p.path}" for p in state.pages
    ]
    summary = (
        f"crawl: {root_host}  pages: {len(state.pages)}  errors: {len(state.errors)}"
        f"  skipped(robots/dupe/type): {state.skipped}"
    )
    lines = [summary, f"dir: {out_dir}", *index_lines]
    for path, reason in state.errors:
        lines.append(f"errors: {path} ({reason})")
    report = "\n".join(lines)

    (out_dir / "INDEX.md").write_text(report + "\n")
    (out_dir / "index.json").write_text(
        json.dumps(
            [
                {"url": p.url, "title": p.title, "file": p.filename, "tokens": p.tokens}
                for p in state.pages
            ],
            indent=2,
        )
    )
    cache.log_crawl(crawl_id, start, int(time.time()), len(state.pages), str(out_dir))
    return report
