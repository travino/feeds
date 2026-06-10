"""Common Ninja blog feed generator.

Common Ninja's blog (https://www.commoninja.com/blog) has no native RSS/Atom
feed, but the listing is fully server-rendered: each post is an
``a[href^="/blog/"]`` card carrying the title (``h3`` / ``title`` attribute),
a ``<time datetime>`` publish date, an author line, and a ``.desc`` summary.
A plain ``requests`` fetch is therefore enough — no JS execution needed.

Fetches the listing, parses the post cards, merges them with a local cache so
history accumulates across runs, and writes an **Atom** feed to
``feeds/feed_commoninja.xml``.
"""

import argparse
import sys
from urllib.parse import urljoin

import pytz
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from feedgen.feed import FeedGenerator

from utils import (
    deserialize_entries,
    fetch_page,
    get_feeds_dir,
    load_cache,
    merge_entries,
    sanitize_xml,
    save_cache,
    setup_feed_links,
    setup_logging,
    sort_posts_for_feed,
    stable_fallback_date,
)

logger = setup_logging()

FEED_NAME = "commoninja"
BLOG_URL = "https://www.commoninja.com/blog"
BASE_URL = "https://www.commoninja.com"
MAX_ENTRIES = 100


def fetch_listing() -> str | None:
    """Fetch the blog listing HTML, returning the body or None."""
    try:
        html = fetch_page(BLOG_URL)
        if html and "posts-container" in html:
            logger.info(f"Fetched listing ({len(html)} bytes)")
            return html
        logger.warning("Listing fetched but expected markup missing")
        return html
    except Exception as e:
        logger.error(f"Fetch failed: {e}")
        return None


def parse_items(html: str) -> list[dict]:
    """Parse post cards into feed-entry dicts.

    Skips category links (``/blog/category/...``) and wraps each card so one
    malformed item is skipped rather than aborting the run.
    """
    soup = BeautifulSoup(html, "lxml")
    entries: list[dict] = []
    seen: set[str] = set()

    for a in soup.select('a[href^="/blog/"]'):
        href = a.get("href", "")
        if not href or "/blog/category/" in href or href.rstrip("/") == "/blog":
            continue
        link = urljoin(BASE_URL, href)
        if link in seen:
            continue

        try:
            heading = a.find("h3")
            title = (heading.get_text(strip=True) if heading else a.get("title", "")).strip()
            if not title:
                continue

            time_tag = a.find("time")
            date = None
            if time_tag is not None:
                raw = time_tag.get("datetime") or time_tag.get_text(strip=True)
                if raw:
                    try:
                        dt = date_parser.parse(raw)
                        date = dt.astimezone(pytz.UTC) if dt.tzinfo else pytz.UTC.localize(dt)
                    except (ValueError, OverflowError):
                        date = None
            if date is None:
                date = stable_fallback_date(link)

            desc_tag = a.find(class_="desc")
            description = desc_tag.get_text(strip=True) if desc_tag else ""

            author_tag = a.find(class_="author")
            if author_tag:
                # The author line also contains the date; keep only the name.
                author = author_tag.get_text(" ", strip=True)
                if time_tag:
                    author = author.replace(time_tag.get_text(strip=True), "")
                author = author.strip().strip(",").strip()
                if author and description:
                    description = f"{description}\n\nBy {author}"
                elif author:
                    description = f"By {author}"

            seen.add(link)
            entries.append(
                {
                    "title": sanitize_xml(title),
                    "link": link,
                    "date": date,
                    "description": sanitize_xml(description),
                }
            )
        except Exception as e:  # never let one bad card kill the run
            logger.warning(f"Skipping malformed card ({href}): {e}")
            continue

    logger.info(f"Parsed {len(entries)} entries")
    return entries


def generate_atom_feed(entries, feed_name=FEED_NAME):
    fg = FeedGenerator()
    fg.id(f"{BLOG_URL}#{feed_name}")
    fg.title("Common Ninja Blog")
    fg.subtitle("Helpful, useful & informative articles from Common Ninja")
    setup_feed_links(fg, BLOG_URL, feed_name)
    fg.language("en")
    fg.author({"name": "Common Ninja"})

    for e in entries:
        fe = fg.add_entry()
        fe.id(e["link"])
        fe.title(e["title"])
        fe.link(href=e["link"])
        fe.description(e["description"])
        if e.get("date"):
            fe.published(e["date"])
            fe.updated(e["date"])

    logger.info("Generated Atom feed")
    return fg


def save_atom_feed(fg, feed_name=FEED_NAME):
    out = get_feeds_dir() / f"feed_{feed_name}.xml"
    fg.atom_file(str(out), pretty=True)
    logger.info(f"Saved Atom feed to {out}")
    return out


def main(full=False) -> bool:
    html = fetch_listing()
    if html is None:
        logger.error("Fetch failed — skipping write to preserve the last good feed")
        return False

    new_entries = parse_items(html)
    if not new_entries:
        logger.warning("No entries parsed — skipping write to avoid an empty feed")
        return False

    if full:
        logger.info("Full reset requested — ignoring existing cache")
        cached = []
    else:
        cached = deserialize_entries(load_cache(FEED_NAME).get("entries", []), date_field="date")

    merged = merge_entries(new_entries, cached, id_field="link", date_field="date")
    merged = sort_posts_for_feed(merged, date_field="date")
    if len(merged) > MAX_ENTRIES:
        merged = merged[-MAX_ENTRIES:]

    save_cache(FEED_NAME, merged)
    save_atom_feed(generate_atom_feed(merged))
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the Common Ninja blog Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
