#!/usr/bin/env python3
"""Combined Atom feed for Google's official blogs.

Several Google properties publish their own RSS/Atom feeds. This generator
merges them into a single Atom feed, deduplicated by canonical article URL so
the same post surfacing in more than one source feed (e.g. The Keyword and the
Search Central / Feedburner mirror) appears only once.

Sources (each a native feed unless marked scraped, aggregated here into one):

* The Keyword                 https://blog.google/rss/
* Google Poland (PL)          https://blog.google/intl/pl-pl/rss/
* Workspace Updates           https://workspaceupdates.googleblog.com/atom.xml
* Google Developers           https://developers.googleblog.com/feed/
* Android Developers          https://android-developers.googleblog.com/atom.xml
* Chrome for Developers       https://developer.chrome.com/static/blog/feed.xml
* Chromium Blog               https://blog.chromium.org/atom.xml
* Firebase                    https://firebase.blog/rss.xml
* Search Central              https://feeds.feedburner.com/blogspot/amDG
* Search Central Docs         https://developers.google.com/search/updates/search_docs_updates.rss
* Search Status Dashboard     https://status.search.google.com/en/feed.atom?hl=pl
* Waze                        https://blog.google/waze/rss/
* Google Research             https://research.google/blog/rss/
* Google DeepMind             https://deepmind.google/blog/rss.xml
* Google Cloud                https://cloudblog.withgoogle.com/rss/
* Google Cloud Press          https://www.googlecloudpresscorner.com/press-releases?pagetemplate=rss
* Workspace Updates (mirror)  https://feeds.feedburner.com/GoogleAppsUpdates
* Google Antigravity          https://antigravity.google/blog  (scraped; no native feed)
* Gemini CLI                   https://geminicli.com/docs/changelogs/  (scraped; no native feed)

Entries are deduplicated across sources by canonical URL *or* normalized title,
so the same post arriving from more than one feed appears only once. Each entry
is tagged with its source via an Atom <category>. A rolling JSON cache keeps
history across hourly runs even when an upstream feed truncates.

Usage:
    python google_blogs.py          # fetch all sources, merge into cache
    python google_blogs.py --full   # ignore cache, rebuild from current feeds only

Output:
    feeds/feed_google.xml           # combined Atom feed
    cache/google_posts.json         # entry cache (rolling archive)
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import requests
import yaml
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

FEED_NAME = "google"
BLOG_URL = "https://blog.google/"
FEED_TITLE = "Google Blogs"
FEED_DESC = "Combined feed of Google's official blogs (The Keyword, Developers, Android, Chrome, Research, DeepMind, Cloud, and more)"
FEED_LANG = "en"
MAX_ENTRIES = 500  # many sources share one rolling archive

# Google Antigravity has no native feed: it's an Angular SPA whose blog index
# is a hardcoded slug list inside the JS bundle, with one Markdown file per post
# under /assets/blog-posts/<slug>.md (YAML front-matter + body). We discover the
# bundle name from the index HTML (it carries a content hash that changes on
# every deploy), pull the slug list out of it, then fetch each post.
ANTIGRAVITY_BASE = "https://antigravity.google"
ANTIGRAVITY_BLOG = f"{ANTIGRAVITY_BASE}/blog"
ANTIGRAVITY_LABEL = "Antigravity"
ANTIGRAVITY_EXCERPT = 600  # chars of body kept as the entry summary

# Gemini CLI release notes are a static Astro docs page: one <h2> per release,
# its text/id carrying the version and date ("Announcements: v0.45.0 - 2026-06-03").
GEMINICLI_URL = "https://geminicli.com/docs/changelogs/"
GEMINICLI_LABEL = "Gemini CLI"
GEMINICLI_EXCERPT = 600
_GEMINICLI_RE = re.compile(r"v(\d+\.\d+\.\d+)\s*[-\u2013]\s*(\d{4}-\d{2}-\d{2})")

# Query params that are pure tracking and should be stripped so the same
# article from different source feeds collapses to one canonical URL.
_TRACKING_KEYS = {
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
}


@dataclass(frozen=True)
class Source:
    """One Google feed to aggregate."""

    key: str    # short tag used in <category>
    label: str  # human label
    url: str


SOURCES: list[Source] = [
    Source("keyword", "The Keyword", "https://blog.google/rss/"),
    Source("keyword-pl", "Google Poland", "https://blog.google/intl/pl-pl/rss/"),
    Source("workspace", "Workspace Updates", "https://workspaceupdates.googleblog.com/atom.xml"),
    Source("developers", "Google Developers", "https://developers.googleblog.com/feed/"),
    Source("android", "Android Developers", "https://android-developers.googleblog.com/atom.xml"),
    Source("chrome", "Chrome for Developers", "https://developer.chrome.com/static/blog/feed.xml"),
    Source("chromium", "Chromium Blog", "https://blog.chromium.org/atom.xml"),
    Source("firebase", "Firebase", "https://firebase.blog/rss.xml"),
    Source("search-central", "Search Central", "https://feeds.feedburner.com/blogspot/amDG"),
    Source("search-docs", "Search Central Docs", "https://developers.google.com/search/updates/search_docs_updates.rss"),
    Source("search-status", "Search Status Dashboard", "https://status.search.google.com/en/feed.atom?hl=pl"),
    Source("waze", "Waze", "https://blog.google/waze/rss/"),
    Source("research", "Google Research", "https://research.google/blog/rss/"),
    Source("deepmind", "Google DeepMind", "https://deepmind.google/blog/rss.xml"),
    Source("cloud", "Google Cloud", "https://cloudblog.withgoogle.com/rss/"),
    Source("cloud-press", "Google Cloud Press", "https://www.googlecloudpresscorner.com/press-releases?pagetemplate=rss"),
    Source("apps-updates", "Workspace Updates", "https://feeds.feedburner.com/GoogleAppsUpdates"),
]


def canonical_link(url: str) -> str:
    """Normalize a URL so equivalent links dedupe: drop tracking query params
    (utm_*, gclid, ...). The fragment is preserved, since some sources (e.g. the
    Gemini CLI changelog) use per-entry #anchors on a single page."""
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
    """Lowercased, whitespace-collapsed title for cross-source dedupe."""
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def entry_date(entry) -> datetime | None:
    """Best-effort tz-aware UTC datetime from a feedparser entry."""
    for key in ("published_parsed", "updated_parsed"):
        struct = entry.get(key)
        if struct:
            return datetime(*struct[:6], tzinfo=timezone.utc)
    return None


def fetch_feed(src: Source):
    """Fetch and parse one source feed; return a feedparser result or None."""
    try:
        resp = requests.get(src.url, headers=DEFAULT_HEADERS, timeout=30)
        resp.raise_for_status()
        return feedparser.parse(resp.content)
    except Exception as exc:  # one dead source never kills the run
        logger.warning("[%s] fetch failed (%s); skipping this source", src.key, exc)
        return None


def parse_source(src: Source, parsed) -> list[dict]:
    """Normalize a parsed feed into the project's entry dicts."""
    entries: list[dict] = []
    for e in parsed.entries:
        try:
            link = canonical_link(e.get("feedburner_origlink") or e.get("link") or "")
            title = sanitize_xml((e.get("title") or "").strip())
            if not link or not title:
                continue
            entries.append(
                {
                    "title": title,
                    "link": link,
                    "date": entry_date(e) or stable_fallback_date(link),
                    "description": sanitize_xml(e.get("summary") or ""),
                    "source": src.label,
                }
            )
        except Exception as exc:  # one malformed item is skipped, not fatal
            logger.warning("[%s] skipping an entry due to error: %s", src.key, exc)
    logger.info("[%s] parsed %d entries", src.key, len(entries))
    return entries


def _antigravity_excerpt(body: str) -> str:
    """Reduce a Markdown post body to a short plain-text summary."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)            # drop images
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)         # links -> text
    text = re.sub(r"[#>*`_]", "", text)                          # strip md marks
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > ANTIGRAVITY_EXCERPT:
        text = text[: ANTIGRAVITY_EXCERPT - 1].rstrip() + "\u2026"
    return sanitize_xml(text)


def collect_antigravity() -> list[dict]:
    """Scrape the Google Antigravity blog (no native feed) into entry dicts."""
    entries: list[dict] = []
    try:
        index_html = requests.get(ANTIGRAVITY_BLOG, headers=DEFAULT_HEADERS, timeout=30).text
        bundle = re.search(r"(main-[A-Za-z0-9_]+\.js)", index_html)
        if not bundle:
            logger.warning("[antigravity] could not locate JS bundle; skipping source")
            return []
        bundle_js = requests.get(f"{ANTIGRAVITY_BASE}/{bundle.group(1)}", headers=DEFAULT_HEADERS, timeout=30).text
        m = re.search(r"BLOG_POST_SLUGS\s*=\s*\[([^\]]*)\]", bundle_js)
        slugs = re.findall(r'"([^"]+)"', m.group(1)) if m else []
        if not slugs:
            logger.warning("[antigravity] no slugs found in bundle; skipping source")
            return []
    except Exception as exc:
        logger.warning("[antigravity] index/bundle fetch failed (%s); skipping source", exc)
        return []

    for slug in slugs:
        try:
            resp = requests.get(f"{ANTIGRAVITY_BASE}/assets/blog-posts/{slug}.md", headers=DEFAULT_HEADERS, timeout=30)
            resp.raise_for_status()
            md = resp.content.decode("utf-8", errors="replace")
            fm = re.match(r"^\s*---\s*\n(.*?)\n---\s*\n(.*)$", md, re.S)
            if not fm:
                continue
            meta = yaml.safe_load(fm.group(1)) or {}
            title = sanitize_xml(str(meta.get("title", "")).strip())
            if not title:
                continue
            raw_date = meta.get("date")
            if isinstance(raw_date, datetime):
                date = raw_date.replace(tzinfo=timezone.utc) if raw_date.tzinfo is None else raw_date.astimezone(timezone.utc)
            else:
                date = stable_fallback_date(slug)
            link = f"{ANTIGRAVITY_BASE}/blog/{slug}"
            entries.append(
                {
                    "title": title,
                    "link": link,
                    "date": date,
                    "description": _antigravity_excerpt(fm.group(2)),
                    "content_type": "text",
                    "source": ANTIGRAVITY_LABEL,
                }
            )
        except Exception as exc:  # one bad post never kills the source
            logger.warning("[antigravity] skipping %s due to error: %s", slug, exc)
    logger.info("[antigravity] parsed %d entries", len(entries))
    return entries


def collect_geminicli() -> list[dict]:
    """Scrape the Gemini CLI release-notes page (no native feed) into entries."""
    entries: list[dict] = []
    try:
        resp = requests.get(GEMINICLI_URL, headers=DEFAULT_HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as exc:
        logger.warning("[geminicli] fetch failed (%s); skipping source", exc)
        return []

    for h2 in soup.find_all("h2"):
        try:
            m = _GEMINICLI_RE.search(h2.get_text(" ", strip=True))
            if not m:
                continue
            version, date_str = m.group(1), m.group(2)
            body_parts = []
            for sib in h2.find_next_siblings():
                if sib.name == "h2":
                    break
                body_parts.append(sib.get_text(" ", strip=True))
            body = re.sub(r"Section titled \u201c.*?\u201d", " ", " ".join(p for p in body_parts if p))
            body = re.sub(r"\s+", " ", body).strip()
            if len(body) > GEMINICLI_EXCERPT:
                body = body[: GEMINICLI_EXCERPT - 1].rstrip() + "\u2026"
            entries.append(
                {
                    "title": f"Gemini CLI v{version}",
                    "link": f"{GEMINICLI_URL}#{h2.get('id', '')}",
                    "date": datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc),
                    "description": sanitize_xml(body),
                    "content_type": "text",
                    "source": GEMINICLI_LABEL,
                }
            )
        except Exception as exc:  # one bad release never kills the source
            logger.warning("[geminicli] skipping a release due to error: %s", exc)
    logger.info("[geminicli] parsed %d entries", len(entries))
    return entries


def collect() -> list[dict]:
    """Fetch every source and dedupe across sources by canonical URL *or*
    normalized title (first occurrence wins; feed sources before scraped ones)."""
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

    for src in SOURCES:
        parsed = fetch_feed(src)
        if parsed:
            add(parse_source(src, parsed))
    # Non-feed (scraped) sources go through the same dedupe.
    add(collect_antigravity())
    add(collect_geminicli())

    logger.info("Collected %d unique entries across %d sources", len(out), len(SOURCES) + 2)
    return out


def generate_atom_feed(articles, feed_name=FEED_NAME):
    """Build an Atom FeedGenerator from the article list."""
    fg = FeedGenerator()
    fg.id(BLOG_URL)
    fg.title(FEED_TITLE)
    fg.subtitle(FEED_DESC)
    setup_feed_links(fg, BLOG_URL, feed_name)
    fg.language(FEED_LANG)
    fg.author({"name": "Google"})

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
    """Write the feed to feeds/feed_<name>.xml in Atom format."""
    output_file = get_feeds_dir() / f"feed_{feed_name}.xml"
    fg.atom_file(str(output_file), pretty=True)
    logger.info(f"Saved Atom feed to {output_file}")
    return output_file


def main(full=False) -> bool:
    """Aggregate every source feed, merge with cache, and write the Atom feed."""
    new_articles = collect()
    if not new_articles:
        logger.error("No entries collected from any source — skipping write to preserve the last good feed")
        return False

    if full:
        logger.info("Full reset requested — ignoring existing cache")
        cached = []
    else:
        cache = load_cache(FEED_NAME)
        cached = deserialize_entries(cache.get("entries", []), date_field="date")

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
    parser = argparse.ArgumentParser(description="Generate the combined Google blogs Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from current feeds only")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
