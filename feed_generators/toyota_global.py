"""Toyota Global feed generator.

Aggregates Toyota's public article streams into one **Atom** feed written to
``feeds/feed_toyota_global.xml``:

    - Toyota USA Newsroom        https://pressroom.toyota.com/   (native RSS feed)
    - Newsroom Toyota Europe     https://newsroom.toyota.eu/     (native presspage RSS feed)
    - Toyota Global Newsroom      https://global.toyota/en/       (native all-news RSS feed)
    - Toyota Connected            https://www.toyotaconnected.com/ (HTML "Insights" listing)
    - Toyota Research Institute   https://www.tri.global/         (via Google News RSS proxy)

The three newsrooms publish usable native feeds and are consumed directly.
Toyota Connected exposes an "Insights" listing whose article pages carry a
JSON-LD date. The Toyota Research Institute site sits behind a TLS-level block that refuses
automated clients outright, so — as with the Reuters feed — its recent coverage
is pulled from the Google News RSS proxy instead. Each source is fetched
independently and wrapped so one failing source is skipped, never fatal. History
accumulates across hourly runs via the shared JSON cache
(``cache/toyota_global_posts.json``); only links not already cached trigger a
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
    DEFAULT_HEADERS,
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

FEED_NAME = "toyota_global"
BLOG_URL = "https://pressroom.toyota.com/"

# Native RSS / Atom feeds — parsed directly, no scraping needed.
NATIVE_FEEDS = [
    ("Toyota USA Newsroom", "https://pressroom.toyota.com/feed/"),
    ("Newsroom Toyota Europe", "https://newsroom.toyota.eu/feed/"),
    ("Toyota Global Newsroom", "https://global.toyota/export/en/allnews_rss.xml"),
]

# Toyota Connected: HTML "Insights" listing. Article URLs are /insights/<slug>;
# category and pagination pages are excluded.
TC_LISTING = "https://www.toyotaconnected.com/insights"
TC_BASE = "https://www.toyotaconnected.com"
TC_LINK_RE = re.compile(r"^https://www\.toyotaconnected\.com/insights/(?!categories/|p\d+$)[\w-]+$")

# Toyota Research Institute: the site blocks automation at the TLS layer, so we
# republish recent coverage from the Google News RSS proxy (same approach as the
# Reuters feed). We try query variants in order until one returns items.
TRI_LABEL = "Toyota Research Institute"
TRI_SOURCE_URLS = [
    'https://news.google.com/rss/search?q=when:30d+%22Toyota+Research+Institute%22&hl=en-US&gl=US&ceid=US:en',
    'https://news.google.com/rss/search?q=%22Toyota+Research+Institute%22&hl=en-US&gl=US&ceid=US:en',
]
GNEWS_HEADERS = {
    **DEFAULT_HEADERS,
    "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Polite delay between per-article metadata fetches.
SLEEP_BETWEEN = 0.4

# Cap the merged feed so the committed XML stays a reasonable size.
MAX_ENTRIES = 100


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def parse_date(date_str):
    """Parse a date string into a UTC datetime, or None on failure."""
    if not date_str:
        return None
    try:
        dt = date_parser.parse(date_str.replace(".", " "))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.UTC)
        return dt.astimezone(pytz.UTC)
    except (ValueError, TypeError, OverflowError) as e:
        logger.warning(f"Could not parse date '{date_str}': {e}")
        return None


def fetch_text(url, retries=3, backoff=2.0, headers=None):
    """Fetch a URL's text body with retries; return None on failure (never raise)."""
    for attempt in range(1, retries + 1):
        try:
            return fetch_page(url, headers=headers)
        except Exception as e:
            logger.warning(f"Fetch failed for {url} (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(backoff * attempt)
    return None


def clean_description(html, fallback=""):
    """Strip HTML to a plain-text summary, sanitized and length-capped."""
    if not html:
        return sanitize_xml(fallback)
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 500:
        text = text[:497].rstrip() + "..."
    return sanitize_xml(text or fallback)


def og_meta(soup, *keys):
    """Return the first matching og:/meta content value on a parsed page."""
    for key in keys:
        tag = soup.find("meta", property=key) or soup.find("meta", attrs={"name": key})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


def title_from_slug(href):
    """Last-resort title derived from a URL slug."""
    slug = href.rstrip("/").split("/")[-1].split(".")[0]
    return slug.replace("-", " ").replace("_", " ").strip().capitalize()


# ---------------------------------------------------------------------------
# Source: native RSS / Atom feeds
# ---------------------------------------------------------------------------


def parse_native_feed(xml, label):
    """Parse an RSS 2.0 or Atom feed into entry dicts. Handles both shapes."""
    entries = []
    soup = BeautifulSoup(xml, "xml")
    items = soup.find_all("item") or soup.find_all("entry")
    for item in items:
        try:
            title_el = item.find("title")
            title = sanitize_xml(title_el.get_text(strip=True)) if title_el else None

            # RSS <link> carries the URL as text; Atom <link> carries it in href.
            link = None
            link_el = item.find("link")
            if link_el is not None:
                link = (link_el.get_text(strip=True) or link_el.get("href") or "").strip()
            if not link:
                for la in item.find_all("link"):
                    if la.get("rel") in (None, "alternate") and la.get("href"):
                        link = la["href"].strip()
                        break
            if not title or not link:
                continue

            date_el = (
                item.find("pubDate")
                or item.find("published")
                or item.find("updated")
                or item.find("date")
            )
            date_obj = parse_date(date_el.get_text(strip=True)) if date_el else None

            desc_el = (
                item.find("description")
                or item.find("summary")
                or item.find("encoded")
                or item.find("content")
            )
            description = clean_description(desc_el.get_text() if desc_el else "", fallback=title)

            entries.append({
                "title": title,
                "link": link,
                "date": date_obj,
                "description": description,
                "source": label,
            })
        except Exception as e:
            logger.warning(f"[{label}] skipped a malformed item: {e}")
    logger.info(f"[{label}] parsed {len(entries)} entries")
    return entries


def collect_native_feed(label, url):
    xml = fetch_text(url, headers={**DEFAULT_HEADERS, "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8"})
    if not xml:
        logger.warning(f"[{label}] fetch failed — skipping this source")
        return []
    return parse_native_feed(xml, label)


# ---------------------------------------------------------------------------
# Source: Toyota Connected (Insights listing)
# ---------------------------------------------------------------------------


def collect_toyota_connected(known_links):
    """Scrape the Toyota Connected Insights listing; fetch JSON-LD date +
    og:title for links we haven't cached yet."""
    label = "Toyota Connected"
    html = fetch_text(TC_LISTING)
    if not html:
        logger.warning(f"[{label}] fetch failed — skipping this source")
        return []

    soup = BeautifulSoup(html, "html.parser")
    links = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/insights/"):
            href = TC_BASE + href
        href = href.split("?")[0].rstrip("/")
        if TC_LINK_RE.match(href) and href not in seen:
            seen.add(href)
            links.append(href)

    entries = []
    for link in links:
        try:
            if link in known_links:
                continue
            page = fetch_text(link)
            if not page:
                continue
            psoup = BeautifulSoup(page, "html.parser")

            title = og_meta(psoup, "og:title", "twitter:title")
            if title:
                title = re.split(r"\s+\|\s+", title)[0].strip()

            date_obj = None
            for sc in psoup.find_all("script", type="application/ld+json"):
                m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', sc.string or "")
                if m:
                    date_obj = parse_date(m.group(1))
                    break
            if date_obj is None:
                date_obj = parse_date(og_meta(psoup, "article:published_time"))

            summary = og_meta(psoup, "og:description", "description")
            time.sleep(SLEEP_BETWEEN)

            title = sanitize_xml(title or title_from_slug(link))
            entries.append({
                "title": title,
                "link": link,
                "date": date_obj,
                "description": clean_description(summary, fallback=title),
                "source": label,
            })
            logger.info(f"  [{label}] {title}")
        except Exception as e:
            logger.warning(f"[{label}] skipped {link}: {e}")
    logger.info(f"[{label}] collected {len(entries)} new entries")
    return entries


# ---------------------------------------------------------------------------
# Source: Toyota Research Institute (Google News proxy)
# ---------------------------------------------------------------------------


def collect_tri():
    """Pull recent Toyota Research Institute coverage from the Google News RSS
    proxy. Links point at Google News redirects (the TRI site itself blocks
    automated clients)."""
    label = TRI_LABEL
    xml = None
    for url in TRI_SOURCE_URLS:
        candidate = fetch_text(url, headers=GNEWS_HEADERS)
        if candidate and "<item>" in candidate:
            xml = candidate
            break
    if not xml:
        logger.warning(f"[{label}] no items from Google News proxy — skipping this source")
        return []

    entries = []
    soup = BeautifulSoup(xml, "xml")
    seen = set()
    for item in soup.find_all("item"):
        try:
            title_el = item.find("title")
            link_el = item.find("link")
            if not title_el or not link_el:
                continue
            title = sanitize_xml(title_el.get_text(strip=True))
            link = link_el.get_text(strip=True)
            if not title or not link or link in seen:
                continue
            seen.add(link)

            # Google News appends " - Publisher" to titles; drop the suffix.
            source_el = item.find("source")
            if source_el:
                suffix = f" - {source_el.get_text(strip=True)}"
                if title.endswith(suffix):
                    title = title[: -len(suffix)].strip()

            pub_el = item.find("pubDate")
            date_obj = parse_date(pub_el.get_text(strip=True)) if pub_el else None

            entries.append({
                "title": title,
                "link": link,
                "date": date_obj,
                "description": title,
                "source": label,
            })
        except Exception as e:
            logger.warning(f"[{label}] skipped an item: {e}")
    logger.info(f"[{label}] collected {len(entries)} entries")
    return entries


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def collect_all(known_links):
    """Collect entries from every source. A failure in one source is logged and
    skipped so the others still contribute."""
    entries = []
    for label, url in NATIVE_FEEDS:
        logger.info(f"Fetching native feed: {label}")
        try:
            entries += collect_native_feed(label, url)
        except Exception as e:
            logger.warning(f"[{label}] unexpected error: {e}")

    logger.info("Scraping Toyota Connected ...")
    try:
        entries += collect_toyota_connected(known_links)
    except Exception as e:
        logger.warning(f"[Toyota Connected] unexpected error: {e}")

    logger.info("Fetching Toyota Research Institute (Google News proxy) ...")
    try:
        entries += collect_tri()
    except Exception as e:
        logger.warning(f"[{TRI_LABEL}] unexpected error: {e}")

    return entries


def generate_atom_feed(articles, feed_name=FEED_NAME):
    """Build an Atom FeedGenerator from the merged article list."""
    fg = FeedGenerator()
    fg.id(f"{BLOG_URL}#{feed_name}")
    fg.title("Toyota Global")
    fg.subtitle("Toyota news from the USA, Europe, the global newsroom, Toyota Connected, and Toyota Research Institute, in one feed.")
    setup_feed_links(fg, BLOG_URL, feed_name)
    fg.language("en")
    fg.author({"name": "Toyota"})

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
    """Collect every source, merge with cache, and write the Atom feed."""
    if full:
        logger.info("Full reset requested — ignoring existing cache")
        cached = []
    else:
        cache = load_cache(FEED_NAME)
        cached = deserialize_entries(cache.get("entries", []), date_field="date")

    known_links = {e["link"] for e in cached}
    new_articles = collect_all(known_links)

    if not new_articles and not cached:
        logger.warning("No articles collected — skipping write to avoid an empty feed")
        return False

    merged = merge_entries(new_articles, cached, id_field="link", date_field="date")
    merged = sort_posts_for_feed(merged, date_field="date")

    # Keep full history in the cache so already-seen links are never re-evaluated
    # on later runs; only the rendered feed is capped to the newest MAX_ENTRIES.
    save_cache(FEED_NAME, merged)

    feed_items = merged[-MAX_ENTRIES:] if len(merged) > MAX_ENTRIES else merged

    fg = generate_atom_feed(feed_items)
    save_atom_feed(fg)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the Toyota Global Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
