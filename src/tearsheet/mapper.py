"""URL discovery: sitemap.xml (including sitemap indexes) plus shallow link discovery."""

from urllib.parse import urljoin, urlsplit

import httpx
from lxml import etree
from lxml import html as lxml_html

from tearsheet.config import Settings, get_settings
from tearsheet.fetch import fetch_url
from tearsheet.urls import is_crawlable_url, normalize_url

_MAX_CHILD_SITEMAPS = 20


def extract_links(html: bytes, base_url: str) -> list[str]:
    """Absolute, deduped, order-preserving http(s) links from a page."""
    try:
        tree = lxml_html.fromstring(html)
    except etree.ParserError:
        return []
    seen: set[str] = set()
    links: list[str] = []
    for href in tree.xpath("//a/@href"):
        absolute = urljoin(base_url, str(href).strip())
        if not absolute.startswith(("http://", "https://")):
            continue
        normalized = normalize_url(absolute)
        if normalized not in seen:
            seen.add(normalized)
            links.append(normalized)
    return links


def _sitemap_locs(body: bytes) -> tuple[list[str], bool]:
    """(locs, is_index) — namespace-agnostic <loc> extraction."""
    try:
        root = etree.fromstring(body)
    except etree.XMLSyntaxError:
        return [], False
    locs = [str(loc).strip() for loc in root.xpath("//*[local-name()='loc']/text()")]
    is_index = etree.QName(root).localname == "sitemapindex"
    return locs, is_index


def host_allowed(url: str, root_host: str, include_subdomains: bool) -> bool:
    host = urlsplit(url).netloc.lower()
    if host == root_host:
        return True
    if include_subdomains:
        base = root_host.removeprefix("www.")
        base = base.split(".", 1)[1] if base.count(".") >= 2 else base
        return host == base or host.endswith("." + base)
    return False


async def map_site(
    url: str,
    *,
    max_urls: int = 200,
    search: str | None = None,
    use_sitemap: bool = True,
    include_subdomains: bool = False,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    settings = settings or get_settings()
    parts = urlsplit(url)
    root = f"{parts.scheme}://{parts.netloc}"
    root_host = parts.netloc.lower()

    sitemap_urls: list[str] = []
    if use_sitemap:
        # try the host root first, then the URL's own directory (subpath-hosted sites
        # like docs.astral.sh/ruff/ keep sitemap.xml under the prefix, not at the root)
        candidates = [f"{root}/sitemap.xml"]
        prefix = parts.path.rstrip("/")
        if prefix:
            candidates.append(f"{root}{prefix}/sitemap.xml")
        result = None
        for candidate in candidates:
            attempt = await fetch_url(candidate, settings=settings, transport=transport)
            if attempt.status == 200 and attempt.body and _sitemap_locs(attempt.body)[0]:
                result = attempt
                break
        if result is not None and result.body:
            locs, is_index = _sitemap_locs(result.body)
            if is_index:
                for child in locs[:_MAX_CHILD_SITEMAPS]:
                    child_result = await fetch_url(child, settings=settings, transport=transport)
                    if child_result.status == 200 and child_result.body:
                        child_locs, _ = _sitemap_locs(child_result.body)
                        sitemap_urls.extend(child_locs)
                    if len(sitemap_urls) >= max_urls * 2:
                        break
            else:
                sitemap_urls = locs

    page_result = await fetch_url(url, settings=settings, transport=transport)
    page_links = (
        extract_links(page_result.body, page_result.final_url)
        if page_result.status == 200 and page_result.body
        else []
    )

    def keep(u: str) -> bool:
        return host_allowed(u, root_host, include_subdomains) and is_crawlable_url(u)

    seen: set[str] = set()
    collected: list[str] = []
    counts = {"sitemap": 0, "links": 0}
    for source, urls in (("sitemap", sitemap_urls), ("links", page_links)):
        for u in urls:
            normalized = normalize_url(u)
            if normalized in seen or not keep(normalized):
                continue
            seen.add(normalized)
            collected.append(normalized)
            counts[source] += 1

    matching = [u for u in collected if search.lower() in u.lower()] if search else collected
    shown = matching[:max_urls]

    summary = f"site: {root} — {len(collected)} urls (sitemap {counts['sitemap']}, links {counts['links']})"
    if search:
        summary += f'; showing {len(shown)} matching "{search}"'
    elif len(shown) < len(matching):
        summary += f"; showing {len(shown)}"

    def display(u: str) -> str:
        split = urlsplit(u)
        if split.netloc.lower() == root_host:
            path = split.path or "/"
            return path + (f"?{split.query}" if split.query else "")
        return u

    return "\n".join([summary, *(display(u) for u in shown)])
