"""URL normalization and hashing shared by cache and crawler."""

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_EXACT = {"fbclid", "gclid", "ref"}
_TRACKING_PREFIXES = ("utm_",)


def _is_tracking(param: str) -> bool:
    return param in _TRACKING_EXACT or param.startswith(_TRACKING_PREFIXES)


def normalize_url(url: str) -> str:
    parts = urlsplit(url)
    pairs = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)
    ]
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/"),
            urlencode(sorted(pairs)),
            "",  # fragment always dropped
        )
    )


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()[:32]
