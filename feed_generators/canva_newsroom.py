"""Canva Newsroom feed generator.

Canva's newsroom (https://www.canva.com/newsroom/news/) has no native feed and
sits behind Cloudflare, which fingerprints the TLS handshake (JA3) and returns
HTTP 403 to plain ``requests``. It's a Next.js app, but the post list is shipped
in the page's ``__NEXT_DATA__`` blob, so ``curl_cffi`` impersonating a real
Chrome fingerprint is enough — no browser/JS execution needed.

Each post carries a real ``publishedAt`` timestamp, so this is a genuine
date-ordered news feed. Posts are merged with a local cache (dedupe by URL) so
history accumulates across runs, and written as **Atom** to
``feeds/feed_canva_newsroom.xml``.
"""

import argparse
import json
import sys
import time

import pytz
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
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
    stable_fallback_date,
)

logger = setup_logging()

FEED_NAME = "canva_newsroom"
BLOG_URL = "https://www.canva.com/newsroom/news/"
ARTICLE_TMPL = "https://www.canva.com/newsroom/news/{slug}/"
MAX_ENTRIES = 100


def fetch_page_html(retries: int = 3, backoff: float = 2.0) -> str | None:
    """Fetch the newsroom HTML via curl_cffi (Cloudflare 403s plain requests)."""
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
                logger.info(f"Fetched newsroom ({len(resp.text)} bytes)")
                return resp.text
            logger.warning(f"Unexpected response (status {resp.status_code}) on attempt {attempt}")
        except Exception as e:
            logger.warning(f"Fetch failed (attempt {attempt}/{retries}): {e}")
        if attempt < retries:
            time.sleep(backoff * attempt)
    return None


def extract_posts(html: str) -> list[dict]:
    """Pull post objects out of __NEXT_DATA__ (regular list + featured)."""
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

    posts: list[dict] = []
    posts.extend(props.get("featuredArticles") or [])
    posts.extend(props.get("posts") or [])
    return posts


def build_entries(posts: list[dict]) -> list[dict]:
    entries: list[dict] = []
    seen: set[str] = set()

    for post in posts:
        try:
            slug = (post.get("slug") or "").strip()
            title = (post.get("name") or "").strip()
            if not slug or not title:
                continue
            link = ARTICLE_TMPL.format(slug=slug)
            if link in seen:
                continue
            seen.add(link)

            raw_date = post.get("publishedAt")
            date = None
            if raw_date:
                try:
                    dt = date_parser.parse(raw_date)
                    date = dt.astimezone(pytz.UTC) if dt.tzinfo else pytz.UTC.localize(dt)
                except (ValueError, OverflowError):
                    date = None
            if date is None:
                date = stable_fallback_date(link)

            summary = (post.get("summary") or "").strip()
            category = ((post.get("category") or {}).get("title") or "").strip()
            description = f"{summary}\n\nCategory: {category}" if category else summary

            entries.append(
                {
                    "title": sanitize_xml(title),
                    "link": link,
                    "date": date,
                    "description": sanitize_xml(description),
                }
            )
        except Exception as e:  # never let one bad post kill the run
            logger.warning(f"Skipping malformed post: {e}")
            continue

    logger.info(f"Built {len(entries)} entries")
    return entries


def generate_atom_feed(entries, feed_name=FEED_NAME):
    fg = FeedGenerator()
    fg.id(f"{BLOG_URL}#{feed_name}")
    fg.title("Canva Newsroom")
    fg.subtitle("News and announcements from Canva")
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

    posts = extract_posts(html)
    if not posts:
        logger.warning("No posts extracted — skipping write to avoid an empty feed")
        return False

    new_entries = build_entries(posts)
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
    parser = argparse.ArgumentParser(description="Generate the Canva Newsroom Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
