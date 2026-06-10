"""Groq feed generator.

Aggregates Groq's update sources into one **Atom** feed written to
``feeds/feed_groq.xml``:

    - Groq Blog              https://groq.com/blog                              (HTML)
    - Groq Newsroom          https://groq.com/newsroom                          (HTML)
    - Groq Changelog         https://groq.com/changelog                         (HTML)
    - Changelog repo commits https://github.com/groq/groq-changelog/commits/main.atom (native Atom)

Source handling:
  * Blog / Newsroom — server-rendered listing cards: an ``<a href="/blog/...">``
    (or ``/newsroom/...``) whose surrounding card carries an ``<h2-4>`` title
    and a "Apr 09, 2026" date. The featured hero card has no date; those
    entries get a deterministic ``stable_fallback_date`` so they don't churn.
  * Changelog — entries are ``<h2>`` blocks (no ids) with an abbreviated date
    nearby and the body following; links get a synthetic ``#<slug>`` fragment
    for stable dedupe (fragments are the only differentiator — preserve them).
    The page lags behind the changelog repo, hence the commits feed below.
  * Commits — the groq/groq-changelog GitHub Atom feed; coarse batch commits
    ("Q1 2026 changelog entries"), but fresher than the website. Parsed as
    native Atom entries.

History accumulates across runs via the shared JSON cache
(``cache/groq_posts.json``); entries dedupe by link, then cross-source by
normalized URL/title.
"""

import argparse
import re
import sys

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

FEED_NAME = "groq"
BLOG_URL = "https://groq.com/"

# (label, listing URL, site base, href prefix)
CARD_SOURCES = [
    ("Groq Blog", "https://groq.com/blog", "https://groq.com", "/blog/"),
    ("Groq Newsroom", "https://groq.com/newsroom", "https://groq.com", "/newsroom/"),
]

CHANGELOG_URL = "https://groq.com/changelog"
COMMITS_ATOM_URL = "https://github.com/groq/groq-changelog/commits/main.atom"
COMMITS_LABEL = "Groq Changelog commits"

DATE_RE = re.compile(
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December"
    r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2},?\s+\d{4})"
)

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


def title_from_slug(href):
    slug = href.rstrip("/").split("/")[-1]
    return slug.replace("-", " ").replace("_", " ").strip().capitalize()


# --------------------------------------------------------------------------- #
# Blog / Newsroom listing cards
# --------------------------------------------------------------------------- #


def scrape_cards(label, listing_url, base, prefix, known_links):
    entries = []
    html = _get_html(listing_url)
    if html is None:
        return entries
    soup = BeautifulSoup(html, "html.parser")

    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith(prefix) or href.rstrip("/") == prefix.rstrip("/") or href in seen:
            continue
        seen.add(href)
        link = base + href
        if link in known_links:
            continue
        try:
            # Climb to the smallest container whose text carries a date.
            card, card_text, m = a, a.get_text(" ", strip=True), None
            for _ in range(5):
                m = DATE_RE.search(card_text)
                if m:
                    break
                if not card.parent:
                    break
                card = card.parent
                card_text = card.get_text(" ", strip=True)

            heading = card.find(["h2", "h3", "h4"]) if hasattr(card, "find") else None
            title = heading.get_text(" ", strip=True) if heading else title_from_slug(href)
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
            logger.warning(f"  [{label}] skipping malformed card {href}: {e}")
    return entries


# --------------------------------------------------------------------------- #
# Changelog page (h2 blocks, no anchors, date in the entry container)
# --------------------------------------------------------------------------- #


def scrape_changelog(known_links):
    label = "Groq Changelog"
    entries = []
    html = _get_html(CHANGELOG_URL)
    if html is None:
        return entries
    soup = BeautifulSoup(html, "html.parser")

    main = soup.find("main") or soup
    headings = [h for h in main.find_all("h2") if len(h.get_text(strip=True)) > 3]
    if not headings:
        logger.warning(f"  [{label}] no changelog headings matched — layout may have changed")
        return entries

    for h in headings:
        try:
            title = re.sub(r"\s+", " ", h.get_text(" ", strip=True))
            link = f"{CHANGELOG_URL}#{slugify(title)}"
            if link in known_links:
                continue

            # The date and body live in the entry container around the h2;
            # climb until the surrounding text carries a date.
            container, text, m = h, h.get_text(" ", strip=True), None
            for _ in range(5):
                m = DATE_RE.search(text)
                if m:
                    break
                if not container.parent:
                    break
                container = container.parent
                text = container.get_text(" ", strip=True)
            date_obj = parse_date(m.group(1)) if m else None
            if date_obj is None:
                # Real changelog entries always carry a date; a dateless h2 is
                # page furniture (e.g. the "Subscribe for updates" box).
                logger.info(f"  [{label}] skipping dateless heading: {title}")
                continue

            # Body: drop the title/date scaffolding, keep the prose.
            desc = text
            desc = desc.replace(title, " ", 1)
            if m:
                desc = desc.replace(m.group(1), " ", 1)
            desc = re.sub(r"\b(Plus|Minus) icon\b", " ", desc)
            desc = re.sub(r"\s+", " ", desc).strip()[:DESC_LIMIT]
            entries.append({
                "title": sanitize_xml(title),
                "link": link,
                "date": date_obj,
                "description": sanitize_xml(desc) or sanitize_xml(title),
                "source": label,
            })
            logger.info(f"  [{label}] {title}")
        except Exception as e:
            logger.warning(f"  [{label}] skipping malformed item: {e}")
    return entries


# --------------------------------------------------------------------------- #
# groq/groq-changelog commits (native GitHub Atom)
# --------------------------------------------------------------------------- #


def scrape_commits_atom(known_links):
    label = COMMITS_LABEL
    entries = []
    xml = _get_html(COMMITS_ATOM_URL)
    if xml is None:
        return entries
    try:
        soup = BeautifulSoup(xml, "xml")
    except Exception as e:
        logger.warning(f"Could not parse {COMMITS_ATOM_URL}: {e}")
        return entries

    for item in soup.find_all("entry"):
        try:
            link_el = item.find("link")
            link = link_el.get("href") if link_el else ""
            if not link or link in known_links:
                continue
            title_el = item.find("title")
            title = sanitize_xml(title_el.get_text(strip=True)) if title_el else label
            upd_el = item.find("updated")
            date_obj = parse_date(upd_el.get_text(strip=True)) if upd_el else None
            entries.append({
                "title": title,
                "link": link,
                "date": date_obj,
                "description": title,
                "source": label,
            })
            logger.info(f"  [{label}] {title}")
        except Exception as e:
            logger.warning(f"  [{label}] skipping malformed entry: {e}")
    return entries


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def scrape_all(known_links):
    new_entries = []
    for label, url, base, prefix in CARD_SOURCES:
        logger.info(f"Scraping {label} ...")
        new_entries += scrape_cards(label, url, base, prefix, known_links)
    logger.info("Scraping Groq Changelog ...")
    new_entries += scrape_changelog(known_links)
    logger.info(f"Scraping {COMMITS_LABEL} ...")
    new_entries += scrape_commits_atom(known_links)
    return new_entries


def generate_atom_feed(articles, feed_name=FEED_NAME):
    fg = FeedGenerator()
    fg.id(f"https://groq.com/{feed_name}")
    fg.title("Groq")
    fg.subtitle(
        "Groq updates: Blog, Newsroom, the GroqCloud changelog, and commits to "
        "the groq-changelog repo."
    )
    setup_feed_links(fg, BLOG_URL, feed_name)
    fg.language("en")
    fg.author({"name": "Groq"})

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
    parser = argparse.ArgumentParser(description="Generate the Groq Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
