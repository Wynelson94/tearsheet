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


_NON_CONTENT_EXTENSIONS = frozenset(
    ["jpg", "jpeg", "png", "gif", "webp", "svg", "ico", "css", "js", "mjs", "map", "woff", "woff2", "ttf", "otf", "eot", "zip", "gz", "tar", "tgz", "bz2", "7z", "rar", "dmg", "exe", "msi", "mp3", "mp4", "mov", "avi", "mkv", "webm", "wav", "flac", "doc", "docx", "xls", "xlsx", "ppt", "pptx"]
)
_MAX_QUERY_PARAMS = 3


def is_crawlable_url(url: str) -> bool:
    """Trap defense: reject urls unlikely to be content pages (crawler frontier filter)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return False
    if len(parse_qsl(parts.query, keep_blank_values=True)) > _MAX_QUERY_PARAMS:
        return False
    segments = [s for s in parts.path.split("/") if s]
    # repeating pair pattern like /a/b/a/b — classic calendar/breadcrumb loop
    if len(segments) >= 4:
        for i in range(len(segments) - 3):
            if segments[i] == segments[i + 2] and segments[i + 1] == segments[i + 3]:
                return False
    if segments and "." in segments[-1]:
        ext = segments[-1].rsplit(".", 1)[-1].lower()
        if ext in _NON_CONTENT_EXTENSIONS:
            return False
    return True
