"""Nexus Mods news feed generator.

Nexus Mods has no native feed for its news section and sits behind Cloudflare,
which returns HTTP 403 to plain ``requests``. The news listing is, however,
fully server-rendered (the article cards are present in the initial HTML), so
no browser/JS execution is needed: ``curl_cffi`` impersonating a real Chrome TLS
fingerprint clears the bot check and returns the same HTML a browser would.

This generator fetches the listing page(s), parses the ``div.tile-content``
article cards (title, link, date, author, category, summary), merges them with a
local cache so history accumulates across hourly runs, and writes an RSS feed to
``feeds/feed_nexusmods_news.xml``.

The page paginates with ``?page=N``; incremental runs fetch only page 1 and
merge, while ``--full`` walks several pages to backfill the archive.
"""

import argparse
import time
from datetime import datetime

import pytz
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

from utils import (
    deserialize_entries,
    load_cache,
    merge_entries,
    sanitize_xml,
    save_cache,
    save_rss_feed,
    setup_feed_links,
    setup_logging,
    sort_posts_for_feed,
    stable_fallback_date,
)

logger = setup_logging()

FEED_NAME = "nexusmods_news"
BLOG_URL = "https://www.nexusmods.com/news"
BASE_URL = "https://www.nexusmods.com"

# datetime attribute on the <time> tag is the most reliable; visible text is a
# fallback ("21 May 2026").
DATE_FORMATS = [
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%d %B %Y",
    "%d %b %Y",
]


def fetch_listing(page: int, retries: int = 3, backoff: float = 2.0) -> str | None:
    """Fetch a single news listing page.

    Nexus Mods 403s plain requests; ``curl_cffi`` impersonates a real Chrome TLS
    fingerprint and gets through. We fall back to the shared ``fetch_page`` only
    if curl_cffi isn't installed (which will likely 403, but keeps the import
    non-fatal).
    """
    url = f"{BLOG_URL}?page={page}"
    try:
        from curl_cffi import requests as creq
    except ImportError:
        logger.warning("curl_cffi not installed; falling back to plain requests (likely 403)")
        from utils import fetch_page

        try:
            return fetch_page(url)
        except Exception as e:
            logger.error(f"Fallback fetch failed: {e}")
            return None

    for attempt in range(1, retries + 1):
        try:
            resp = creq.get(url, impersonate="chrome", timeout=30)
            if resp.status_code == 200 and "tile-content" in resp.text:
                logger.info(f"Fetched page {page} ({len(resp.text)} bytes)")
                return resp.text
            logger.warning(f"Unexpected response (status {resp.status_code}) for page {page} on attempt {attempt}")
        except Exception as e:
            logger.warning(f"Fetch failed for page {page} (attempt {attempt}/{retries}): {e}")
        if attempt < retries:
            time.sleep(backoff * attempt)
    return None


def parse_date(card) -> datetime | None:
    """Extract a timezone-aware datetime from a tile card's <time> element."""
    time_elem = card.select_one("time")
    if not time_elem:
        return None
    candidates = []
    if time_elem.get("datetime"):
        candidates.append(time_elem["datetime"].strip())
    if time_elem.get_text(strip=True):
        candidates.append(time_elem.get_text(strip=True))
    for text in candidates:
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=pytz.UTC)
            except ValueError:
                continue
    return None


def extract_category(card) -> str:
    """Find the news category for a card, falling back to 'News'."""
    node = card
    for _ in range(4):
        node = node.parent
        if node is None:
            break
        cat = node.select_one("a.post-category")
        if cat:
            return (cat.get("title") or cat.get_text(strip=True) or "News").strip()
    return "News"


def parse_posts(html_pages) -> list[dict]:
    """Parse rendered HTML page(s) and extract article dicts."""
    if isinstance(html_pages, str):
        html_pages = [html_pages]

    posts = []
    seen_links = set()

    for html in html_pages:
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for card in soup.select("div.tile-content"):
            try:
                link_elem = card.select_one("p.tile-name a[href]")
                if not link_elem:
                    continue
                href = link_elem.get("href", "").strip()
                link = href if href.startswith("http") else BASE_URL + href
                if "/news/" not in link or link in seen_links:
                    continue
                seen_links.add(link)

                title = link_elem.get_text(strip=True)
                if not title:
                    continue

                date = parse_date(card)
                if not date:
                    logger.warning(f"Could not parse date for: {title}")
                    date = stable_fallback_date(link)

                desc_elem = card.select_one("p.desc")
                description = desc_elem.get_text(" ", strip=True) if desc_elem else title

                author_elem = card.select_one("div.author a, .author a")
                author = author_elem.get_text(strip=True) if author_elem else "Nexus Mods"

                posts.append(
                    {
                        "title": sanitize_xml(title),
                        "link": link,
                        "description": sanitize_xml(description),
                        "date": date,
                        "category": sanitize_xml(extract_category(card)),
                        "author": sanitize_xml(author),
                    }
                )
            except Exception as exc:  # never let one bad card crash the run
                logger.warning("Skipping malformed card: %s", exc)
                continue

    logger.info("Parsed %d articles from listing", len(posts))
    return posts


def generate_rss_feed(posts: list[dict]) -> FeedGenerator:
    fg = FeedGenerator()
    fg.title("Nexus Mods News")
    fg.description("Latest news and updates from Nexus Mods and the modding community")
    fg.language("en")
    fg.author({"name": "Nexus Mods"})
    fg.logo("https://www.nexusmods.com/assets/images/default/avatar.png")
    fg.subtitle("Site news, competitions, and interviews from Nexus Mods")
    setup_feed_links(fg, blog_url=BLOG_URL, feed_name=FEED_NAME)

    for post in posts:
        fe = fg.add_entry()
        fe.title(post["title"])
        fe.description(post["description"])
        fe.link(href=post["link"])
        fe.id(post["link"])
        fe.author({"name": post.get("author", "Nexus Mods")})
        if post.get("category"):
            fe.category(term=post["category"])
        if post.get("date"):
            fe.published(post["date"])

    logger.info("Generated RSS feed with %d entries", len(posts))
    return fg


def main(full_reset: bool = False, full_pages: int = 15) -> bool:
    cache = load_cache(FEED_NAME)
    cached_entries = deserialize_entries(cache.get("entries", []))

    if full_reset or not cached_entries:
        mode = "full reset" if full_reset else "no cache exists"
        logger.info("Running full fetch (%s)", mode)
        html_pages = []
        for page in range(1, full_pages + 1):
            html = fetch_listing(page)
            if not html or "tile-content" not in html:
                logger.info("No more articles after page %d; stopping pagination", page - 1)
                break
            html_pages.append(html)
        new_posts = parse_posts(html_pages)
        posts = sort_posts_for_feed(new_posts, date_field="date")
    else:
        logger.info("Running incremental update (first page only)")
        html = fetch_listing(1)
        new_posts = parse_posts(html)
        posts = merge_entries(new_posts, cached_entries)

    if not posts:
        logger.warning("No posts fetched — skipping feed update to avoid overwriting with empty feed")
        return False

    save_cache(FEED_NAME, posts)
    feed = generate_rss_feed(posts)
    save_rss_feed(feed, FEED_NAME)
    logger.info("Done!")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Nexus Mods News RSS feed")
    parser.add_argument("--full", action="store_true", help="Force full reset (paginate the archive)")
    parser.add_argument("--pages", type=int, default=15, help="Max pages to fetch on a full reset")
    args = parser.parse_args()
    main(full_reset=args.full, full_pages=args.pages)
