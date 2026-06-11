#!/usr/bin/env python3
"""Combined Atom feed for YouTube's official blog and Culture & Trends.

blog.youtube ships a native RSS feed at /rss/, but it only carries the
News & Events and Creator & Artist Stories sections — Inside YouTube posts
(e.g. the CEO's annual letter) never appear in it, and the Culture & Trends
site (youtube.com/trends) has no feed at all. This generator merges three
sources into one Atom feed, deduplicated by canonical URL / normalized title:

* Native RSS                 https://blog.youtube/rss/
* "Latest" page ItemList     https://blog.youtube/feed/  (HTML, not a feed —
  its ld+json ItemList catches posts the RSS omits; each new URL is fetched
  once for its BlogPosting metadata, gated by the cache)
* Culture & Trends Discover  https://www.youtube.com/trends/discover/
  (scraped cards; the articles are dateless, so they get a stable fallback
  date and never churn)

Usage:
    python youtube.py          # fetch all sources, merge into cache
    python youtube.py --full   # ignore cache, rebuild from current sources

Output:
    feeds/feed_youtube.xml     # combined Atom feed
    cache/youtube_posts.json   # entry cache (rolling archive)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import feedparser
import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

from utils import (
    DEFAULT_HEADERS,
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

FEED_NAME = "youtube"
BLOG_URL = "https://blog.youtube/"
FEED_TITLE = "YouTube Blog & Culture and Trends"
FEED_DESC = (
    "Combined feed of the official YouTube Blog (News & Events, Creator & "
    "Artist Stories, Inside YouTube) and YouTube Culture & Trends"
)
FEED_LANG = "en"
MAX_ENTRIES = 300

RSS_URL = "https://blog.youtube/rss/"
LATEST_URL = "https://blog.youtube/feed/"  # HTML "Latest" page, not a feed
TRENDS_URL = "https://www.youtube.com/trends/discover/"
TRENDS_BASE = "https://www.youtube.com"

LATEST_FETCH_BUDGET = 10  # max per-article fetches per run for never-seen URLs

# Map URL path section -> human label for the Atom <category> tag.
SECTION_LABELS = {
    "news-and-events": "News & Events",
    "creator-and-artist-stories": "Creator & Artist Stories",
    "inside-youtube": "Inside YouTube",
    "culture-and-trends": "Culture & Trends",
}

_TRACKING_KEYS = {"gclid", "fbclid", "mc_cid", "mc_eid", "ref", "ref_src"}


def canonical_link(url: str) -> str:
    """Normalize a URL so equivalent links dedupe: strip tracking params,
    keep the fragment (some sources differentiate entries by #anchor)."""
    if not url:
        return url
    parts = urlsplit(url.strip())
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_KEYS
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def section_label(link: str) -> str:
    """Derive the source label from the article URL's first path segment."""
    path = urlsplit(link).path.strip("/").split("/")
    if urlsplit(link).netloc == "www.youtube.com":
        return "Culture & Trends"
    return SECTION_LABELS.get(path[0] if path else "", "YouTube Blog")


def entry_date(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        struct = entry.get(key)
        if struct:
            return datetime(*struct[:6], tzinfo=timezone.utc)
    return None


def collect_rss() -> list[dict]:
    """The native blog.youtube RSS feed (News & Events + Creator Stories)."""
    try:
        resp = requests.get(RSS_URL, headers=DEFAULT_HEADERS, timeout=30)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
    except Exception as exc:  # one dead source never kills the run
        logger.warning("[rss] fetch failed (%s); skipping this source", exc)
        return []

    entries: list[dict] = []
    for e in parsed.entries:
        try:
            link = canonical_link(e.get("link") or "")
            title = sanitize_xml((e.get("title") or "").strip())
            if not link or not title:
                continue
            entries.append(
                {
                    "title": title,
                    "link": link,
                    "date": entry_date(e) or stable_fallback_date(link),
                    "description": sanitize_xml(e.get("summary") or ""),
                    "source": section_label(link),
                }
            )
        except Exception as exc:  # one malformed item is skipped, not fatal
            logger.warning("[rss] skipping an entry due to error: %s", exc)
    logger.info("[rss] parsed %d entries", len(entries))
    return entries


def _article_metadata(url: str) -> dict | None:
    """Fetch one blog.youtube article and read its BlogPosting ld+json."""
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict) and data.get("@type") in ("BlogPosting", "NewsArticle", "Article"):
            title = sanitize_xml(str(data.get("headline") or "").strip())
            if not title:
                return None
            raw_date = data.get("datePublished")
            try:
                from dateutil import parser as dateutil_parser

                date = dateutil_parser.parse(raw_date).astimezone(timezone.utc)
            except Exception:
                date = stable_fallback_date(url)
            return {
                "title": title,
                "link": url,
                "date": date,
                "description": sanitize_xml(str(data.get("description") or "")),
                "content_type": "text",
                "source": section_label(url),
            }
    return None


def collect_latest(known_links: set[str]) -> list[dict]:
    """Posts on the blog's "Latest" page that the native RSS omitted.

    The page's ld+json ItemList only carries URLs, so each genuinely new URL
    costs one article fetch — gated by `known_links` (cache + RSS results) so
    steady-state runs make zero extra requests.
    """
    try:
        resp = requests.get(LATEST_URL, headers=DEFAULT_HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as exc:
        logger.warning("[latest] fetch failed (%s); skipping this source", exc)
        return []

    urls: list[str] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict) and data.get("@type") == "ItemList":
            for item in data.get("itemListElement") or []:
                url = canonical_link(str(item.get("url") or ""))
                if url.startswith("https://blog.youtube/") and url not in known_links:
                    urls.append(url)

    entries: list[dict] = []
    for url in urls[:LATEST_FETCH_BUDGET]:
        try:
            meta = _article_metadata(url)
            if meta:
                entries.append(meta)
        except Exception as exc:  # one bad article never kills the source
            logger.warning("[latest] skipping %s due to error: %s", url, exc)
    logger.info("[latest] %d new URLs, parsed %d entries", len(urls), len(entries))
    return entries


def collect_trends() -> list[dict]:
    """Culture & Trends Discover cards (youtube.com/trends — no native feed).

    The articles carry no publication date anywhere, so each gets a stable
    fallback date keyed on its URL and never reshuffles between runs.
    """
    try:
        resp = requests.get(TRENDS_URL, headers=DEFAULT_HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as exc:
        logger.warning("[trends] fetch failed (%s); skipping this source", exc)
        return []

    entries: list[dict] = []
    for card in soup.select("li.ytt-card"):
        try:
            a = card.select_one("a.ytt-card__link")
            h3 = card.select_one("h3")
            if not a or not a.get("href") or not h3:
                continue
            link = canonical_link(urljoin(TRENDS_BASE, a["href"]))
            title = sanitize_xml(h3.get_text(" ", strip=True))
            if not title:
                continue
            eyebrow = card.select_one(".ytt-card__eyebrow")
            kind = eyebrow.get_text(strip=True) if eyebrow else ""
            entries.append(
                {
                    "title": title,
                    "link": link,
                    "date": stable_fallback_date(link),
                    "description": sanitize_xml(f"Culture & Trends{' — ' + kind if kind else ''}: {title}"),
                    "content_type": "text",
                    "source": "Culture & Trends",
                }
            )
        except Exception as exc:  # one bad card never kills the source
            logger.warning("[trends] skipping a card due to error: %s", exc)
    logger.info("[trends] parsed %d entries", len(entries))
    return entries


def collect(cached_links: set[str]) -> list[dict]:
    """Fetch every source and dedupe by canonical URL or normalized title
    (first occurrence wins; the metadata-rich RSS goes first)."""
    seen_links: set[str] = set()
    seen_titles: set[str] = set()
    out: list[dict] = []

    def add(items):
        for item in items:
            ntitle = normalize_title(item["title"])
            if item["link"] in seen_links or ntitle in seen_titles:
                continue
            seen_links.add(item["link"])
            seen_titles.add(ntitle)
            out.append(item)

    add(collect_rss())
    add(collect_latest(known_links=cached_links | seen_links))
    add(collect_trends())

    logger.info("Collected %d unique entries across 3 sources", len(out))
    return out


def generate_atom_feed(articles, feed_name=FEED_NAME):
    fg = FeedGenerator()
    fg.id(BLOG_URL)
    fg.title(FEED_TITLE)
    fg.subtitle(FEED_DESC)
    setup_feed_links(fg, BLOG_URL, feed_name)
    fg.language(FEED_LANG)
    fg.author({"name": "YouTube"})

    for article in articles:
        fe = fg.add_entry()
        fe.id(article["link"])
        fe.title(article["title"])
        fe.link(href=article["link"])
        if article.get("description"):
            fe.content(article["description"], type=article.get("content_type", "html"))
        if article.get("source"):
            fe.category(term=article["source"])
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


def main(full=False) -> bool:
    """Aggregate every source, merge with cache, and write the Atom feed."""
    if full:
        logger.info("Full reset requested — ignoring existing cache")
        cached = []
    else:
        cache = load_cache(FEED_NAME)
        cached = deserialize_entries(cache.get("entries", []), date_field="date")

    new_articles = collect(cached_links={e["link"] for e in cached})
    if not new_articles:
        logger.error("No entries collected from any source — skipping write to preserve the last good feed")
        return False

    merged = merge_entries(new_articles, cached, id_field="link", date_field="date")
    merged = sort_posts_for_feed(merged, date_field="date")

    # sort_posts_for_feed returns ascending (feedgen reverses on write), so the
    # tail is newest — keep it when capping.
    if len(merged) > MAX_ENTRIES:
        merged = merged[-MAX_ENTRIES:]

    save_cache(FEED_NAME, merged)
    save_atom_feed(generate_atom_feed(merged))
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the combined YouTube Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from current sources only")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
