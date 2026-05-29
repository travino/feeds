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

# Google News RSS proxy, restricted to reuters.com articles from the last week.
# `allinurl:reuters.com` keeps results to Reuters' own domain; `when:7d` gives a
# healthy backlog even on slow news days. Combined with the local cache below,
# the feed accumulates a stable set of recent articles.
SOURCE_URL = (
    "https://news.google.com/rss/search"
    "?q=when:7d+allinurl:reuters.com"
    "&hl=en-US&gl=US&ceid=US:en"
)

# Cap the merged feed so the committed XML stays a reasonable size.
MAX_ENTRIES = 100


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
    try:
        xml_content = fetch_page(SOURCE_URL)
    except Exception as e:
        logger.error(f"Failed to fetch source feed: {e}")
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
    main(full=args.full)
