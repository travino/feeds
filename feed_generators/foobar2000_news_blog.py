#!/usr/bin/env python3
"""Atom feed generator for foobar2000: News (https://www.foobar2000.org/news).

The site exposes no native RSS/Atom feed (no <link rel="alternate"> in <head>,
and /feed, /rss.xml, /atom.xml etc. all 404). It is a static, server-rendered
page: the whole news history sits in one document as a flat run of
``<h3>YYYY-MM-DD</h3>`` date headings, each followed by one or more ``<p>``
blocks of content until the next date heading.

Because posts have neither titles nor per-post URLs (every link points back at
``/news``), each entry gets:

* a synthesized title  -> date + first sentence of the body
* a stable id          -> ``{BLOG_URL}#{date}-{n}`` (n disambiguates same-day posts)

The page shows the full archive every time, but a rolling JSON cache is still
kept so ids stay stable and history survives if the page ever truncates. Run
on a schedule (e.g. hourly).

Usage:
    python foobar2000_news_blog.py              # fetch live page, merge into cache
    python foobar2000_news_blog.py page.html    # build from a local saved HTML file
    python foobar2000_news_blog.py --full       # ignore cache, rebuild from page only

Output:
    feeds/feed_foobar2000_news.xml      # generated Atom feed (rolling archive)
    cache/foobar2000_news_posts.json    # entry cache (source of truth for history)
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
FEED_NAME = "foobar2000_news"
BLOG_URL = "https://www.foobar2000.org/news"
BASE_URL = "https://www.foobar2000.org"
FEED_TITLE = "foobar2000: News"
FEED_DESC = "News and release announcements from foobar2000.org"
FEED_LANG = "en"

ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT_DIR / "feeds"
OUTPUT_FILE = OUTPUT_DIR / f"feed_{FEED_NAME}.xml"
CACHE_DIR = ROOT_DIR / "cache"
CACHE_FILE = CACHE_DIR / f"{FEED_NAME}_posts.json"

# Keep at most this many entries in the rolling archive.
MAX_ENTRIES = 300

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# News date headings look exactly like "2026-02-24".
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TITLE_LEN = 100  # cap synthesized titles


def setup_logging() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger(FEED_NAME)


log = setup_logging()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def fetch_page(url: str) -> str:
    log.info("Fetching %s", url)
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def parse_date(date_text: str) -> datetime:
    """Parse a YYYY-MM-DD heading; fall back to 'now' on failure."""
    date_text = (date_text or "").strip()
    with contextlib.suppress(ValueError):
        return datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    log.warning("Unparseable date %r, using current time", date_text)
    return datetime.now(timezone.utc)


def _synth_title(date_text: str, body_text: str) -> str:
    """Build a readable title from the date and the first sentence of the body."""
    first = re.split(r"(?<=[.!?])\s+", body_text.strip(), maxsplit=1)[0] if body_text else ""
    first = first.strip()
    if len(first) > _TITLE_LEN:
        first = first[: _TITLE_LEN - 1].rstrip() + "\u2026"
    return f"{date_text}: {first}" if first else date_text


# --------------------------------------------------------------------------- #
# Cache (rolling archive)
# --------------------------------------------------------------------------- #
def load_cache() -> list[dict]:
    """Load previously seen entries. Returns [] if no cache yet."""
    if not CACHE_FILE.exists():
        return []
    try:
        raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not read cache (%s); starting fresh", exc)
        return []
    entries = []
    for e in raw:
        with contextlib.suppress(Exception):
            e["published"] = datetime.fromisoformat(e["published"])
            entries.append(e)
    log.info("Loaded %d cached entries", len(entries))
    return entries


def save_cache(entries: list[dict]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    serializable = [{**e, "published": e["published"].isoformat()} for e in entries]
    CACHE_FILE.write_text(
        json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("Saved %d entries to cache", len(entries))


def merge_entries(existing: list[dict], new: list[dict]) -> list[dict]:
    """Merge new scraped entries into the archive, deduped by id.

    Newly scraped data wins for an id already present (refreshes metadata),
    while previously seen entries no longer on the page are kept. Result is
    sorted newest-first and capped at MAX_ENTRIES.
    """
    by_id: dict[str, dict] = {e["id"]: e for e in existing}
    before = len(by_id)
    for e in new:
        by_id[e["id"]] = e
    added = len(by_id) - before
    merged = sorted(by_id.values(), key=lambda x: x["published"], reverse=True)
    if len(merged) > MAX_ENTRIES:
        merged = merged[:MAX_ENTRIES]
    log.info("Merge: %d new, %d total (capped at %d)", added, len(merged), MAX_ENTRIES)
    return merged


# --------------------------------------------------------------------------- #
# Scraping
# --------------------------------------------------------------------------- #
def extract_articles(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    headings = [h for h in soup.find_all("h3") if _DATE_RE.match(h.get_text(strip=True))]
    log.info("Found %d dated news entries", len(headings))

    results: list[dict] = []
    per_date_count: dict[str, int] = {}

    for h in headings:
        try:
            date_text = h.get_text(strip=True)

            # Collect sibling content up to the next date heading.
            blocks = []
            for sib in h.find_next_siblings():
                if getattr(sib, "name", None) == "h3" and _DATE_RE.match(
                    sib.get_text(strip=True)
                ):
                    break
                if getattr(sib, "name", None):
                    blocks.append(sib)

            text = " ".join(b.get_text(" ", strip=True) for b in blocks).strip()
            html_parts = "".join(str(b) for b in blocks)

            # Absolutize relative links (/download -> https://www.foobar2000.org/download).
            frag = BeautifulSoup(html_parts, "html.parser")
            for a in frag.find_all("a", href=True):
                a["href"] = urljoin(BASE_URL + "/", a["href"])
            summary = str(frag) or text

            published = parse_date(date_text)

            # Disambiguate multiple posts sharing a date (the page has a few).
            n = per_date_count.get(date_text, 0)
            per_date_count[date_text] = n + 1
            entry_id = f"{BLOG_URL}#{date_text}" + (f"-{n}" if n else "")

            results.append(
                {
                    "id": entry_id,
                    "title": _synth_title(date_text, text),
                    "link": BLOG_URL,
                    "summary": summary,
                    "published": published,
                }
            )
        except Exception as exc:  # never let one bad block kill the run
            log.warning("Skipping a news entry due to error: %s", exc)
            continue

    results.sort(key=lambda x: x["published"], reverse=True)
    return results


# --------------------------------------------------------------------------- #
# Feed
# --------------------------------------------------------------------------- #
def build_feed(articles: list[dict]) -> bytes:
    fg = FeedGenerator()
    fg.id(BLOG_URL)
    fg.title(FEED_TITLE)
    fg.subtitle(FEED_DESC)
    fg.link(href=BLOG_URL, rel="alternate")
    fg.link(
        href=f"https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_{FEED_NAME}.xml",
        rel="self",
    )
    fg.language(FEED_LANG)
    fg.updated(datetime.now(timezone.utc))
    fg.generator("travino-feeds foobar2000_news_blog.py")

    # feedgen prepends entries, so add oldest-first to keep newest at the top.
    for art in reversed(articles):
        fe = fg.add_entry()
        fe.id(art["id"])
        fe.title(art["title"])
        fe.link(href=art["link"], rel="alternate")
        fe.updated(art["published"])
        fe.published(art["published"])
        fe.content(art["summary"], type="html")

    return fg.atom_str(pretty=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Atom feed for foobar2000: News")
    parser.add_argument("html_file", nargs="?", help="Optional local HTML file")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Ignore the cache and rebuild the feed from the current page only",
    )
    args = parser.parse_args()

    if args.html_file:
        log.info("Reading local file %s", args.html_file)
        html = Path(args.html_file).read_text(encoding="utf-8", errors="replace")
    else:
        html = fetch_page(BLOG_URL)

    scraped = extract_articles(html)
    if not scraped:
        log.error("No articles extracted; aborting without overwriting feed.")
        return 1

    existing = [] if args.full else load_cache()
    entries = merge_entries(existing, scraped)
    save_cache(entries)

    atom_bytes = build_feed(entries)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_bytes(atom_bytes)
    log.info("Wrote %d entries to %s", len(entries), OUTPUT_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
