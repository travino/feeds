"""OLX Group feed generator.

Aggregates the native RSS feeds published across the OLX Group's Polish
properties into a single Atom feed:

  * OLX Blog                 https://blog.olx.pl/feed/
  * OLX Zawodowo             https://www.olx.pl/zawodowo/feed/
  * OTOMOTO News             https://www.otomoto.pl/news/feed
  * Otodom – Wiadomości      https://www.otodom.pl/wiadomosci/feed/
  * Otodom – pressreleases   https://media.otodom.pl/feed

Each source already exposes a usable RSS 2.0 feed, so this generator does not
scrape HTML — it fetches each feed independently (per-source error isolation so
one failure never sinks the run), normalizes the items, tags them with their
source, merges into a local cache (dedup by article ``link``) so history
accumulates across hourly runs, and writes an **Atom** feed to
``feeds/feed_olx.xml``.

Note: ``media.otomoto.pl/feed`` is intentionally excluded — that host serves the
OTOMOTO single-page app rather than a feed, so there is nothing to parse there.
"""

import argparse
import sys
import time

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
)

logger = setup_logging()

FEED_NAME = "olx"
BLOG_URL = "https://www.olx.pl/"

# (source label, category, feed URL). The label is shown as the per-entry
# author/source; the category groups OLX vs OTOMOTO vs Otodom in readers.
SOURCES = [
    ("OLX Blog", "olx", "https://blog.olx.pl/feed/"),
    ("OLX Zawodowo", "olx", "https://www.olx.pl/zawodowo/feed/"),
    ("OTOMOTO News", "otomoto", "https://www.otomoto.pl/news/feed"),
    ("Otodom – Wiadomości", "otodom", "https://www.otodom.pl/wiadomosci/feed/"),
    ("Otodom – pressroom", "otodom", "https://media.otodom.pl/feed"),
]

FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}

# Cap the merged feed so the committed XML stays a reasonable size.
MAX_ENTRIES = 100


def fetch_feed(url, retries=3, backoff=2.0):
    """Fetch an RSS feed body, retrying transient failures. None on failure."""
    for attempt in range(1, retries + 1):
        try:
            xml = fetch_page(url, headers=FETCH_HEADERS)
            if "<item" in xml or "<entry" in xml:
                return xml
            logger.warning(f"No items in response from {url} (attempt {attempt})")
        except Exception as e:
            logger.warning(f"Fetch failed for {url} (attempt {attempt}/{retries}): {e}")
        if attempt < retries:
            time.sleep(backoff * attempt)
    return None


def parse_date(date_str):
    """Parse an RFC-822/ISO pubDate into a UTC datetime, or None."""
    try:
        dt = date_parser.parse(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.UTC)
        return dt.astimezone(pytz.UTC)
    except (ValueError, TypeError, OverflowError) as e:
        logger.warning(f"Could not parse date '{date_str}': {e}")
        return None


def parse_feed(xml_content, source_label, category):
    """Parse one RSS feed into normalized entry dicts."""
    soup = BeautifulSoup(xml_content, "xml")
    entries = []
    seen = set()

    for item in soup.find_all("item"):
        try:
            title_el = item.find("title")
            link_el = item.find("link")
            if not title_el or not link_el:
                continue

            title = sanitize_xml(title_el.get_text(strip=True))
            link = link_el.get_text(strip=True)
            if not title or not link or link in seen:
                continue
            seen.add(link)

            pub_el = item.find("pubDate") or item.find("published") or item.find("date")
            date_obj = parse_date(pub_el.get_text(strip=True)) if pub_el else None

            desc_el = item.find("description") or item.find("summary")
            description = sanitize_xml(desc_el.get_text(strip=True)) if desc_el else title

            entries.append(
                {
                    "title": title,
                    "link": link,
                    "date": date_obj,
                    "description": description or title,
                    "source": source_label,
                    "category": category,
                }
            )
        except Exception as e:  # never let one bad item kill the run
            logger.warning(f"[{source_label}] skipping malformed item: {e}")
            continue

    logger.info(f"[{source_label}] parsed {len(entries)} items")
    return entries


def collect_entries():
    """Fetch and normalize all sources. Per-source failures are logged and skipped."""
    entries = []
    for label, category, url in SOURCES:
        xml = fetch_feed(url)
        if xml is None:
            logger.warning(f"Source '{label}' unavailable; continuing")
            continue
        try:
            entries.extend(parse_feed(xml, label, category))
        except Exception as e:
            logger.warning(f"Source '{label}' parse failed ({e}); continuing")
    return entries


def generate_atom_feed(entries, feed_name=FEED_NAME):
    """Build an Atom FeedGenerator from the normalized entry list."""
    fg = FeedGenerator()
    fg.id(f"https://www.olx.pl/{feed_name}")
    fg.title("OLX Group – OLX, OTOMOTO & Otodom")
    fg.subtitle("Combined blog, news and press feeds from OLX, OTOMOTO and Otodom")
    setup_feed_links(fg, BLOG_URL, feed_name)
    fg.language("pl")
    fg.author({"name": "OLX Group"})

    for entry in entries:
        fe = fg.add_entry()
        fe.id(entry["link"])
        fe.title(entry["title"])
        fe.link(href=entry["link"])
        fe.description(entry["description"])
        if entry.get("category"):
            fe.category(term=entry["category"])
        if entry.get("source"):
            fe.author({"name": entry["source"]})
        if entry.get("date"):
            fe.published(entry["date"])
            fe.updated(entry["date"])

    logger.info("Generated Atom feed")
    return fg


def save_atom_feed(fg, feed_name=FEED_NAME):
    """Write the feed to feeds/feed_<name>.xml in Atom format."""
    output_file = get_feeds_dir() / f"feed_{feed_name}.xml"
    fg.atom_file(str(output_file), pretty=True)
    logger.info(f"Saved Atom feed to {output_file}")
    return output_file


def main(full=False):
    """Fetch all sources, merge with cache, and write the Atom feed."""
    new_entries = collect_entries()
    if not new_entries:
        logger.warning("No entries from any source — skipping write to preserve last good feed")
        return False

    if full:
        logger.info("Full reset requested — ignoring existing cache")
        cached = []
    else:
        cache = load_cache(FEED_NAME)
        cached = deserialize_entries(cache.get("entries", []), date_field="date")

    merged = merge_entries(new_entries, cached, id_field="link", date_field="date")
    merged = sort_posts_for_feed(merged, date_field="date")

    # Keep the newest MAX_ENTRIES. sort_posts_for_feed returns ascending
    # (oldest first; feedgen reverses on write), so keep the tail.
    if len(merged) > MAX_ENTRIES:
        merged = merged[-MAX_ENTRIES:]

    save_cache(FEED_NAME, merged)

    fg = generate_atom_feed(merged)
    save_atom_feed(fg)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the OLX Group Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
