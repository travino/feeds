"""Bitly feed generator.

Aggregates Bitly's update sources into one **Atom** feed written to
``feeds/feed_bitly.xml``:

    - Bitly Blog          https://bitly.com/blog/                              (HTML + per-article meta)
    - Bitly Press Room    https://bitly.com/pages/press                        (HTML)
    - Bitly MCP changelog https://dev.bitly.com/bitly-mcp/overview/mcp-changelog/ (__NEXT_DATA__ markdown)

Source handling:
  * Blog — a headless WordPress listing that shows titles but no dates, and the
    usual WP feed routes aren't proxied (``/blog/feed/`` just returns the
    listing HTML). Post links match ``/blog/<slug>/``; for links not already
    cached, the article page is fetched once for its ``og:title`` /
    ``og:description`` / ``article:published_time`` meta, so steady-state runs
    do no per-article fetches.
  * Press Room — each item is a ``div.press-info`` carrying a "April 2, 2026"
    date and an ``h3.post-title`` link (sometimes to external coverage).
  * MCP changelog — a Next.js docs page; the page markdown ships in
    ``__NEXT_DATA__`` (``props.pageProps.markdownSource``) as a
    ``| Release Date | Summary |`` table with month-granular dates. Entries
    are dated to the 1st of their month and get a synthetic
    ``#mcp-<date>-<slug>`` fragment for stable dedupe (fragments are the only
    differentiator between entries — preserve them).

History accumulates across runs via the shared JSON cache
(``cache/bitly_posts.json``); entries dedupe by link, then cross-source by
normalized URL/title.
"""

import argparse
import json
import re
import sys
import time

import pytz
import requests
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

FEED_NAME = "bitly"
BLOG_URL = "https://bitly.com/blog/"

BLOG_LISTING = "https://bitly.com/blog/"
PRESS_URL = "https://bitly.com/pages/press"
MCP_CHANGELOG_URL = "https://dev.bitly.com/bitly-mcp/overview/mcp-changelog/"

# Post permalinks look like https://bitly.com/blog/<slug>/ ; these path heads
# are listing/taxonomy pages, not posts.
_BLOG_POST_RE = re.compile(r"^https://bitly\.com/blog/([a-z0-9-]+)/$")
_BLOG_SKIP = {"category", "tag", "author", "page"}

DATE_RE = re.compile(
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December"
    r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2},?\s+\d{4})"
)
# MCP changelog table rows carry month-granular dates ("April 2026").
_MONTH_YEAR_RE = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{4})$"
)

# Polite delay between per-article metadata fetches.
SLEEP_BETWEEN = 0.4

DESC_LIMIT = 500
MAX_ENTRIES = 200


def _get_html(url):
    """Fetch a URL impersonating Chrome, falling back to plain requests if
    curl_cffi is unavailable. Returns text or None."""
    try:
        from curl_cffi import requests as creq

        resp = creq.get(url, impersonate="chrome", timeout=30)
    except ImportError:
        logger.warning(f"curl_cffi unavailable; using plain requests for {url}")
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0"},
                timeout=30,
            )
        except Exception as e:
            logger.warning(f"Fetch failed for {url}: {e}")
            return None
    except Exception as e:
        logger.warning(f"Fetch failed for {url}: {e}")
        return None
    if resp.status_code != 200:
        logger.warning(f"Fetch for {url} returned HTTP {resp.status_code}")
        return None
    return resp.text


def parse_date(date_str):
    """Parse a date string into a UTC datetime, or None on failure."""
    try:
        dt = date_parser.parse(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.UTC)
        return dt.astimezone(pytz.UTC)
    except (ValueError, TypeError, OverflowError) as e:
        logger.warning(f"Could not parse date '{date_str}': {e}")
        return None


def _normalize_url(url):
    """Canonicalize a URL for dedup: drop scheme and www, normalize a trailing
    slash or index.html. Query and fragment are PRESERVED, since changelog
    entries are distinguished only by their fragment."""
    from urllib.parse import urlsplit
    try:
        parts = urlsplit(url)
        host = re.sub(r"^www\.", "", (parts.netloc or "").lower())
        path = re.sub(r"/index\.html?$", "/", parts.path or "").rstrip("/")
        query = f"?{parts.query}" if parts.query else ""
        frag = f"#{parts.fragment}" if parts.fragment else ""
        return f"{host}{path}{query}{frag}".lower()
    except Exception:
        return (url or "").strip().lower()


def _normalize_title(title):
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def dedupe_entries(entries, id_field="link", title_field="title", date_field="date"):
    """Remove cross-source duplicates by normalized URL and normalized title.

    Keeps the first occurrence and preserves order; if a later duplicate has a
    date while the kept one does not, the dated entry replaces it. Entries with
    empty URL/title keys are never collapsed against each other.
    """
    seen_url, seen_title, result, removed = {}, {}, [], 0
    for entry in entries:
        ukey = _normalize_url(entry.get(id_field, ""))
        tkey = _normalize_title(entry.get(title_field, ""))
        idx = seen_url.get(ukey) if ukey else None
        if idx is None and tkey:
            idx = seen_title.get(tkey)
        if idx is None:
            pos = len(result)
            if ukey:
                seen_url[ukey] = pos
            if tkey:
                seen_title[tkey] = pos
            result.append(entry)
        else:
            removed += 1
            if result[idx].get(date_field) is None and entry.get(date_field) is not None:
                result[idx] = entry
    if removed:
        logger.info(f"Deduplicated {removed} entries")
    return result


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def title_from_slug(slug):
    return slug.replace("-", " ").replace("_", " ").strip().capitalize()


def _meta(html, prop):
    m = re.search(rf'<meta[^>]+property="{prop}"[^>]+content="([^"]*)"', html)
    if not m:
        m = re.search(rf'<meta[^>]+content="([^"]*)"[^>]+property="{prop}"', html)
    return m.group(1) if m else None


# --------------------------------------------------------------------------- #
# Bitly Blog (headless WP listing without dates; per-article og: meta)
# --------------------------------------------------------------------------- #


def scrape_blog(known_links):
    label = "Bitly Blog"
    entries = []
    html = _get_html(BLOG_LISTING)
    if html is None:
        return entries
    soup = BeautifulSoup(html, "html.parser")

    seen = set()
    for a in soup.find_all("a", href=True):
        m = _BLOG_POST_RE.match(a["href"])
        if not m or m.group(1) in _BLOG_SKIP:
            continue
        link = a["href"]
        if link in seen:
            continue
        seen.add(link)
        if link in known_links:
            continue
        try:
            # The listing carries no dates, so fetch the article once for its
            # og: meta; the cache gate above keeps steady-state runs at zero
            # per-article fetches.
            page = _get_html(link)
            time.sleep(SLEEP_BETWEEN)
            if page is None:
                continue
            title = _meta(page, "og:title") or title_from_slug(m.group(1))
            desc = _meta(page, "og:description") or title
            published = _meta(page, "article:published_time")
            date_obj = parse_date(published) if published else stable_fallback_date(link)
            entries.append({
                "title": sanitize_xml(title),
                "link": link,
                "date": date_obj,
                "description": sanitize_xml(desc)[:DESC_LIMIT],
                "source": label,
            })
            logger.info(f"  [{label}] {title}")
        except Exception as e:
            logger.warning(f"  [{label}] skipping malformed post {link}: {e}")
    return entries


# --------------------------------------------------------------------------- #
# Bitly Press Room (div.press-info: date + h3.post-title link)
# --------------------------------------------------------------------------- #


def scrape_press(known_links):
    label = "Bitly Press"
    entries = []
    html = _get_html(PRESS_URL)
    if html is None:
        return entries
    soup = BeautifulSoup(html, "html.parser")

    infos = soup.find_all("div", class_="press-info")
    if not infos:
        logger.warning(f"  [{label}] no press items matched — layout may have changed")
        return entries

    for info in infos:
        try:
            h3 = info.find("h3")
            a = h3.find("a", href=True) if h3 else None
            if a is None:
                continue
            link = a["href"].split("#")[0]
            if not link or link in known_links:
                continue
            title = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
            m = DATE_RE.search(info.get_text(" ", strip=True))
            date_obj = parse_date(m.group(1)) if m else stable_fallback_date(link)
            entries.append({
                "title": sanitize_xml(title),
                "link": link,
                "date": date_obj,
                "description": sanitize_xml(title),
                "source": label,
            })
            logger.info(f"  [{label}] {title}")
        except Exception as e:
            logger.warning(f"  [{label}] skipping malformed item: {e}")
    return entries


# --------------------------------------------------------------------------- #
# Bitly MCP changelog (__NEXT_DATA__ markdownSource: | Release Date | Summary |)
# --------------------------------------------------------------------------- #


def scrape_mcp_changelog(known_links):
    import datetime as _dt

    label = "Bitly MCP changelog"
    entries = []
    html = _get_html(MCP_CHANGELOG_URL)
    if html is None:
        return entries

    try:
        soup = BeautifulSoup(html, "html.parser")
        nd = soup.find("script", id="__NEXT_DATA__")
        data = json.loads(nd.string)
        md = data["props"]["pageProps"]["markdownSource"]
    except Exception as e:
        logger.warning(f"  [{label}] could not extract __NEXT_DATA__ markdown: {e}")
        return entries

    rows = 0
    for line in md.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        mdate = _MONTH_YEAR_RE.match(cells[0])
        if not mdate:
            continue   # header / separator rows
        try:
            rows += 1
            date_obj = parse_date(f"{mdate.group(1)} 1, {mdate.group(2)}")
            summary = re.sub(r"\s+", " ", cells[1]).strip()
            frag = f"mcp-{date_obj.date().isoformat()}-{slugify(' '.join(summary.split()[:6]))[:48]}"
            link = f"{MCP_CHANGELOG_URL}#{frag}"
            if link in known_links:
                continue
            title = summary if len(summary) <= 110 else summary[:107] + "..."
            entries.append({
                "title": sanitize_xml(title),
                "link": link,
                "date": date_obj,
                "description": sanitize_xml(summary)[:DESC_LIMIT],
                "source": label,
            })
            logger.info(f"  [{label}] {title}")
        except Exception as e:
            logger.warning(f"  [{label}] skipping malformed row: {e}")
    if not rows:
        logger.warning(f"  [{label}] no table rows parsed — page structure may have changed")
    return entries


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def scrape_all(known_links):
    new_entries = []
    logger.info("Scraping Bitly Blog ...")
    new_entries += scrape_blog(known_links)
    logger.info("Scraping Bitly Press ...")
    new_entries += scrape_press(known_links)
    logger.info("Scraping Bitly MCP changelog ...")
    new_entries += scrape_mcp_changelog(known_links)
    return new_entries


def generate_atom_feed(articles, feed_name=FEED_NAME):
    fg = FeedGenerator()
    fg.id(f"https://bitly.com/{feed_name}")
    fg.title("Bitly")
    fg.subtitle("Bitly updates: Blog, Press Room, and the Bitly MCP changelog.")
    setup_feed_links(fg, BLOG_URL, feed_name)
    fg.language("en")
    fg.author({"name": "Bitly"})

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
    output_file = get_feeds_dir() / f"feed_{feed_name}.xml"
    fg.atom_file(str(output_file), pretty=True)
    logger.info(f"Saved Atom feed to {output_file}")
    return output_file


def main(full=False):
    if full:
        logger.info("Full reset requested — ignoring existing cache")
        cached = []
    else:
        cache = load_cache(FEED_NAME)
        cached = deserialize_entries(cache.get("entries", []), date_field="date")

    known_links = {e["link"] for e in cached}
    new_articles = scrape_all(known_links)

    if not new_articles and not cached:
        logger.warning("No articles collected — skipping write to avoid an empty feed")
        return False

    merged = merge_entries(new_articles, cached, id_field="link", date_field="date")
    merged = dedupe_entries(merged, id_field="link", title_field="title", date_field="date")
    merged = sort_posts_for_feed(merged, date_field="date")

    # Keep full (deduplicated) history in the cache so already-seen links are
    # never re-evaluated on later runs; only the rendered feed is capped.
    save_cache(FEED_NAME, merged)

    feed_items = merged[-MAX_ENTRIES:] if len(merged) > MAX_ENTRIES else merged

    fg = generate_atom_feed(feed_items)
    save_atom_feed(fg)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the Bitly Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
