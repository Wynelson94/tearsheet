"""Token estimation, truncation, and filename/index formatting."""

import re


def estimate_tokens(text: str) -> int:
    return len(text) // 4


def truncate(text: str, max_chars: int) -> tuple[str, bool]:
    """Truncate at a line boundary within max_chars. max_chars=0 means unlimited."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    cut = text.rfind("\n", 0, max_chars + 1)
    if cut <= 0:
        return text[:max_chars], True
    return text[: cut + 1], True


def slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower().replace("'", "").replace("’", "")).strip(
        "-"
    )
    if len(slug) > max_len:
        slug = slug[:max_len].rsplit("-", 1)[0]
    return slug or "untitled"
