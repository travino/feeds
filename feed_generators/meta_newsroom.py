"""Meta Newsroom feed generator.

Aggregates Meta's public blog streams into one **Atom** feed written to
``feeds/feed_meta_newsroom.xml``:

    - The Meta.com Blog   https://www.meta.com/blog/rss/      (native RSS)
    - Meta Newsroom       https://about.fb.com/feed/          (native RSS)
    - Engineering at Meta https://engineering.fb.com/feed/    (native RSS)
    - AI at Meta Blog     https://ai.meta.com/blog/           (no native feed;
          mirrored by Olshansk/rss-feeds, consumed from its raw GitHub XML)

Every source publishes (or is mirrored as) a usable RSS/Atom feed, so each is
parsed directly -- no scraping. The WhatsApp and Instagram blogs were
considered but excluded: both are JavaScript-rendered Facebook shells with no
native feed and no static article markup to parse without a browser, and this
project has no Selenium.

Each source is fetched independently and wrapped so one failing source is
skipped, never fatal -- the feed is still built from whatever succeeded.
History accumulates across hourly runs via the shared JSON cache
(``cache/meta_newsroom_posts.json``).
"""

import argparse
import re
import sys
import time

import pytz
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from feedgen.feed import FeedGenerator

from utils import (
    DEFAULT_HEADERS,
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

FEED_NAME = "meta_newsroom"
BLOG_URL = "https://about.fb.com/news/"

# Native RSS / Atom feeds (and one mirror) -- parsed directly, no scraping.
NATIVE_FEEDS = [
    ("The Meta.com Blog", "https://www.meta.com/blog/rss/"),
    ("Meta Newsroom", "https://about.fb.com/feed/"),
    ("Engineering at Meta", "https://engineering.fb.com/feed/"),
    # ai.meta.com/blog/ has no native feed; consume the Olshansk mirror.
    ("AI at Meta", "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_meta_ai.xml"),
]

# Cap the merged feed so the committed XML stays a reasonable size.
MAX_ENTRIES = 100


def parse_date(date_str):
    """Parse a date string into a UTC datetime, or None on failure."""
    if not date_str:
        return None
    try:
        dt = date_parser.parse(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.UTC)
        return dt.astimezone(pytz.UTC)
    except (ValueError, TypeError, OverflowError) as e:
        logger.warning(f"Could not parse date '{date_str}': {e}")
        return None


def fetch_text(url, retries=3, backoff=2.0, headers=None):
    """Fetch a URL's text body with retries; return None on failure (never raise).

    meta.com sits behind TLS-fingerprint filtering and 400s a plain requests
    User-Agent, so try curl_cffi Chrome impersonation first when available and
    fall back to the shared fetch_page otherwise.
    """
    try:
        from curl_cffi import requests as creq
    except ImportError:
        creq = None

    for attempt in range(1, retries + 1):
        try:
            if creq is not None:
                resp = creq.get(url, impersonate="chrome", timeout=30, headers=headers)
                resp.raise_for_status()
                return resp.text
            return fetch_page(url, headers=headers)
        except Exception as e:
            logger.warning(f"Fetch failed for {url} (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(backoff * attempt)
    return None


def clean_description(html, fallback=""):
    """Strip HTML to a plain-text summary, sanitized and length-capped."""
    if not html:
        return sanitize_xml(fallback)
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 500:
        text = text[:497].rstrip() + "..."
    return sanitize_xml(text or fallback)


def parse_native_feed(xml, label):
    """Parse an RSS 2.0 or Atom feed into entry dicts. Handles both shapes."""
    entries = []
    soup = BeautifulSoup(xml, "xml")
    items = soup.find_all("item") or soup.find_all("entry")
    for item in items:
        try:
            title_el = item.find("title")
            title = sanitize_xml(title_el.get_text(strip=True)) if title_el else None

            # RSS <link> carries the URL as text; Atom <link> carries it in href.
            link = None
            link_el = item.find("link")
            if link_el is not None:
                link = (link_el.get_text(strip=True) or link_el.get("href") or "").strip()
            if not link:
                for la in item.find_all("link"):
                    if la.get("rel") in (None, "alternate") and la.get("href"):
                        link = la["href"].strip()
                        break
            if not title or not link:
                continue

            date_el = (
                item.find("pubDate")
                or item.find("published")
                or item.find("updated")
                or item.find("date")
            )
            date_obj = parse_date(date_el.get_text(strip=True)) if date_el else None

            desc_el = (
                item.find("description")
                or item.find("summary")
                or item.find("encoded")
                or item.find("content")
            )
            description = clean_description(desc_el.get_text() if desc_el else "", fallback=title)

            entries.append({
                "title": title,
                "link": link,
                "date": date_obj,
                "description": description,
                "source": label,
            })
        except Exception as e:
            logger.warning(f"[{label}] skipped a malformed item: {e}")
    logger.info(f"[{label}] parsed {len(entries)} entries")
    return entries


def collect_native_feed(label, url):
    xml = fetch_text(url, headers={**DEFAULT_HEADERS, "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8"})
    if not xml:
        logger.warning(f"[{label}] fetch failed -- skipping this source")
        return []
    return parse_native_feed(xml, label)


def collect_all():
    """Collect entries from every source. A failure in one source is logged and
    skipped so the others still contribute."""
    entries = []
    for label, url in NATIVE_FEEDS:
        logger.info(f"Fetching native feed: {label}")
        try:
            entries += collect_native_feed(label, url)
        except Exception as e:
            logger.warning(f"[{label}] unexpected error: {e}")
    return entries


def generate_atom_feed(articles, feed_name=FEED_NAME):
    """Build an Atom FeedGenerator from the merged article list."""
    fg = FeedGenerator()
    fg.id(f"{BLOG_URL}#{feed_name}")
    fg.title("Meta Newsroom")
    fg.subtitle("Meta news, engineering, and AI blogs -- Meta.com, About Meta, Engineering at Meta, and AI at Meta -- in one feed.")
    setup_feed_links(fg, BLOG_URL, feed_name)
    fg.language("en")
    fg.author({"name": "Meta"})

    for article in articles:
        fe = fg.add_entry()
        fe.id(article["link"])
        fe.title(article["title"])
        fe.link(href=article["link"])
        source = article.get("source")
        if source:
            fe.category(term=source, label=source)
        fe.description(article.get("description") or article["title"])
        if article.get("date"):
            fe.published(article["date"])
            fe.updated(article["date"])

    logger.info("Generated Atom feed")
    return fg


def save_atom_feed(fg, feed_name=FEED_NAME):
    """Write the feed to feeds/feed_<name>.xml in Atom format."""
    output_file = get_feeds_dir() / f"feed_{feed_name}.xml"
    fg.atom_file(str(output_file), pretty=True)
    logger.info(f"Saved Atom feed to {output_file}")
    return output_file


def main(full=False):
    """Collect every source, merge with cache, and write the Atom feed."""
    if full:
        logger.info("Full reset requested -- ignoring existing cache")
        cached = []
    else:
        cache = load_cache(FEED_NAME)
        cached = deserialize_entries(cache.get("entries", []), date_field="date")

    new_articles = collect_all()

    if not new_articles and not cached:
        logger.warning("No articles collected -- skipping write to avoid an empty feed")
        return False

    merged = merge_entries(new_articles, cached, id_field="link", date_field="date")
    merged = sort_posts_for_feed(merged, date_field="date")

    save_cache(FEED_NAME, merged)

    feed_items = merged[-MAX_ENTRIES:] if len(merged) > MAX_ENTRIES else merged

    fg = generate_atom_feed(feed_items)
    save_atom_feed(fg)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the Meta Newsroom Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
