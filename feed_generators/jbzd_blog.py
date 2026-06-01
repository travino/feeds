#!/usr/bin/env python3
"""Atom feed generator for jbzd.com.pl ("najgorsze obrazki w internecie").

The site exposes no native RSS/Atom feed, so this scraper builds an Atom 1.0
feed from the homepage listing. It is a static (requests + BeautifulSoup) site.

The homepage only shows a handful of posts at a time, so each run is merged into
a rolling JSON cache. The feed therefore accumulates history across runs instead
of being overwritten. Run it on a schedule (e.g. hourly) to keep the archive
growing.

Usage:
    python jbzd_blog.py                 # fetch live homepage, merge into cache
    python jbzd_blog.py page.html       # build from a local saved HTML file
    python jbzd_blog.py --full          # ignore cache, rebuild from scratch

Output:
    feeds/feed_jbzd.xml         # generated Atom feed (rolling archive)
    feeds/.cache/jbzd.json      # entry cache (source of truth for history)
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
FEED_NAME = "jbzd"
BLOG_URL = "https://jbzd.com.pl/"
FEED_TITLE = "Jbzd.com.pl - najgorsze obrazki w internecie!"
FEED_DESC = "Najnowsze obrazki, memy i humor z jbzd.com.pl"
FEED_LANG = "pl"

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "feeds"
OUTPUT_FILE = OUTPUT_DIR / f"feed_{FEED_NAME}.xml"
CACHE_DIR = OUTPUT_DIR / ".cache"
CACHE_FILE = CACHE_DIR / f"{FEED_NAME}.json"

# Keep at most this many entries in the rolling archive.
MAX_ENTRIES = 300

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S",  # 2026-06-01 08:13:19  (data-date attribute)
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
]


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
    """Parse the data-date attribute; fall back to 'now' on failure."""
    date_text = (date_text or "").strip()
    for fmt in DATE_FORMATS:
        with contextlib.suppress(ValueError):
            return datetime.strptime(date_text, fmt).replace(tzinfo=timezone.utc)
    log.warning("Unparseable date %r, using current time", date_text)
    return datetime.now(timezone.utc)


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
    serializable = [
        {**e, "published": e["published"].isoformat()} for e in entries
    ]
    CACHE_FILE.write_text(
        json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("Saved %d entries to cache", len(entries))


def merge_entries(existing: list[dict], new: list[dict]) -> list[dict]:
    """Merge new scraped entries into the archive, deduped by id.

    Newly scraped data wins for an id already present (refreshes metadata),
    while previously seen entries that are no longer on the homepage are kept.
    Result is sorted newest-first and capped at MAX_ENTRIES.
    """
    by_id: dict[str, dict] = {e["id"]: e for e in existing}
    before = len(by_id)
    for e in new:
        by_id[e["id"]] = e
    added = len(by_id) - before
    merged = sorted(by_id.values(), key=lambda x: x["published"], reverse=True)
    if len(merged) > MAX_ENTRIES:
        merged = merged[:MAX_ENTRIES]
    log.info(
        "Merge: %d new, %d total (capped at %d)", added, len(merged), MAX_ENTRIES
    )
    return merged


def extract_articles(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    articles = soup.select("article.article")
    log.info("Found %d article containers", len(articles))

    results: list[dict] = []
    seen: set[str] = set()

    for art in articles:
        try:
            title_a = art.select_one(".article-title h2 a")
            if not title_a:
                continue
            link = title_a.get("href", "").strip()
            title = title_a.get_text(strip=True)
            if not link or not title or link in seen:
                continue
            seen.add(link)

            # Stable unique id from the content id when available.
            content_id = art.get("data-content-id") or link

            # Date from the data-date attribute on .article-time.
            time_el = art.select_one(".article-time")
            published = parse_date(time_el.get("data-date") if time_el else "")

            # Categories.
            cats = [
                c.get_text(strip=True)
                for c in art.select(".article-category-parent, .article-category")
                if c.get_text(strip=True)
            ]

            # Lead image (if present).
            img = art.select_one(".article-image img, img.article-image")
            img_src = img.get("src").strip() if img and img.get("src") else None

            # Build a small HTML summary embedding the image.
            if img_src:
                summary = (
                    f'<p><a href="{link}">'
                    f'<img src="{img_src}" alt="{title}" /></a></p>'
                )
            else:
                summary = f'<p><a href="{link}">{title}</a></p>'

            results.append(
                {
                    "id": str(content_id),
                    "title": title,
                    "link": link,
                    "published": published,
                    "categories": cats,
                    "image": img_src,
                    "summary": summary,
                }
            )
        except Exception as exc:  # never let one bad item kill the run
            log.warning("Skipping an article due to error: %s", exc)
            continue

    # Newest first.
    results.sort(key=lambda x: x["published"], reverse=True)
    return results


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
    fg.generator("travino-feeds jbzd_blog.py")

    # feedgen prepends entries, so add oldest-first to keep newest at the top.
    for art in reversed(articles):
        fe = fg.add_entry()
        fe.id(art["id"])
        fe.title(art["title"])
        fe.link(href=art["link"], rel="alternate")
        fe.updated(art["published"])
        fe.published(art["published"])
        fe.content(art["summary"], type="html")
        for cat in art["categories"]:
            fe.category(term=cat)
        if art["image"]:
            # Enclosure-style link so readers can show the media.
            fe.link(href=art["image"], rel="enclosure", type="image/jpeg")

    return fg.atom_str(pretty=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Atom feed for jbzd.com.pl")
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
