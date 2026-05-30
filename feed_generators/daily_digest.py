"""Daily digest feed generator.

Combines five small JSON APIs into a single Atom feed:

  * ZenQuotes "quote of the day"          https://zenquotes.io/api/today
  * ViewBits useless fact of the day      https://api.viewbits.com/v1/uselessfacts?mode=today
  * ViewBits life hack of the day         https://api.viewbits.com/v1/lifehacks?mode=today
  * ViewBits fortune cookie of the day    https://api.viewbits.com/v1/fortunecookie?mode=today
  * ViewBits news headlines               https://api.viewbits.com/v1/headlines

Each source is fetched independently so one failure never sinks the run. Entries
merge into a local cache (dedup by ``guid``) so history accumulates across hourly
runs, and the result is written as an **Atom** feed to ``feeds/feed_daily_digest.xml``.

The four "today" endpoints expose only a single URL each (no per-day permalink),
so they are deduplicated by a synthetic ``{kind}:{date}`` guid while their
clickable ``link`` stays pointed at the real source. Headlines dedupe by article URL.
"""

import argparse
import html
import json
import sys
import time
from datetime import datetime

import pytz
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

FEED_NAME = "daily_digest"
BLOG_URL = "https://api.viewbits.com/"

SOURCES = {
    "quote": "https://zenquotes.io/api/today",
    "fact": "https://api.viewbits.com/v1/uselessfacts?mode=today",
    "lifehack": "https://api.viewbits.com/v1/lifehacks?mode=today",
    "fortune": "https://api.viewbits.com/v1/fortunecookie?mode=today",
    "headlines": "https://api.viewbits.com/v1/headlines",
}

FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

# Cap the merged feed so the committed XML stays a reasonable size.
MAX_ENTRIES = 100


def fetch_json(url, retries=3, backoff=2.0):
    """Fetch *url* and parse JSON, retrying transient failures. None on failure."""
    for attempt in range(1, retries + 1):
        try:
            body = fetch_page(url, headers=FETCH_HEADERS)
            return json.loads(body)
        except Exception as e:
            logger.warning(f"Fetch failed for {url} (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(backoff * attempt)
    return None


def _clean(text):
    """HTML-unescape then strip characters invalid in XML 1.0."""
    return sanitize_xml(html.unescape(text or "").strip())


def _today_utc():
    return datetime.now(pytz.UTC)


def _day_midnight(date_str=None):
    """Midnight UTC for the given YYYY-MM-DD (or today). Stable within a day so
    repeated runs produce an identical entry and the feed doesn't churn."""
    if date_str:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            d = _today_utc()
    else:
        d = _today_utc()
    return d.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=pytz.UTC)


# --- Per-source adapters. Each returns a list of normalized entry dicts:
#     {guid, link, title, description, date, source, category} -------------


def adapt_quote(data):
    item = data[0]
    text = _clean(item.get("q"))
    author = _clean(item.get("a"))
    date_str = item.get("date") or f"{_today_utc():%Y-%m-%d}"
    body = f"\u201c{text}\u201d \u2014 {author}" if author else f"\u201c{text}\u201d"
    return [{
        "guid": f"quote:{date_str}",
        "link": "https://zenquotes.io/",
        "title": _clean(f"Quote of the Day \u2014 {author}") if author else "Quote of the Day",
        "description": body,
        "date": _day_midnight(date_str),
        "source": author or "ZenQuotes",
        "category": "quote",
    }]


def adapt_simple(data, *, kind, title, source_name):
    """Single-object ViewBits endpoints (fact / lifehack / fortune)."""
    text = _clean(data.get("text"))
    body = text
    if data.get("numbers"):
        body = f"{text}\n\nLucky Numbers: {_clean(data['numbers'])}"
    day = f"{_today_utc():%Y-%m-%d}"
    return [{
        "guid": f"{kind}:{day}",
        "link": data.get("url") or BLOG_URL,
        "title": title,
        "description": body or title,
        "date": _day_midnight(),
        "source": source_name,
        "category": kind,
    }]


def adapt_headlines(data):
    entries = []
    seen = set()
    for item in data:
        try:
            link = item.get("link")
            title = _clean(item.get("title"))
            if not link or not title or link in seen:
                continue
            seen.add(link)
            desc = _clean(item.get("description")) or title
            pub = item.get("pubDate")
            try:
                date_obj = date_parser.parse(pub) if pub else None
                if date_obj and date_obj.tzinfo is None:
                    date_obj = date_obj.replace(tzinfo=pytz.UTC)
                if date_obj:
                    date_obj = date_obj.astimezone(pytz.UTC)
            except (ValueError, TypeError, OverflowError):
                date_obj = None
            entries.append({
                "guid": link,
                "link": link,
                "title": title,
                "description": desc,
                "date": date_obj,
                "source": item.get("source") or "headlines",
                "category": item.get("category") or "news",
            })
        except Exception as e:  # never let one bad item kill the run
            logger.warning(f"Skipping malformed headline: {e}")
    return entries


ADAPTERS = {
    "quote": adapt_quote,
    "fact": lambda d: adapt_simple(d, kind="fact", title="Useless Fact of the Day", source_name="ViewBits"),
    "lifehack": lambda d: adapt_simple(d, kind="lifehack", title="Life Hack of the Day", source_name="ViewBits"),
    "fortune": lambda d: adapt_simple(d, kind="fortune", title="Fortune Cookie of the Day", source_name="ViewBits"),
    "headlines": adapt_headlines,
}


def collect_entries():
    """Fetch and normalize all sources. Per-source failures are logged and skipped."""
    entries = []
    for key, url in SOURCES.items():
        data = fetch_json(url)
        if data is None:
            logger.warning(f"Source '{key}' unavailable; continuing")
            continue
        try:
            new = ADAPTERS[key](data)
            logger.info(f"{key}: {len(new)} entry(ies)")
            entries.extend(new)
        except Exception as e:
            logger.warning(f"Source '{key}' parse failed ({e}); continuing")
    return entries


def generate_atom_feed(entries, feed_name=FEED_NAME):
    """Build an Atom FeedGenerator from the normalized entry list."""
    fg = FeedGenerator()
    fg.id(f"https://api.viewbits.com/{feed_name}")
    fg.title("Daily Digest")
    fg.subtitle("Quote, fact, life hack, fortune cookie, and headlines of the day")
    setup_feed_links(fg, BLOG_URL, feed_name)
    fg.language("en")
    fg.author({"name": "Daily Digest"})

    for entry in entries:
        fe = fg.add_entry()
        fe.id(entry["guid"])
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

    merged = merge_entries(new_entries, cached, id_field="guid", date_field="date")
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
    parser = argparse.ArgumentParser(description="Generate the Daily Digest Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
