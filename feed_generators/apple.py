"""Apple feed: combined Atom from Apple Newsroom, Developer news/releases,
developer-documentation release notes, and Technotes.

Sources:
  * Apple Newsroom PL (apple.com/pl/newsroom) — native Atom
  * Apple Developer News (developer.apple.com/news) — native RSS
  * Apple Developer Releases (developer.apple.com/news/releases) — native RSS
    (OS/Xcode/TestFlight build announcements)
  * Developer documentation topics — the docs site is JS-rendered, but every
    page has a JSON twin under ``/tutorials/data/documentation/<path>.json``;
    the topic indexes for Technotes and the iOS/iPadOS, macOS, and
    Safari release notes are read from there, newest 12 per topic. Doc pages
    carry no dates, so entries are dated when first seen. (The Apple News
    Format release notes are a single prose page with no per-version
    subpages, so they are not an item source.)
  * Developer Account release notes (developer.apple.com/help/account) —
    server-rendered ``h5.rn-date`` entries with real dates; entries are keyed
    by a date fragment on the page URL since the page has no per-entry links.
"""

import argparse
import re
import sys
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from multi_rss import get_html, parse_date, run
from utils import sanitize_xml

FEED_NAME = "apple"

DOCS_BASE = "https://developer.apple.com"
DOCS_JSON = DOCS_BASE + "/tutorials/data/documentation/{path}.json"
ACCOUNT_RN_URL = DOCS_BASE + "/help/account/release-notes/"

SOURCES = [
    ("Apple Newsroom PL", "https://www.apple.com/pl/newsroom/rss-feed.rss", 30),
    ("Developer News", "https://developer.apple.com/news/rss/news.rss", 40),
    ("Developer Releases", "https://developer.apple.com/news/releases/rss/releases.rss", 40),
]

# (label, json path under /tutorials/data/documentation/)
DOC_TOPICS = [
    ("Technotes", "technotes"),
    ("iOS & iPadOS Release Notes", "ios-ipados-release-notes"),
    ("macOS Release Notes", "macos-release-notes"),
    ("Safari Release Notes", "safari-release-notes"),
]

DOC_TOPIC_CAP = 12  # newest pages per topic (topicSections order is newest-first)


def _abstract_text(ref):
    return " ".join(p.get("text", "") for p in ref.get("abstract") or []).strip()


def scrape_doc_topics(known_links):
    """Article references from the JSON twins of developer-documentation
    topic pages, newest ``DOC_TOPIC_CAP`` per topic (the ``topicSections``
    identifier order is newest-first). Doc pages carry no dates, so entries
    are dated when first seen — the timestamp is then preserved in the cache,
    so newly published release notes surface at the top of the feed."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    entries = []
    for label, path in DOC_TOPICS:
        url = DOCS_JSON.format(path=path)
        try:
            data = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30).json()
        except Exception:
            continue
        refs = data.get("references") or {}
        ordered_ids = []
        for section in data.get("topicSections") or []:
            ordered_ids += section.get("identifiers") or []
        count = 0
        for ident in ordered_ids:
            ref = refs.get(ident)
            if not ref:
                continue
            try:
                if ref.get("role") != "article" and ref.get("kind") != "article":
                    continue
                rel = ref.get("url") or ""
                if not rel.startswith("/documentation/"):
                    continue
                link = urljoin(DOCS_BASE, rel)
                count += 1
                if count > DOC_TOPIC_CAP:
                    break
                if link in known_links:
                    continue
                title = sanitize_xml((ref.get("title") or "").strip())
                if not title:
                    continue
                entries.append({
                    "title": title,
                    "link": link,
                    "date": now,
                    "description": sanitize_xml(_abstract_text(ref) or title)[:500],
                    "source": label,
                })
            except Exception:
                continue
    return entries


def scrape_account_release_notes(known_links):
    """Developer Account release notes: dated ``h5.rn-date`` headings each
    followed by a paragraph. The page has no per-entry links, so entries are
    keyed by a ``#YYYY-MM-DD`` fragment on the page URL (fragments are
    preserved by the dedupe key)."""
    entries = []
    html = get_html(ACCOUNT_RN_URL)
    if html is None:
        return entries
    soup = BeautifulSoup(html, "html.parser")
    for h in soup.select("h5.rn-date"):
        try:
            date = parse_date(h.get_text(strip=True))
            if date is None:
                continue
            link = f"{ACCOUNT_RN_URL}#{date.date().isoformat()}"
            if link in known_links:
                continue
            p = h.find_next_sibling("p")
            desc = sanitize_xml(p.get_text(" ", strip=True)) if p else ""
            entries.append({
                "title": f"Developer Account updates — {h.get_text(strip=True)}",
                "link": link,
                "date": date,
                "description": desc[:500] or h.get_text(strip=True),
                "source": "Account Release Notes",
            })
        except Exception:
            continue
    return entries


def main(full=False):
    return run(
        feed_name=FEED_NAME,
        title="Apple",
        subtitle="Combined Apple feed: Newsroom PL, Developer news and "
                 "releases, Technotes, iOS/iPadOS, macOS and Safari release "
                 "notes, and Developer Account release notes.",
        blog_url="https://www.apple.com/pl/newsroom/",
        author="Apple",
        sources=SOURCES,
        extra_scrapers=(scrape_doc_topics, scrape_account_release_notes),
        full=full,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the Apple Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    sys.exit(0 if main(full=parser.parse_args().full) else 1)
