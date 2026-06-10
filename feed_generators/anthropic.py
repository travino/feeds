"""Anthropic feed generator.

Aggregates Anthropic's three article streams into one **Atom** feed written to
``feeds/feed_anthropic.xml``:

    - Anthropic Newsroom      https://www.anthropic.com/news
    - Anthropic Research      https://www.anthropic.com/research
    - Anthropic Engineering   https://www.anthropic.com/engineering

The listing pages render article cards in static HTML (no JS), so a plain
``requests`` fetch is enough. Titles and summaries are read from each article's
``og:title`` / ``og:description`` meta tags; the publish date comes from the
listing card. History accumulates across hourly runs via the shared JSON cache
(``cache/anthropic_posts.json``); only links not already cached trigger a
per-article metadata fetch, so steady-state runs are cheap.
"""

import argparse
import re
import sys
import time

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

FEED_NAME = "anthropic"
BLOG_URL = "https://www.anthropic.com/"

# (source label, listing URL, site base, href prefix)
SOURCES = [
    ("Anthropic Newsroom", "https://www.anthropic.com/news", "https://www.anthropic.com", "/news/"),
    ("Anthropic Research", "https://www.anthropic.com/research", "https://www.anthropic.com", "/research/"),
    ("Anthropic Engineering", "https://www.anthropic.com/engineering", "https://www.anthropic.com", "/engineering/"),
]

# The research listing also links team/index pages, which are not articles.
RESEARCH_SKIP = re.compile(r"^/research/(team/|$)")

# red.anthropic.com is a static blog; posts live under /<year>/<slug>/.
RED_BASE = "https://red.anthropic.com/"
RED_LABEL = "Anthropic Red"
RED_HREF_RE = re.compile(r"^(?:\./)?(20\d\d)/[^?#]+")

# Human dates in cards, e.g. "May 28, 2026" / "Apr 08, 2026".
DATE_RE = re.compile(r"([A-Z][a-z]{2,8}\.?\s+\d{1,2},\s+\d{4})")

# Default og:description served site-wide on some anthropic.com pages; not a
# real per-article summary, so we drop it.
ANTHROPIC_BOILERPLATE = "Anthropic is an AI safety and research company"

# Polite delay between per-article metadata fetches.
SLEEP_BETWEEN = 0.4

# Cap the merged feed so the committed XML stays a reasonable size.
MAX_ENTRIES = 100


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
    slash or index.html. Query and fragment are PRESERVED, since anchor-based
    entries can be distinguished only by their fragment."""
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


def title_from_slug(href):
    """Last-resort title derived from the URL slug."""
    slug = href.rstrip("/").split("/")[-1]
    return slug.replace("-", " ").replace("_", " ").strip().capitalize()


def _meta(soup, *keys):
    for key in keys:
        tag = soup.find("meta", property=key) or soup.find("meta", attrs={"name": key})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


def fetch_article_meta(url):
    """Return {'title', 'summary'} for an anthropic.com article via meta tags."""
    title = summary = None
    try:
        soup = BeautifulSoup(fetch_page(url), "html.parser")
        title = _meta(soup, "og:title", "twitter:title")
        if title:
            title = re.split(r"\s[\\|]\s", title)[0].strip()
        summary = _meta(soup, "og:description", "description")
        if summary and summary.startswith(ANTHROPIC_BOILERPLATE):
            summary = None
    except Exception as e:
        logger.warning(f"Could not fetch article meta for {url}: {e}")
    time.sleep(SLEEP_BETWEEN)
    return {"title": title, "summary": summary}


def scrape_source(label, listing_url, base, prefix, known_links):
    """Scrape an Anthropic listing page; skip links already in the cache."""
    entries = []
    try:
        soup = BeautifulSoup(fetch_page(listing_url), "html.parser")
    except Exception as e:
        logger.warning(f"Could not fetch {listing_url}: {e}")
        return entries

    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith(prefix) or href == prefix or href in seen:
            continue
        if prefix == "/research/" and RESEARCH_SKIP.match(href):
            continue
        seen.add(href)

        text = a.get_text(" ", strip=True)
        m = DATE_RE.search(text)
        if not m:  # cards without a date aren't real articles
            continue
        date_obj = parse_date(m.group(1))
        link = href if href.startswith("http") else base + href

        if link in known_links:
            continue  # already cached, no need to refetch metadata

        meta = fetch_article_meta(link)
        title = sanitize_xml(meta["title"] or title_from_slug(href))
        summary = sanitize_xml(meta["summary"] or title)
        entries.append({
            "title": title,
            "link": link,
            "date": date_obj,
            "description": summary,
            "source": label,
        })
        logger.info(f"  [{label}] {title}")
    return entries


def fetch_red_article(url):
    """Return {'title', 'date', 'summary'} for a red.anthropic.com post."""
    title = summary = None
    date_obj = None
    try:
        soup = BeautifulSoup(fetch_page(url), "html.parser")
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(" ", strip=True)
        # Publish date is the first full date appearing after the title.
        scope = h1.find_all_next(string=DATE_RE) if h1 else soup.find_all(string=DATE_RE)
        for s in scope:
            m = DATE_RE.search(str(s))
            if m:
                date_obj = parse_date(m.group(1))
                break
        summary = _meta(soup, "og:description", "description")
    except Exception as e:
        logger.warning(f"Could not fetch red article {url}: {e}")
    time.sleep(SLEEP_BETWEEN)
    return {"title": title, "date": date_obj, "summary": summary}


def scrape_red(known_links):
    """Scrape the red.anthropic.com index; fetch metadata for new posts only."""
    entries = []
    try:
        soup = BeautifulSoup(fetch_page(RED_BASE), "html.parser")
    except Exception as e:
        logger.warning(f"Could not fetch {RED_BASE}: {e}")
        return entries

    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http"):
            continue  # external / cross-site links in the index
        if not RED_HREF_RE.match(href):
            continue
        link = RED_BASE + href.lstrip("./")
        if link in seen:
            continue
        seen.add(link)
        if link in known_links:
            continue

        meta = fetch_red_article(link)
        title = sanitize_xml(meta["title"] or title_from_slug(href))
        summary = sanitize_xml(meta["summary"] or title)
        entries.append({
            "title": title,
            "link": link,
            "date": meta["date"],
            "description": summary,
            "source": RED_LABEL,
        })
        logger.info(f"  [{RED_LABEL}] {title}")
    return entries


def scrape_all(known_links):
    """Collect new entries from every source, skipping already-cached links."""
    new_entries = []
    for label, listing, base, prefix in SOURCES:
        logger.info(f"Scraping {label} ...")
        new_entries += scrape_source(label, listing, base, prefix, known_links)
    logger.info(f"Scraping {RED_LABEL} ...")
    new_entries += scrape_red(known_links)
    return new_entries


def generate_atom_feed(articles, feed_name=FEED_NAME):
    """Build an Atom FeedGenerator from the merged article list."""
    fg = FeedGenerator()
    fg.id(f"https://www.anthropic.com/{feed_name}")
    fg.title("Anthropic")
    fg.subtitle("Anthropic Newsroom, Research, and Engineering posts in one feed.")
    setup_feed_links(fg, BLOG_URL, feed_name)
    fg.language("en")
    fg.author({"name": "Anthropic"})

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
    """Write the feed to feeds/feed_<name>.xml in Atom format."""
    output_file = get_feeds_dir() / f"feed_{feed_name}.xml"
    fg.atom_file(str(output_file), pretty=True)
    logger.info(f"Saved Atom feed to {output_file}")
    return output_file


def main(full=False):
    """Scrape every source, merge with cache, and write the Atom feed."""
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
    parser = argparse.ArgumentParser(description="Generate the Anthropic Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
