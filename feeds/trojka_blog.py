"""Generate RSS feed for Trójka — Program Trzeci Polskiego Radia
(https://trojka.polskieradio.pl/czytaj-wiecej).

Trójka's site is a Next.js app. The article listing is server-side rendered into
the ``__NEXT_DATA__`` JSON blob (``props.pageProps.data``), so no JS execution /
Selenium is needed — a plain ``requests`` fetch yields fully structured article
objects with ``url``, ``title``, ``lead``, ``datePublic`` (ISO 8601), and
``categoryName``.

A JSON cache (``cache/trojka_posts.json``) accumulates history across hourly
runs and dedupes by article URL, so older articles persist after they scroll off
the listing page. Writes an RSS feed to ``feeds/feed_trojka.xml``.
"""

import argparse
import json
import re
from datetime import datetime

import pytz
from feedgen.feed import FeedGenerator

from utils import (
    deserialize_entries,
    fetch_page,
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

FEED_NAME = "trojka"
BLOG_URL = "https://trojka.polskieradio.pl/czytaj-wiecej"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)


def _extract_next_data(html: str) -> dict:
    """Pull and parse the Next.js __NEXT_DATA__ JSON blob from the page HTML."""
    match = _NEXT_DATA_RE.search(html)
    if not match:
        raise ValueError("__NEXT_DATA__ blob not found — page structure changed")
    return json.loads(match.group(1))


def _parse_date(value: str | None, fallback_id: str) -> datetime:
    """Parse Trójka's ISO 8601 ``datePublic`` (e.g. 2026-05-30T18:30:00).

    Times come back as naive local (Europe/Warsaw); attach that tz so the feed
    carries correct offsets.
    """
    if not value:
        return stable_fallback_date(fallback_id)
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = pytz.timezone("Europe/Warsaw").localize(dt)
        return dt
    except (ValueError, TypeError):
        logger.warning("Unable to parse date %r; using fallback", value)
        return stable_fallback_date(fallback_id)


def parse_posts(html: str) -> list[dict]:
    """Extract articles from the listing page's __NEXT_DATA__ JSON."""
    data = _extract_next_data(html)
    articles = data.get("props", {}).get("pageProps", {}).get("data", [])

    posts: list[dict] = []
    for art in articles:
        try:
            link = art.get("url")
            title = art.get("title")
            if not link or not title:
                continue
            if link.startswith("/"):
                link = f"https://trojka.polskieradio.pl{link}"

            lead = sanitize_xml((art.get("lead") or "").strip())
            description = lead or sanitize_xml(title.strip())
            date = _parse_date(art.get("datePublic"), link)

            posts.append(
                {
                    "link": link,
                    "title": sanitize_xml(title.strip()),
                    "description": description,
                    "date": date,
                    "category": (art.get("categoryName") or "").strip() or None,
                }
            )
        except Exception as exc:  # never let one bad article crash the run
            logger.warning("Skipping malformed article (%s): %s", art.get("id"), exc)
            continue

    logger.info("Parsed %d articles from listing", len(posts))
    return posts


def generate_rss_feed(posts: list[dict]) -> FeedGenerator:
    fg = FeedGenerator()
    fg.title("Trójka – Program Trzeci Polskiego Radia")
    fg.description(
        "Najnowsze artykuły radiowej Trójki: muzyka, kultura, koncerty, "
        "Lista Przebojów Trójki i Trójkowe podcasty."
    )
    fg.language("pl")
    fg.author({"name": "Polskie Radio – Trójka"})
    fg.logo("https://trojka.polskieradio.pl/logo_100_black.svg")
    fg.subtitle("Program Trzeci Polskiego Radia")
    setup_feed_links(fg, blog_url="https://trojka.polskieradio.pl", feed_name=FEED_NAME)

    for post in posts:
        fe = fg.add_entry()
        fe.title(post["title"])
        fe.description(post["description"])
        fe.link(href=post["link"])
        fe.id(post["link"])
        if post.get("category"):
            fe.category(term=post["category"])
        if post.get("date"):
            fe.published(post["date"])

    logger.info("Generated RSS feed with %d entries", len(posts))
    return fg


def main(full_reset: bool = False) -> bool:
    cache = load_cache(FEED_NAME)
    cached_entries = deserialize_entries(cache.get("entries", []))

    html = fetch_page(BLOG_URL)
    new_posts = parse_posts(html)

    if full_reset or not cached_entries:
        mode = "full reset" if full_reset else "no cache exists"
        logger.info("Running full fetch (%s)", mode)
        posts = sort_posts_for_feed(new_posts, date_field="date")
    else:
        logger.info("Running incremental update")
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
    parser = argparse.ArgumentParser(description="Generate Trójka (Polskie Radio) RSS feed")
    parser.add_argument("--full", action="store_true", help="Force full reset (ignore cache)")
    args = parser.parse_args()
    main(full_reset=args.full)
