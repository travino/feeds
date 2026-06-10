"""Canva Learn feed generator.

Canva's Learn hub (https://www.canva.com/learn/) has no native feed and sits
behind Cloudflare, which 403s plain ``requests``. It's a Next.js app whose
article list ships in the page's ``__NEXT_DATA__`` blob, so ``curl_cffi``
impersonating Chrome is enough — no browser/JS execution needed.

Unlike the newsroom, the Learn landing page is an **editorial topic hub**: the
listing JSON has no publish dates and the order is curated by section, not by
recency. So rather than re-emitting the same evergreen guides every run, this
generator follows the Beatport pattern and treats the feed as *"articles as
they first appear on the hub"*: each article is keyed by its URL and dated by
the moment it is first observed, so newly added Learn articles surface as fresh
feed items. The JSON cache accumulates that history and dedupes by URL.

Writes an **Atom** feed to ``feeds/feed_canva_learn.xml``.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta

import pytz
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

from utils import (
    deserialize_entries,
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

FEED_NAME = "canva_learn"
BLOG_URL = "https://www.canva.com/learn/"
ARTICLE_TMPL = "https://www.canva.com/learn/{slug}/"
MAX_ENTRIES = 200


def fetch_page_html(retries: int = 3, backoff: float = 2.0) -> str | None:
    """Fetch the Learn hub HTML via curl_cffi (Cloudflare 403s plain requests)."""
    try:
        from curl_cffi import requests as creq
    except ImportError:
        logger.warning("curl_cffi not installed; falling back to plain requests (likely 403)")
        from utils import fetch_page

        try:
            return fetch_page(BLOG_URL)
        except Exception as e:
            logger.error(f"Fallback fetch failed: {e}")
            return None

    for attempt in range(1, retries + 1):
        try:
            resp = creq.get(BLOG_URL, impersonate="chrome", timeout=30)
            if resp.status_code == 200 and "__NEXT_DATA__" in resp.text:
                logger.info(f"Fetched Learn hub ({len(resp.text)} bytes)")
                return resp.text
            logger.warning(f"Unexpected response (status {resp.status_code}) on attempt {attempt}")
        except Exception as e:
            logger.warning(f"Fetch failed (attempt {attempt}/{retries}): {e}")
        if attempt < retries:
            time.sleep(backoff * attempt)
    return None


def extract_articles(html: str) -> list[dict]:
    """Collect article objects from featuredPosts + every section's posts."""
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag is None or not tag.string:
        logger.error("__NEXT_DATA__ script not found — page layout may have changed")
        return []
    try:
        props = json.loads(tag.string)["props"]["pageProps"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error(f"Could not parse __NEXT_DATA__ structure: {e}")
        return []

    articles: list[dict] = []
    seen_slugs: set[str] = set()
    buckets = list(props.get("featuredPosts") or [])
    for section in props.get("sections") or []:
        buckets.extend(section.get("posts") or [])

    for art in buckets:
        slug = (art.get("slug") or "").strip()
        if slug and slug not in seen_slugs:
            seen_slugs.add(slug)
            articles.append(art)
    return articles


def build_entries(articles: list[dict], now: datetime) -> list[dict]:
    """Build feed-entry dicts, dating each article at first observation.

    Within a single run articles share the observation time; we subtract the
    listing position (in seconds) so the hub order is preserved as feed order
    on the first run. The cache keeps each article's original first-seen date
    afterwards, so only genuinely new articles appear as fresh items.
    """
    entries: list[dict] = []
    seen: set[str] = set()

    for pos, art in enumerate(articles, start=1):
        try:
            slug = (art.get("slug") or "").strip()
            title = (art.get("title") or "").strip()
            if not slug or not title:
                continue
            link = ARTICLE_TMPL.format(slug=slug)
            if link in seen:
                continue
            seen.add(link)

            excerpt = (art.get("excerpt") or "").strip()
            group = (art.get("primaryGroupTitle") or "").strip()
            description = excerpt
            if group:
                description = f"{excerpt}\n\nTopic: {group}" if excerpt else f"Topic: {group}"

            entries.append(
                {
                    "title": sanitize_xml(title),
                    "link": link,
                    "date": now - timedelta(seconds=pos),
                    "description": sanitize_xml(description),
                }
            )
        except Exception as e:  # never let one bad article kill the run
            logger.warning(f"Skipping malformed article at position {pos}: {e}")
            continue

    logger.info(f"Built {len(entries)} entries")
    return entries


def generate_atom_feed(entries, feed_name=FEED_NAME):
    fg = FeedGenerator()
    fg.id(f"{BLOG_URL}#{feed_name}")
    fg.title("Canva Learn")
    fg.subtitle("Design tips, guides, and tutorials from Canva Learn")
    setup_feed_links(fg, BLOG_URL, feed_name)
    fg.language("en")
    fg.author({"name": "Canva"})

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
    html = fetch_page_html()
    if html is None:
        logger.error("Fetch failed — skipping write to preserve the last good feed")
        return False

    articles = extract_articles(html)
    if not articles:
        logger.warning("No articles extracted — skipping write to avoid an empty feed")
        return False

    now = datetime.now(pytz.UTC)
    new_entries = build_entries(articles, now)
    if not new_entries:
        logger.warning("No usable entries built — skipping write to avoid an empty feed")
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
    parser = argparse.ArgumentParser(description="Generate the Canva Learn Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
