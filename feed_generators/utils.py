"""Shared utilities for feed generators.

A trimmed, self-contained version: HTTP fetching, XML sanitization, a JSON
cache for incremental updates, and feedgen link helpers. No Selenium and no
external settings library — everything here depends only on requests, feedgen,
and pytz.
"""

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytz
import requests
from feedgen.feed import FeedGenerator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {"User-Agent": DEFAULT_USER_AGENT}

# Used to build the rel="self" link in each feed. In GitHub Actions,
# GITHUB_REPOSITORY ("owner/repo") is set automatically, so the self link is
# correct out of the box. Override locally with RSS_REPO_SLUG if needed.
REPO_SLUG = os.getenv("RSS_REPO_SLUG") or os.getenv("GITHUB_REPOSITORY") or "travino/feeds"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def setup_logging(name: str | None = None) -> logging.Logger:
    """Configure logging and return a logger. Call once: ``logger = setup_logging()``."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    if name is None:
        import inspect

        frame_info = inspect.stack()[1]
        frame = getattr(frame_info, "frame", frame_info[0])
        name = frame.f_globals.get("__name__", __name__)
    return logging.getLogger(name)


logger = setup_logging()

# ---------------------------------------------------------------------------
# Text sanitization
# ---------------------------------------------------------------------------

# XML 1.0 forbids NULL bytes and most C0/C1 control characters.
_INVALID_XML_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def sanitize_xml(text: str) -> str:
    """Strip characters that are invalid in XML 1.0 from *text*."""
    return _INVALID_XML_RE.sub("", text)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def get_project_root() -> Path:
    return Path(__file__).parent.parent


def get_cache_dir() -> Path:
    cache_dir = get_project_root() / "cache"
    cache_dir.mkdir(exist_ok=True)
    return cache_dir


def get_feeds_dir() -> Path:
    feeds_dir = get_project_root() / "feeds"
    feeds_dir.mkdir(exist_ok=True)
    return feeds_dir


def get_cache_file(feed_name: str) -> Path:
    return get_cache_dir() / f"{feed_name}_posts.json"


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def fetch_page(url: str, timeout: int = 30, headers: dict | None = None) -> str:
    """Fetch a URL and return its text body, raising on HTTP errors."""
    response = requests.get(url, headers=headers or DEFAULT_HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.text


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def stable_fallback_date(identifier: str) -> datetime:
    """Generate a stable date from a URL/title hash for dateless posts.

    Uses hashlib rather than the builtin hash(), which is salted per process
    (PYTHONHASHSEED) and would otherwise assign a different fallback date on
    every run — defeating the whole point of a *stable* fallback.
    """
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
    hash_val = int(digest, 16) % 730
    epoch = datetime(2023, 1, 1, 0, 0, 0, tzinfo=pytz.UTC)
    return epoch + timedelta(days=hash_val)


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------


def load_cache(feed_name: str, entries_key: str = "entries") -> dict:
    """Load existing cache or return an empty structure."""
    cache_file = get_cache_file(feed_name)
    if cache_file.exists():
        try:
            with open(cache_file) as f:
                data = json.load(f)
                logger.info(f"Loaded cache with {len(data.get(entries_key, []))} entries")
                return data
        except json.JSONDecodeError:
            logger.warning(f"Corrupted cache file {cache_file}, starting fresh")
    logger.info("No cache file found, will do full fetch")
    return {"last_updated": None, entries_key: []}


def save_cache(feed_name: str, entries: list[dict], entries_key: str = "entries") -> None:
    """Save entries to the cache file, serializing datetimes to ISO strings."""
    cache_file = get_cache_file(feed_name)
    serializable = []
    for entry in entries:
        entry_copy = entry.copy()
        for key, value in entry_copy.items():
            if isinstance(value, datetime):
                entry_copy[key] = value.isoformat()
        serializable.append(entry_copy)

    data = {"last_updated": datetime.now(pytz.UTC).isoformat(), entries_key: serializable}
    with open(cache_file, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved cache with {len(entries)} entries to {cache_file}")


def deserialize_entries(entries: list[dict], date_field: str = "date") -> list[dict]:
    """Convert cached ISO date strings back to datetime objects."""
    result = []
    for entry in entries:
        entry_copy = entry.copy()
        if isinstance(entry_copy.get(date_field), str):
            try:
                entry_copy[date_field] = datetime.fromisoformat(entry_copy[date_field])
            except ValueError:
                entry_copy[date_field] = stable_fallback_date(entry_copy.get("link", ""))
        result.append(entry_copy)
    return result


def merge_entries(
    new_entries: list[dict],
    cached_entries: list[dict],
    id_field: str = "link",
    date_field: str = "date",
) -> list[dict]:
    """Merge new entries into the cache, deduplicate by id_field, and sort."""
    existing_ids = {e[id_field] for e in cached_entries}
    merged = list(cached_entries)

    added = 0
    for entry in new_entries:
        if entry[id_field] not in existing_ids:
            merged.append(entry)
            existing_ids.add(entry[id_field])
            added += 1

    logger.info(f"Added {added} new entries to cache")
    return sort_posts_for_feed(merged, date_field=date_field)


# ---------------------------------------------------------------------------
# Feed generation
# ---------------------------------------------------------------------------


def setup_feed_links(fg: FeedGenerator, blog_url: str, feed_name: str) -> None:
    """Set feed links so <link rel="self"> points to the raw feed and the main
    link points to the source site.

    feedgen requires rel="self" be set first and rel="alternate" last.
    """
    fg.link(
        href=f"https://raw.githubusercontent.com/{REPO_SLUG}/main/feeds/feed_{feed_name}.xml",
        rel="self",
    )
    fg.link(href=blog_url, rel="alternate")


def sort_posts_for_feed(posts: list[dict[str, Any]], date_field: str = "date") -> list[dict[str, Any]]:
    """Sort newest-last (ascending). feedgen reverses on write, so the final
    feed is newest-first. Dateless posts are placed at the end."""
    with_date = [p for p in posts if p.get(date_field) is not None]
    without_date = [p for p in posts if p.get(date_field) is None]
    with_date.sort(key=lambda x: x[date_field])
    return with_date + without_date


def save_atom_feed(fg: FeedGenerator, feed_name: str) -> Path:
    """Write an Atom feed to feeds/feed_<name>.xml (project default format)."""
    output_file = get_feeds_dir() / f"feed_{feed_name}.xml"
    fg.atom_file(str(output_file), pretty=True)
    logger.info(f"Saved Atom feed to {output_file}")
    return output_file


def save_rss_feed(fg: FeedGenerator, feed_name: str) -> Path:
    """Write an RSS 2.0 feed to feeds/feed_<name>.xml (for future RSS feeds)."""
    output_file = get_feeds_dir() / f"feed_{feed_name}.xml"
    fg.rss_file(str(output_file), pretty=True)
    logger.info(f"Saved RSS feed to {output_file}")
    return output_file
