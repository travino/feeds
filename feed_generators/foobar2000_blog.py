#!/usr/bin/env python3
"""Combined Atom feed generator for foobar2000.org.

Merges four foobar2000.org pages — none of which expose a native feed — into a
single Atom feed:

* News              https://www.foobar2000.org/news
* Change Log        https://www.foobar2000.org/changelog              (Windows)
* Change Log        https://www.foobar2000.org/changelog-android      (Android)
* Change Log        https://www.foobar2000.org/changelog-encoderpack  (Encoder Pack)

All four are static, server-rendered pages whose entries are a flat run of
dated headings:

* News uses ``<h3>YYYY-MM-DD</h3>`` followed by ``<p>`` paragraphs.
* The change logs use ``<h2>``; the heading text carries a ``YYYY-MM-DD`` date
  (sometimes prefixed with a version like ``2.25.9 released on …``) and the
  body is the following ``<ul>``.

Every entry is tagged with its source so a reader can tell a Windows release
note from an Android one. Entries have no per-item permalinks, so each links
back to its source page and gets a stable synthetic id
(``{page}#{version-or-date}``). A rolling JSON cache keeps ids stable and
preserves history if a page ever truncates.

Usage:
    python foobar2000_blog.py          # fetch all four pages, merge into cache
    python foobar2000_blog.py --full   # ignore cache, rebuild from pages only

Output:
    feeds/feed_foobar2000.xml          # combined Atom feed (rolling archive)
    cache/foobar2000_posts.json        # entry cache (source of truth for history)
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag
from feedgen.feed import FeedGenerator

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
FEED_NAME = "foobar2000"
BASE_URL = "https://www.foobar2000.org"
BLOG_URL = f"{BASE_URL}/news"  # primary/alternate link for the whole feed
FEED_TITLE = "foobar2000"
FEED_DESC = "News and change logs from foobar2000.org (Windows, Android, Encoder Pack)"
FEED_LANG = "en"

ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT_DIR / "feeds"
OUTPUT_FILE = OUTPUT_DIR / f"feed_{FEED_NAME}.xml"
CACHE_DIR = ROOT_DIR / "cache"
CACHE_FILE = CACHE_DIR / f"{FEED_NAME}_posts.json"

MAX_ENTRIES = 600  # four sources share one archive

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_BARE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_VERSION_RE = re.compile(r"^(\d+(?:\.\d+)+)")
_TITLE_LEN = 100


@dataclass(frozen=True)
class Source:
    """One foobar2000.org page to scrape."""

    key: str          # short tag used in ids/titles, e.g. "windows"
    label: str        # human label, e.g. "Change Log (Windows)"
    path: str         # URL path, e.g. "/changelog"
    heading_tag: str  # "h2" or "h3"
    kind: str         # "news" (paragraphs) or "changelog" (ul)


SOURCES: list[Source] = [
    Source("news", "News", "/news", "h3", "news"),
    Source("windows", "Change Log (Windows)", "/changelog", "h2", "changelog"),
    Source("android", "Change Log (Android)", "/changelog-android", "h2", "changelog"),
    Source(
        "encoderpack",
        "Change Log (Encoder Pack)",
        "/changelog-encoderpack",
        "h2",
        "changelog",
    ),
]


def setup_logging() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger(FEED_NAME)


log = setup_logging()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def fetch_page(url: str) -> str:
    log.info("Fetching %s", url)
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def parse_date(date_text: str) -> datetime:
    with contextlib.suppress(ValueError):
        return datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    log.warning("Unparseable date %r, using current time", date_text)
    return datetime.now(timezone.utc)


def _absolutize(fragment_html: str) -> str:
    """Rewrite relative <a>/<img> URLs to absolute foobar2000.org URLs."""
    frag = BeautifulSoup(fragment_html, "html.parser")
    for a in frag.find_all("a", href=True):
        a["href"] = urljoin(BASE_URL + "/", a["href"])
    for img in frag.find_all("img", src=True):
        img["src"] = urljoin(BASE_URL + "/", img["src"])
    return str(frag)


def _shorten(text: str) -> str:
    text = text.strip()
    if len(text) > _TITLE_LEN:
        return text[: _TITLE_LEN - 1].rstrip() + "\u2026"
    return text


# --------------------------------------------------------------------------- #
# Cache (rolling archive)
# --------------------------------------------------------------------------- #
def load_cache() -> list[dict]:
    if not CACHE_FILE.exists():
        return []
    try:
        raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not read cache (%s); starting fresh", exc)
        return []
    entries = []
    for e in raw:
        with contextlib.suppress(Exception):
            e["published"] = datetime.fromisoformat(e["published"])
            entries.append(e)
    log.info("Loaded %d cached entries", len(entries))
    return entries


def save_cache(entries: list[dict]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    serializable = [{**e, "published": e["published"].isoformat()} for e in entries]
    CACHE_FILE.write_text(
        json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("Saved %d entries to cache", len(entries))


def merge_entries(existing: list[dict], new: list[dict]) -> list[dict]:
    """Merge new entries into the archive, deduped by id, newest-first, capped."""
    by_id: dict[str, dict] = {e["id"]: e for e in existing}
    before = len(by_id)
    for e in new:
        by_id[e["id"]] = e
    added = len(by_id) - before
    merged = sorted(by_id.values(), key=lambda x: x["published"], reverse=True)
    if len(merged) > MAX_ENTRIES:
        merged = merged[:MAX_ENTRIES]
    log.info("Merge: %d new, %d total (capped at %d)", added, len(merged), MAX_ENTRIES)
    return merged


# --------------------------------------------------------------------------- #
# Scraping
# --------------------------------------------------------------------------- #
def _content_blocks(heading: Tag, heading_tag: str) -> list[Tag]:
    """Collect sibling element nodes until the next heading of the same level."""
    blocks: list[Tag] = []
    for sib in heading.find_next_siblings():
        name = getattr(sib, "name", None)
        if name == heading_tag and _DATE_RE.search(sib.get_text(" ", strip=True)):
            break
        if name:
            blocks.append(sib)
    return blocks


def extract_source(html: str, src: Source) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    page_url = f"{BASE_URL}{src.path}"

    headings = []
    for h in soup.find_all(src.heading_tag):
        text = h.get_text(" ", strip=True)
        if src.kind == "news":
            if _BARE_DATE_RE.match(h.get_text(strip=True)):
                headings.append(h)
        elif _DATE_RE.search(text):  # changelog: any header carrying a date
            headings.append(h)

    log.info("[%s] found %d entries", src.key, len(headings))

    results: list[dict] = []
    seen_ids: set[str] = set()
    per_key: dict[str, int] = {}

    for h in headings:
        try:
            header_text = h.get_text(" ", strip=True)
            m = _DATE_RE.search(header_text)
            if not m:
                continue
            date_text = m.group(1)
            published = parse_date(date_text)

            vm = _VERSION_RE.match(header_text.strip())
            version = vm.group(1) if vm else None

            blocks = _content_blocks(h, src.heading_tag)
            body_text = " ".join(b.get_text(" ", strip=True) for b in blocks).strip()
            summary = _absolutize("".join(str(b) for b in blocks)) or body_text

            # Stable id: prefer version (changelogs), else date. Disambiguate
            # same-key collisions (e.g. two news posts on one day).
            base = version or date_text
            n = per_key.get(base, 0)
            per_key[base] = n + 1
            entry_id = f"{page_url}#{base}" + (f"-{n}" if n else "")
            if entry_id in seen_ids:
                continue
            seen_ids.add(entry_id)

            # Title: "[Label] version — date" or "[Label] date: first sentence".
            if src.kind == "changelog":
                if version:
                    title = f"[{src.label}] {version} \u2014 {date_text}"
                else:
                    title = f"[{src.label}] {date_text}"
            else:
                first = (
                    re.split(r"(?<=[.!?])\s+", body_text, maxsplit=1)[0]
                    if body_text
                    else ""
                )
                title = f"[{src.label}] {date_text}"
                if first:
                    title = f"{title}: {_shorten(first)}"

            results.append(
                {
                    "id": entry_id,
                    "title": title,
                    "link": page_url,
                    "summary": summary,
                    "published": published,
                    "source": src.label,
                }
            )
        except Exception as exc:  # one bad block never kills the run
            log.warning("[%s] skipping an entry due to error: %s", src.key, exc)
            continue

    return results


def extract_all(pages: dict[str, str]) -> list[dict]:
    all_entries: list[dict] = []
    for src in SOURCES:
        html = pages.get(src.key)
        if not html:
            continue
        all_entries.extend(extract_source(html, src))
    all_entries.sort(key=lambda x: x["published"], reverse=True)
    return all_entries


# --------------------------------------------------------------------------- #
# Feed
# --------------------------------------------------------------------------- #
def build_feed(articles: list[dict]) -> bytes:
    fg = FeedGenerator()
    fg.id(BASE_URL + "/")
    fg.title(FEED_TITLE)
    fg.subtitle(FEED_DESC)
    fg.link(href=BLOG_URL, rel="alternate")
    fg.link(
        href=f"https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_{FEED_NAME}.xml",
        rel="self",
    )
    fg.language(FEED_LANG)
    fg.updated(datetime.now(timezone.utc))
    fg.generator("travino-feeds foobar2000_blog.py")

    # feedgen prepends entries, so add oldest-first to keep newest at the top.
    for art in reversed(articles):
        fe = fg.add_entry()
        fe.id(art["id"])
        fe.title(art["title"])
        fe.link(href=art["link"], rel="alternate")
        fe.updated(art["published"])
        fe.published(art["published"])
        fe.content(art["summary"], type="html")
        if art.get("source"):
            fe.category(term=art["source"])

    return fg.atom_str(pretty=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a combined Atom feed for foobar2000.org"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Ignore the cache and rebuild the feed from the current pages only",
    )
    args = parser.parse_args()

    pages: dict[str, str] = {}
    for src in SOURCES:
        try:
            pages[src.key] = fetch_page(f"{BASE_URL}{src.path}")
        except Exception as exc:
            log.warning("[%s] fetch failed (%s); skipping this source", src.key, exc)

    if not pages:
        log.error("No pages fetched; aborting without overwriting feed.")
        return 1

    scraped = extract_all(pages)
    if not scraped:
        log.error("No entries extracted; aborting without overwriting feed.")
        return 1

    existing = [] if args.full else load_cache()
    entries = merge_entries(existing, scraped)
    save_cache(entries)

    atom_bytes = build_feed(entries)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_bytes(atom_bytes)
    log.info("Wrote %d entries to %s", len(entries), OUTPUT_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
