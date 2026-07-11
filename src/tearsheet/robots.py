"""robots.txt fetching (cached) and policy checks via protego."""

from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from protego import Protego

from tearsheet.cache import Cache
from tearsheet.config import Settings

_MAX_CRAWL_DELAY = 10.0


@dataclass
class RobotsPolicy:
    _parser: Protego
    crawl_delay: float | None
    user_agent: str

    def allowed(self, url: str) -> bool:
        return bool(self._parser.can_fetch(url, self.user_agent))


async def get_policy(
    url: str,
    *,
    cache: Cache,
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None = None,
) -> RobotsPolicy:
    """Robots policy for the host of `url`. Missing/unfetchable robots.txt allows everything."""
    parts = urlsplit(url)
    host = f"{parts.scheme}://{parts.netloc}"
    cached = cache.get_robots(host, settings.robots_ttl_seconds)
    if cached is not None:
        body, _ = cached
    else:
        body = ""
        try:
            async with httpx.AsyncClient(
                timeout=settings.timeout_seconds,
                headers={"User-Agent": settings.user_agent},
                follow_redirects=True,
                transport=transport,
            ) as client:
                response = await client.get(f"{host}/robots.txt")
                if response.status_code == 200:
                    body = response.text
        except httpx.HTTPError:
            body = ""
        parser = Protego.parse(body)
        delay = _capped_delay(parser, settings.user_agent)
        cache.put_robots(host, body, delay)
    parser = Protego.parse(body)
    return RobotsPolicy(
        _parser=parser,
        crawl_delay=_capped_delay(parser, settings.user_agent),
        user_agent=settings.user_agent,
    )


def _capped_delay(parser: Protego, user_agent: str) -> float | None:
    delay = parser.crawl_delay(user_agent)
    if delay is None:
        return None
    return min(float(delay), _MAX_CRAWL_DELAY)
