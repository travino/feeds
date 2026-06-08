"""SkillsLLM feed generator.

SkillsLLM (https://skillsllm.com) is a Next.js App Router site with no native
RSS/Atom feed — every `/feed`, `/rss.xml`, etc. path falls through to the SPA.
It does, however, publish a complete ``sitemap.xml`` with accurate ``lastmod``
dates, and each article page server-renders a real ``<title>`` and
``<meta name="description">``.

So this generator discovers article URLs from the sitemap (both the daily
``/news/ai-news-YYYY-MM-DD`` summaries and the long-form ``/blog/<slug>``
posts), then fetches each *new* page once to pull its title and description.
Already-cached URLs are never re-fetched, so a steady-state hourly run does at
most a couple of detail requests. Entries merge into a local cache (dedup by
``link``) and the result is written as an **Atom** feed to
``feeds/feed_skillsllm.xml``.
"""

import argparse
import re
import sys
import time
from datetime import datetime

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

FEED_NAME = "skillsllm"
BLOG_URL = "https://skillsllm.com/"
SITEMAP_URL = "https://skillsllm.com/sitemap.xml"

FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Only sitemap URLs under these path prefixes become feed entries.
SECTIONS = {
    "/news/": "news",
    "/blog/": "blog",
}

# Title suffixes the site appends; stripped for clean headlines.
_TITLE_SUFFIXES = (" | SkillsLLM Blog", " | SkillsLLM")
_NEWS_DATE_RE = re.compile(r"/news/ai-news-(\d{4}-\d{2}-\d{2})")

# Cap the merged feed so the committed XML stays a reasonable size; also bounds
# how many detail pages a cold (cache-less) build will fetch.
MAX_ENTRIES = 80


def fetch_url(url, retries=3, backoff=2.0):
    """Fetch *url* text, retrying transient failures. None on failure."""
    for attempt in range(1, retries + 1):
        try:
            return fetch_page(url, headers=FETCH_HEADERS)
        except Exception as e:
            logger.warning(f"Fetch failed for {url} (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(backoff * attempt)
    return None


def parse_date(value):
    """Parse a date string into a UTC datetime, or None."""
    try:
        dt = date_parser.parse(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.UTC)
        return dt.astimezone(pytz.UTC)
    except (ValueError, TypeError, OverflowError):
        return None


def discover_urls(sitemap_xml):
    """Return [(link, date)] for sitemap entries under SECTIONS, newest first.

    The date comes from the news slug when present (most reliable), otherwise
    from the sitemap ``<lastmod>``.
    """
    soup = BeautifulSoup(sitemap_xml, "xml")
    found = []
    for url_el in soup.find_all("url"):
        loc_el = url_el.find("loc")
        if not loc_el:
            continue
        loc = loc_el.get_text(strip=True)
        if not any(seg in loc for seg in SECTIONS):
            continue

        slug_match = _NEWS_DATE_RE.search(loc)
        if slug_match:
            date_obj = parse_date(slug_match.group(1))
        else:
            lastmod_el = url_el.find("lastmod")
            date_obj = parse_date(lastmod_el.get_text(strip=True)) if lastmod_el else None

        found.append((loc, date_obj))

    found.sort(key=lambda t: (t[1] or datetime.min.replace(tzinfo=pytz.UTC)), reverse=True)
    logger.info(f"Discovered {len(found)} news/blog URLs in sitemap")
    return found


def _section_of(link):
    for seg, name in SECTIONS.items():
        if seg in link:
            return name
    return "news"


def _clean_title(raw):
    title = sanitize_xml(raw.strip())
    for suffix in _TITLE_SUFFIXES:
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()
            break
    return title


def fetch_detail(link, date_obj):
    """Fetch one article page and return a normalized entry dict, or None."""
    html = fetch_url(link)
    if html is None:
        return None
    soup = BeautifulSoup(html, "html.parser")

    title_el = soup.find("title")
    title = _clean_title(title_el.get_text()) if title_el else None
    if not title:
        return None

    desc_el = soup.find("meta", attrs={"name": "description"})
    description = sanitize_xml(desc_el["content"].strip()) if desc_el and desc_el.get("content") else title

    return {
        "title": title,
        "link": link,
        "date": date_obj or stable_fallback_date(link),
        "description": description or title,
        "category": _section_of(link),
    }


def collect_entries(known_links):
    """Discover URLs from the sitemap and fetch details for unseen ones only.

    *known_links* is the set of links already in the cache; those are skipped
    (their cached entry is reused by the merge step), so only new articles cost
    a detail request.
    """
    sitemap = fetch_url(SITEMAP_URL)
    if sitemap is None:
        logger.error("Could not fetch sitemap — skipping run")
        return None

    discovered = discover_urls(sitemap)
    if not discovered:
        logger.warning("No news/blog URLs found in sitemap")
        return []

    # Only the newest MAX_ENTRIES are eligible, so a cold build is bounded.
    candidates = discovered[:MAX_ENTRIES]

    entries = []
    fetched = 0
    for link, date_obj in candidates:
        if link in known_links:
            continue
        try:
            entry = fetch_detail(link, date_obj)
            if entry:
                entries.append(entry)
                fetched += 1
            else:
                logger.warning(f"No usable title for {link}; skipping")
        except Exception as e:  # never let one bad page kill the run
            logger.warning(f"Skipping {link}: {e}")
    logger.info(f"Fetched details for {fetched} new article(s)")
    return entries


def generate_atom_feed(entries, feed_name=FEED_NAME):
    """Build an Atom FeedGenerator from the normalized entry list."""
    fg = FeedGenerator()
    fg.id(f"https://skillsllm.com/{feed_name}")
    fg.title("SkillsLLM – News & Blog")
    fg.subtitle("Daily AI development news and long-form guides from SkillsLLM")
    setup_feed_links(fg, BLOG_URL, feed_name)
    fg.language("en")
    fg.author({"name": "SkillsLLM"})

    for entry in entries:
        fe = fg.add_entry()
        fe.id(entry["link"])
        fe.title(entry["title"])
        fe.link(href=entry["link"])
        fe.description(entry["description"])
        if entry.get("category"):
            fe.category(term=entry["category"])
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
    """Discover articles, fetch new ones, merge with cache, write the feed."""
    if full:
        logger.info("Full reset requested — ignoring existing cache")
        cached = []
    else:
        cache = load_cache(FEED_NAME)
        cached = deserialize_entries(cache.get("entries", []), date_field="date")

    known_links = {e["link"] for e in cached}
    new_entries = collect_entries(known_links)

    if new_entries is None:
        logger.error("Fetch failed — skipping write to preserve the last good feed")
        return False

    merged = merge_entries(new_entries, cached, id_field="link", date_field="date")
    if not merged:
        logger.warning("No entries — skipping write to avoid an empty feed")
        return False

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
    parser = argparse.ArgumentParser(description="Generate the SkillsLLM Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
