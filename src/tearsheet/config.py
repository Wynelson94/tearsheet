"""Defaults and environment overrides (TEARSHEET_HOME, TEARSHEET_UA, TEARSHEET_TTL)."""

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_UA = "tearsheet/0.1 (+https://github.com/Wynelson94/tearsheet; research tool)"


@dataclass(frozen=True)
class Settings:
    home: Path
    user_agent: str
    page_ttl_seconds: int
    robots_ttl_seconds: int = 24 * 3600
    max_response_bytes: int = 5 * 1024 * 1024
    timeout_seconds: float = 20.0
    per_domain_concurrency: int = 2
    per_domain_delay_seconds: float = 1.0
    global_concurrency: int = 8

    @property
    def cache_db(self) -> Path:
        return self.home / "cache.db"

    @property
    def pages_dir(self) -> Path:
        return self.home / "pages"

    @property
    def crawls_dir(self) -> Path:
        return self.home / "crawls"


def get_settings() -> Settings:
    """Build settings from environment. Read fresh each call so tests and overrides are simple."""
    return Settings(
        home=Path(os.environ.get("TEARSHEET_HOME", str(Path.home() / ".tearsheet"))),
        user_agent=os.environ.get("TEARSHEET_UA", DEFAULT_UA),
        page_ttl_seconds=int(os.environ.get("TEARSHEET_TTL", 7 * 24 * 3600)),
    )
