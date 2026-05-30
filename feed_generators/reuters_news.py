"""Reuters news feed generator.

Reuters discontinued its public RSS feeds in 2020, and reuters.com is behind
aggressive bot protection that returns HTTP 403 to automated requests (so a
direct HTML scraper is not viable in CI). The reliable, widely used workaround
is the Google News RSS proxy, which aggregates recent reuters.com articles into
a stable XML feed.

This generator fetches that proxy, normalizes the entries, merges them with a
local cache so history accumulates across hourly runs, and writes an **Atom**
feed to ``feeds/feed_reuters.xml``.
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

FEED_NAME = "reuters"
BLOG_URL = "https://www.reuters.com/"

# Google News RSS proxies, restricted to reuters.com articles. `allinurl:` keeps
# results to Reuters' own domain. We try a few query variants in order so a
# transient block or empty window on one doesn't sink the whole run.
SOURCE_URLS = [
    "https://news.google.com/rss/search?q=when:7d+allinurl:reuters.com&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=when:7d+site:reuters.com&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=reuters.com&hl=en-US&gl=US&ceid=US:en",
]

# Browser-like headers — Google News is more permissive with these than a bare
# request, which matters on shared/datacenter IPs such as CI runners.
FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Cap the merged feed so the committed XML stays a reasonable size.
MAX_ENTRIES = 100


def fetch_source(retries: int = 3, backoff: float = 2.0):
    """Fetch the first source URL that returns parseable items.

    Tries each URL in SOURCE_URLS, retrying transient failures. Returns the XML
    body of the first response that yields at least one <item>, else None.
    """
    for url in SOURCE_URLS:
        for attempt in range(1, retries + 1):
            try:
                xml = fetch_page(url, headers=FETCH_HEADERS)
                if "<item>" in xml:
                    logger.info(f"Fetched source: {url}")
                    return xml
                logger.warning(f"No <item> elements from {url} (attempt {attempt})")
            except Exception as e:
                logger.warning(f"Fetch failed for {url} (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(backoff * attempt)
    return None



def parse_date(date_str):
    """Parse a Google News RFC-822 pubDate into a UTC datetime."""
    try:
        dt = date_parser.parse(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.UTC)
        return dt.astimezone(pytz.UTC)
    except (ValueError, TypeError, OverflowError) as e:
        logger.warning(f"Could not parse date '{date_str}': {e}")
        return None


def parse_feed(xml_content):
    """Parse the Google News RSS XML into a list of article dicts."""
    soup = BeautifulSoup(xml_content, "xml")
    articles = []
    seen_links = set()

    for item in soup.find_all("item"):
        try:
            title_el = item.find("title")
            link_el = item.find("link")
            if not title_el or not link_el:
                continue

            title = sanitize_xml(title_el.get_text(strip=True))
            link = link_el.get_text(strip=True)
            if not title or not link or link in seen_links:
                continue
            seen_links.add(link)

            # Google News appends " - Reuters" to titles; strip the trailing
            # source suffix for a cleaner headline.
            source_el = item.find("source")
            source_name = source_el.get_text(strip=True) if source_el else "Reuters"
            if source_name and title.endswith(f" - {source_name}"):
                title = title[: -len(f" - {source_name}")].strip()

            pub_el = item.find("pubDate")
            date_obj = parse_date(pub_el.get_text(strip=True)) if pub_el else None

            desc_el = item.find("description")
            description = sanitize_xml(desc_el.get_text(strip=True)) if desc_el else title

            articles.append(
                {
                    "title": title,
                    "link": link,
                    "date": date_obj,
                    "description": description or title,
                    "source": source_name or "Reuters",
                }
            )
        except Exception as e:  # never let one bad item kill the run
            logger.warning(f"Skipping malformed item: {e}")
            continue

    logger.info(f"Parsed {len(articles)} articles from source feed")
    return articles


def generate_atom_feed(articles, feed_name=FEED_NAME):
    """Build an Atom FeedGenerator from the article list."""
    fg = FeedGenerator()
    fg.id(f"https://www.reuters.com/{feed_name}")
    fg.title("Reuters | Breaking International News & Views")
    fg.subtitle("Recent Reuters articles, aggregated via Google News")
    setup_feed_links(fg, BLOG_URL, feed_name)
    fg.language("en")
    fg.author({"name": "Reuters"})

    for article in articles:
        fe = fg.add_entry()
        fe.id(article["link"])
        fe.title(article["title"])
        fe.link(href=article["link"])
        fe.description(article["description"])
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
    """Fetch the source feed, merge with cache, and write the Atom feed."""
    xml_content = fetch_source()
    if xml_content is None:
        logger.error(
            "Could not fetch any source feed (all URLs failed or returned no items). "
            "Google News RSS sometimes blocks shared/datacenter IPs with HTTP 403."
        )
        return False

    new_articles = parse_feed(xml_content)
    if not new_articles:
        logger.warning("No articles parsed — skipping write to avoid an empty feed")
        return False

    if full:
        logger.info("Full reset requested — ignoring existing cache")
        cached = []
    else:
        cache = load_cache(FEED_NAME)
        cached = deserialize_entries(cache.get("entries", []), date_field="date")

    merged = merge_entries(new_articles, cached, id_field="link", date_field="date")
    merged = sort_posts_for_feed(merged, date_field="date")

    # Keep only the newest MAX_ENTRIES. sort_posts_for_feed returns ascending
    # (oldest first, since feedgen reverses on write), so keep the tail.
    if len(merged) > MAX_ENTRIES:
        merged = merged[-MAX_ENTRIES:]

    save_cache(FEED_NAME, merged)

    fg = generate_atom_feed(merged)
    save_atom_feed(fg)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the Reuters Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
