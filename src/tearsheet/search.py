"""Keyless metasearch via ddgs (sync lib, called in a thread) with compact formatting."""

import asyncio

from ddgs import DDGS


def format_results(results: list[dict[str, str]]) -> str:
    lines = []
    for i, r in enumerate(results, 1):
        url = r.get("href") or r.get("url") or ""
        snippet = " ".join((r.get("body") or "").split())
        if len(snippet) > 200:
            snippet = snippet[:199].rstrip() + "…"
        lines.append(f"{i}. {r.get('title', '(untitled)')} — {url}")
        if snippet:
            lines.append(f"   {snippet}")
    return "\n".join(lines)


async def search(query: str, *, max_results: int = 8, backend: str = "auto") -> str:
    def run() -> list[dict[str, str]]:
        return DDGS().text(query, max_results=max_results, backend=backend)

    try:
        results = await asyncio.to_thread(run)
    except Exception as exc:
        return f"search failed: {type(exc).__name__}: {exc}"
    if not results:
        return f"no results for: {query}"
    return format_results(results)
