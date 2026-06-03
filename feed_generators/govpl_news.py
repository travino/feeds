"""Gov.pl news feed generator.

Aggregates several Polish government news/announcement listings into one
**Atom** feed at ``feeds/feed_govpl_news.xml``. Sources (all gov.pl):

    - KPRM (Premier)            /web/premier/wydarzenia
    - Profil Zaufany           /web/profilzaufany/aktualnosci
    - Baza wiedzy              /web/baza-wiedzy/aktualnosci
    - Ministerstwo Cyfryzacji  /web/cyfryzacja/wiadomosci
    - Ministerstwo Zdrowia     /web/zdrowie/wiadomosci
    - Obrona Narodowa (MON)    /web/obrona-narodowa/aktualnosci5
    - Dyplomacja (MSZ)         /web/dyplomacja/aktualnosci
    - RCB (komunikaty)         /web/rcb/komunikaty

gov.pl publishes no native feed. Every listing is server-rendered HTML sharing
one template: a ``.art-prev`` block of ``<li>`` items, each with a title, an
article link, and a DD.MM.YYYY date. So a single scraper handles all sources.

curl_cffi Chrome impersonation is used because gov.pl TLS-fingerprints plain
clients. The article lead (og:description) lives on the article page, so it is
fetched once per *new* link only; cached links are never re-fetched. Each
source is wrapped so one failure is skipped, never fatal.

(info.mobywatel.gov.pl was considered but excluded: a JS-rendered SPA with no
markup, no feed, and no API -- nothing to parse without a browser.)
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

FEED_NAME = "govpl_news"
BLOG_URL = "https://www.gov.pl/"
BASE = "https://www.gov.pl"
MAX_ENTRIES = 150

# label, listing URL
SOURCES = [
    ("KPRM", "https://www.gov.pl/web/premier/wydarzenia"),
    ("Profil Zaufany", "https://www.gov.pl/web/profilzaufany/aktualnosci"),
    ("Baza wiedzy", "https://www.gov.pl/web/baza-wiedzy/aktualnosci"),
    ("Min. Cyfryzacji", "https://www.gov.pl/web/cyfryzacja/wiadomosci"),
    ("Min. Zdrowia", "https://www.gov.pl/web/zdrowie/wiadomosci"),
    ("MON", "https://www.gov.pl/web/obrona-narodowa/aktualnosci5"),
    ("MSZ", "https://www.gov.pl/web/dyplomacja/aktualnosci"),
    ("RCB", "https://www.gov.pl/web/rcb/komunikaty"),
]

DATE_RE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")
SLEEP_BETWEEN = 0.4


def fetch_text(url, retries=3, backoff=2.0):
    """Fetch via curl_cffi Chrome impersonation; None on failure (never raise)."""
    try:
        from curl_cffi import requests as creq
    except ImportError:
        creq = None
    for attempt in range(1, retries + 1):
        try:
            if creq is not None:
                resp = creq.get(url, impersonate="chrome", timeout=30)
                resp.raise_for_status()
                return resp.text
            from utils import fetch_page
            return fetch_page(url)
        except Exception as e:
            logger.warning(f"Fetch failed for {url} (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(backoff * attempt)
    return None


def parse_date(date_str):
    """DD.MM.YYYY -> UTC datetime, or None."""
    if not date_str:
        return None
    try:
        dt = date_parser.parse(date_str, dayfirst=True)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.UTC)
        return dt.astimezone(pytz.UTC)
    except (ValueError, TypeError, OverflowError):
        return None


def clean_description(text, fallback=""):
    if not text:
        return sanitize_xml(fallback)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 500:
        text = text[:497].rstrip() + "..."
    return sanitize_xml(text or fallback)


def fetch_lead(url):
    """og:description for a new article; '' if unavailable."""
    page = fetch_text(url, retries=2)
    if not page:
        return ""
    s = BeautifulSoup(page, "html.parser")
    og = s.find("meta", property="og:description") or s.find("meta", attrs={"name": "description"})
    return og["content"].strip() if og and og.get("content") else ""


def collect_source(label, listing_url, known_links):
    html = fetch_text(listing_url)
    if not html:
        logger.warning(f"[{label}] fetch failed -- skipping this source")
        return []
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one(".art-prev")
    if not container:
        logger.warning(f"[{label}] no .art-prev block found -- structure may have changed")
        return []

    entries = []
    for li in container.select("li"):
        try:
            a = li.find("a", href=True)
            if not a:
                continue
            title = sanitize_xml(a.get_text(" ", strip=True))
            href = a["href"].split("?")[0].split("#")[0]
            if not title or not href:
                continue
            link = href if href.startswith("http") else BASE + href

            m = DATE_RE.search(li.get_text(" ", strip=True))
            date_obj = parse_date(m.group(1)) if m else None

            if link in known_links:
                continue  # cached; no per-article fetch
            description = clean_description(fetch_lead(link), fallback=title)
            time.sleep(SLEEP_BETWEEN)

            entries.append({
                "title": title,
                "link": link,
                "date": date_obj,
                "description": description,
                "source": label,
            })
            logger.info(f"  [{label}] {title}")
        except Exception as e:
            logger.warning(f"[{label}] skipped a malformed item: {e}")
    logger.info(f"[{label}] collected {len(entries)} new entries")
    return entries


def collect_all(known_links):
    entries = []
    for label, url in SOURCES:
        logger.info(f"Scraping {label} ...")
        try:
            entries += collect_source(label, url, known_links)
        except Exception as e:
            logger.warning(f"[{label}] unexpected error: {e}")
    return entries


def generate_atom_feed(articles, feed_name=FEED_NAME):
    fg = FeedGenerator()
    fg.id(f"{BLOG_URL}#{feed_name}")
    fg.title("Gov.pl")
    fg.subtitle("Wiadomosci i komunikaty z gov.pl -- KPRM, Cyfryzacja, Zdrowie, MON, MSZ, RCB, Profil Zaufany, Baza wiedzy -- w jednym feedzie.")
    setup_feed_links(fg, BLOG_URL, feed_name)
    fg.language("pl")
    fg.author({"name": "gov.pl"})

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
        logger.info("Full reset requested -- ignoring existing cache")
        cached = []
    else:
        cache = load_cache(FEED_NAME)
        cached = deserialize_entries(cache.get("entries", []), date_field="date")

    known_links = {e["link"] for e in cached}
    new_articles = collect_all(known_links)

    if not new_articles and not cached:
        logger.warning("No articles collected -- skipping write to avoid an empty feed")
        return False

    merged = merge_entries(new_articles, cached, id_field="link", date_field="date")
    merged = sort_posts_for_feed(merged, date_field="date")
    save_cache(FEED_NAME, merged)

    feed_items = merged[-MAX_ENTRIES:] if len(merged) > MAX_ENTRIES else merged
    save_atom_feed(generate_atom_feed(feed_items))
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the Gov.pl Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
