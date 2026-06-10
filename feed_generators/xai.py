"""xAI feed generator.

Aggregates xAI's update sources into one **Atom** feed written to
``feeds/feed_xai.xml``:

    - xAI News               https://x.ai/news                          (HTML)
    - Grok Build changelog   https://x.ai/build/changelog               (HTML)
    - xAI API release notes  https://docs.x.ai/developers/release-notes (Mintlify .md)

Source handling:
  * News — server-rendered listing cards: ``<a href="/news/...">`` with an
    ``<h1-3>`` title and a "Jun 3, 2026" date node inside the card; a card
    with no heading falls back to a slug-derived title. x.ai 403s plain
    requests, so fetches go through curl_cffi Chrome impersonation.
  * Grok Build changelog — each release is an ``<h2 id="v<ver>-<YYYY-MM-DD>">``,
    so the anchor carries both a stable fragment and the date. The body is the
    text up to the next ``<h2>``.
  * API release notes — fetched as Mintlify raw markdown (``<path>.md``),
    organized as ``## <Month>`` (no year, newest first) containing ``###``
    feature sections. The year is inferred by rolling back whenever the month
    jumps upward while walking down; entries are dated to the 1st of their
    month and linked by the Mintlify heading anchor (fragments are the only
    differentiator between entries — preserve them).

History accumulates across runs via the shared JSON cache
(``cache/xai_posts.json``); entries dedupe by link, then cross-source by
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

FEED_NAME = "xai"
BLOG_URL = "https://x.ai/news"

NEWS_URL = "https://x.ai/news"
NEWS_BASE = "https://x.ai"
BUILD_CHANGELOG_URL = "https://x.ai/build/changelog"
RELEASE_NOTES_URL = "https://docs.x.ai/developers/release-notes"
RELEASE_NOTES_MD_URL = "https://docs.x.ai/developers/release-notes.md"

DATE_RE = re.compile(
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December"
    r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2},?\s+\d{4})"
)
MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
# Grok Build h2 anchors look like "v0.2.20-2026-06-03".
_BUILD_ID_RE = re.compile(r"^v.+-(\d{4}-\d{2}-\d{2})$")

DESC_LIMIT = 500
MAX_ENTRIES = 200


def _get_html(url):
    """Fetch a URL impersonating Chrome (x.ai 403s plain clients);
    fall back to plain requests if curl_cffi is unavailable. Returns text or None."""
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
    """Mintlify/GitHub-style heading anchor: lowercase, non-alnum -> hyphen."""
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def title_from_slug(href):
    slug = href.rstrip("/").split("/")[-1]
    return slug.replace("-", " ").replace("_", " ").strip().capitalize()


def clean_markdown(text, limit=DESC_LIMIT):
    """Reduce markdown to readable plain text for a feed summary."""
    text = re.sub(r"<[^>]+>", " ", text)                    # JSX/HTML components
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)        # images
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)     # links -> link text
    text = re.sub(r"[`*_>#]", " ", text)                     # md punctuation
    text = re.sub(r"^\s*[-+]\s+", "", text, flags=re.MULTILINE)  # bullets
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


# --------------------------------------------------------------------------- #
# xAI News (server-rendered listing cards)
# --------------------------------------------------------------------------- #


def scrape_news(known_links):
    label = "xAI News"
    entries = []
    html = _get_html(NEWS_URL)
    if html is None:
        return entries
    soup = BeautifulSoup(html, "html.parser")

    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("/news/") or href == "/news/" or href in seen:
            continue
        seen.add(href)
        link = NEWS_BASE + href
        if link in known_links:
            continue
        try:
            heading = a.find(["h1", "h2", "h3"])
            title = heading.get_text(" ", strip=True) if heading else title_from_slug(href)
            m = DATE_RE.search(a.get_text(" ", strip=True))
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
# Grok Build changelog (h2 id="v<version>-<date>")
# --------------------------------------------------------------------------- #


def scrape_build_changelog(known_links):
    label = "Grok Build changelog"
    entries = []
    html = _get_html(BUILD_CHANGELOG_URL)
    if html is None:
        return entries
    soup = BeautifulSoup(html, "html.parser")

    headings = soup.find_all("h2", id=_BUILD_ID_RE)
    if not headings:
        logger.warning(f"  [{label}] no release headings matched — layout may have changed")
        return entries

    for h in headings:
        try:
            anchor = h.get("id")
            link = f"{BUILD_CHANGELOG_URL}#{anchor}"
            if link in known_links:
                continue
            date_obj = parse_date(_BUILD_ID_RE.match(anchor).group(1))
            title = sanitize_xml(h.get_text(" ", strip=True))
            parts = []
            for el in h.next_elements:
                if getattr(el, "name", None) == "h2" and el is not h:
                    break
                if getattr(el, "name", None) in ("p", "li"):
                    parts.append(el.get_text(" ", strip=True))
            desc = re.sub(r"\s+", " ", " ".join(parts)).strip()[:DESC_LIMIT]
            entries.append({
                "title": title,
                "link": link,
                "date": date_obj,
                "description": sanitize_xml(desc) or title,
                "source": label,
            })
            logger.info(f"  [{label}] {title}")
        except Exception as e:
            logger.warning(f"  [{label}] skipping malformed item: {e}")
    return entries


# --------------------------------------------------------------------------- #
# xAI API release notes (Mintlify markdown: ## Month / ### feature)
# --------------------------------------------------------------------------- #


def scrape_release_notes(known_links, today=None):
    import datetime as _dt

    label = "xAI API release notes"
    entries = []
    md = _get_html(RELEASE_NOTES_MD_URL)
    if md is None:
        return entries

    # Walk the markdown line by line: "## <Month>" sets the current month
    # (year inferred newest-first, rolling back when the month jumps upward),
    # "### <heading>" starts a feature section.
    today = today or _dt.datetime.now(pytz.UTC)
    year, prev_month = today.year, None
    cur_date = None
    sections = []   # (heading, date, [body lines])

    for line in md.splitlines():
        m2 = re.match(r"^##\s+([A-Za-z]+)\s*$", line)
        if m2 and m2.group(1).lower() in MONTH_NAMES:
            month = MONTH_NAMES[m2.group(1).lower()]
            if prev_month is None:
                if month > today.month:
                    year -= 1
            elif month > prev_month:
                year -= 1
            prev_month = month
            cur_date = _dt.datetime(year, month, 1, tzinfo=pytz.UTC)
            continue
        m3 = re.match(r"^###\s+(.+?)\s*$", line)
        if m3 and cur_date is not None:
            sections.append([m3.group(1), cur_date, []])
            continue
        if sections and cur_date is not None:
            sections[-1][2].append(line)

    if not sections:
        logger.warning(f"  [{label}] no sections parsed — page structure may have changed")
        return entries

    seen_slugs = {}
    for heading, date_obj, body in sections:
        try:
            slug = slugify(heading)
            # Mintlify suffixes repeated heading anchors with -2, -3, ...
            seen_slugs[slug] = seen_slugs.get(slug, 0) + 1
            if seen_slugs[slug] > 1:
                slug = f"{slug}-{seen_slugs[slug]}"
            link = f"{RELEASE_NOTES_URL}#{slug}"
            if link in known_links:
                continue
            desc = clean_markdown("\n".join(body)) or heading
            entries.append({
                "title": sanitize_xml(heading),
                "link": link,
                "date": date_obj,
                "description": sanitize_xml(desc),
                "source": label,
            })
            logger.info(f"  [{label}] {heading}")
        except Exception as e:
            logger.warning(f"  [{label}] skipping malformed section: {e}")
    return entries


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def scrape_all(known_links):
    new_entries = []
    logger.info("Scraping xAI News ...")
    new_entries += scrape_news(known_links)
    logger.info("Scraping Grok Build changelog ...")
    new_entries += scrape_build_changelog(known_links)
    logger.info("Scraping xAI API release notes ...")
    new_entries += scrape_release_notes(known_links)
    return new_entries


def generate_atom_feed(articles, feed_name=FEED_NAME):
    fg = FeedGenerator()
    fg.id(f"https://x.ai/{feed_name}")
    fg.title("xAI")
    fg.subtitle(
        "xAI product updates: News, the Grok Build changelog, and the xAI API "
        "release notes."
    )
    setup_feed_links(fg, BLOG_URL, feed_name)
    fg.language("en")
    fg.author({"name": "xAI"})

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
    parser = argparse.ArgumentParser(description="Generate the xAI Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
