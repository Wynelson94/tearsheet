"""SQLite page/robots cache: WAL mode, TTL reads, playwright entries beat httpx."""

import sqlite3
import time
import zlib
from dataclasses import dataclass
from pathlib import Path

from tearsheet.urls import url_hash

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
  url_hash      TEXT PRIMARY KEY,
  url           TEXT NOT NULL,
  final_url     TEXT,
  fetched_at    INTEGER NOT NULL,
  status        INTEGER,
  content_type  TEXT,
  via           TEXT NOT NULL,
  html          BLOB,
  markdown      TEXT,
  title         TEXT,
  etag          TEXT,
  last_modified TEXT
);
CREATE INDEX IF NOT EXISTS idx_pages_fetched ON pages(fetched_at);
CREATE TABLE IF NOT EXISTS robots (
  host        TEXT PRIMARY KEY,
  fetched_at  INTEGER NOT NULL,
  body        TEXT,
  crawl_delay REAL
);
CREATE TABLE IF NOT EXISTS crawls (
  crawl_id   TEXT PRIMARY KEY,
  root_url   TEXT,
  started_at INTEGER,
  pages      INTEGER,
  output_dir TEXT
);
"""


@dataclass
class CachedPage:
    url: str
    final_url: str
    fetched_at: int
    status: int
    content_type: str
    via: str
    html: bytes | None
    markdown: str | None
    title: str | None
    etag: str | None = None
    last_modified: str | None = None


class Cache:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)

    def get_page(self, url: str, ttl_seconds: int, now: int | None = None) -> CachedPage | None:
        now = now if now is not None else int(time.time())
        row = self._conn.execute(
            "SELECT url, final_url, fetched_at, status, content_type, via, html, markdown,"
            " title, etag, last_modified FROM pages WHERE url_hash = ? AND fetched_at > ?",
            (url_hash(url), now - ttl_seconds),
        ).fetchone()
        if row is None:
            return None
        return CachedPage(
            url=row[0],
            final_url=row[1],
            fetched_at=row[2],
            status=row[3],
            content_type=row[4],
            via=row[5],
            html=zlib.decompress(row[6]) if row[6] is not None else None,
            markdown=row[7],
            title=row[8],
            etag=row[9],
            last_modified=row[10],
        )

    def put_page(self, page: CachedPage, *, force: bool = False) -> None:
        """Store a page. `force=True` overrides the playwright-beats-httpx preference —
        used when the existing row was judged poisoned (wall cached as content) and the
        replacement, whatever its via, is strictly better than the poison."""
        h = url_hash(page.url)
        existing = self._conn.execute("SELECT via FROM pages WHERE url_hash = ?", (h,)).fetchone()
        if not force and existing and existing[0] == "playwright" and page.via != "playwright":
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO pages (url_hash, url, final_url, fetched_at, status,"
            " content_type, via, html, markdown, title, etag, last_modified)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                h,
                page.url,
                page.final_url,
                page.fetched_at,
                page.status,
                page.content_type,
                page.via,
                zlib.compress(page.html) if page.html is not None else None,
                page.markdown,
                page.title,
                page.etag,
                page.last_modified,
            ),
        )
        self._conn.commit()

    def get_robots(self, host: str, ttl_seconds: int) -> tuple[str, float | None] | None:
        row = self._conn.execute(
            "SELECT body, crawl_delay FROM robots WHERE host = ? AND fetched_at > ?",
            (host, int(time.time()) - ttl_seconds),
        ).fetchone()
        return (row[0], row[1]) if row is not None else None

    def put_robots(self, host: str, body: str, crawl_delay: float | None) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO robots (host, fetched_at, body, crawl_delay)"
            " VALUES (?, ?, ?, ?)",
            (host, int(time.time()), body, crawl_delay),
        )
        self._conn.commit()

    def prune(self, older_than_seconds: int) -> int:
        """Delete pages/robots entries older than the cutoff. Returns rows removed."""
        cutoff = int(time.time()) - older_than_seconds
        pages = self._conn.execute("DELETE FROM pages WHERE fetched_at <= ?", (cutoff,)).rowcount
        robots = self._conn.execute(
            "DELETE FROM robots WHERE fetched_at <= ?", (cutoff,)
        ).rowcount
        self._conn.commit()
        self._conn.execute("VACUUM")
        return pages + robots

    def stats(self) -> dict[str, int]:
        pages = self._conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        robots = self._conn.execute("SELECT COUNT(*) FROM robots").fetchone()[0]
        crawls = self._conn.execute("SELECT COUNT(*) FROM crawls").fetchone()[0]
        page_size, page_count = self._conn.execute(
            "SELECT page_size, page_count FROM pragma_page_size(), pragma_page_count()"
        ).fetchone()
        return {
            "pages": pages,
            "robots": robots,
            "crawls": crawls,
            "db_bytes": page_size * page_count,
        }

    def clear(self) -> None:
        for table in ("pages", "robots", "crawls"):
            self._conn.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed table names
        self._conn.commit()
        self._conn.execute("VACUUM")

    def log_crawl(
        self, crawl_id: str, root_url: str, started_at: int, pages: int, output_dir: str
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO crawls (crawl_id, root_url, started_at, pages, output_dir)"
            " VALUES (?, ?, ?, ?, ?)",
            (crawl_id, root_url, started_at, pages, output_dir),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
