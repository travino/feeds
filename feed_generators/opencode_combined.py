#!/usr/bin/env python3
"""Combined Atom feed generator for OpenCode.

Merges two OpenCode sources into a single Atom feed:

* Change Log   https://opencode.ai/changelog
      A server-rendered page (no native feed) where each release is an
      ``<article>`` carrying a version link to its GitHub release, a
      ``<time datetime=...>`` stamp, and the grouped change notes. Each release
      links to its GitHub release tag and is tagged ``[Release]``.
* opencode.cafe https://www.opencode.cafe/
      A community directory of OpenCode extensions/plugins. The site renders
      its catalog client-side from a public Convex query, so we call that query
      directly (``extensions:listApproved``) rather than scraping the SPA shell.
      Each approved extension is tagged ``[Extension]`` and links to its repo.

Both sources share one rolling JSON cache so ids stay stable and history
survives if a source truncates. Output is newest-first Atom.

Usage:
    python opencode_combined.py          # incremental: merge new entries
    python opencode_combined.py --full   # ignore cache, rebuild from sources

Output:
    feeds/feed_opencode.xml              # combined Atom feed
    cache/opencode_posts.json            # entry cache (history)
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone

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
)

logger = setup_logging()

FEED_NAME = "opencode"
FEED_TITLE = "OpenCode"
FEED_SUBTITLE = "OpenCode release changelog and community extensions from opencode.cafe"
BLOG_URL = "https://opencode.ai/changelog"

CHANGELOG_URL = "https://opencode.ai/pl/changelog"
CAFE_URL = "https://www.opencode.cafe/"
CONVEX_QUERY_URL = "https://curious-quail-727.convex.cloud/api/query"
CONVEX_QUERY_PATH = "extensions:listApproved"

MAX_ENTRIES = 200
_RELEASE_RE = re.compile(r"/releases/tag/")


# --------------------------------------------------------------------------- #
# Fetch helpers
# --------------------------------------------------------------------------- #
def _get_html(url: str):
    """Fetch HTML, impersonating Chrome via curl_cffi, falling back to requests."""
    try:
        from curl_cffi import requests as creq

        resp = creq.get(url, impersonate="chrome", timeout=30)
    except ImportError:
        logger.warning("curl_cffi unavailable; using plain requests for %s", url)
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0"},
            timeout=30,
        )
    except Exception as exc:
        logger.warning("Fetch failed for %s: %s", url, exc)
        return None
    if resp.status_code != 200:
        logger.warning("Fetch for %s returned HTTP %s", url, resp.status_code)
        return None
    return resp.text


# --------------------------------------------------------------------------- #
# Source: OpenCode change log (scraped releases)
# --------------------------------------------------------------------------- #
def fetch_changelog() -> list[dict]:
    html = _get_html(CHANGELOG_URL)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    articles = soup.find_all("article")
    logger.info("Changelog: found %d release articles", len(articles))

    entries: list[dict] = []
    for art in articles:
        try:
            rel = art.find("a", href=_RELEASE_RE)
            if not rel:
                continue
            version = rel.get_text(strip=True)
            link = rel["href"]

            tm = art.find("time")
            published = None
            if tm and tm.get("datetime"):
                published = date_parser.parse(tm["datetime"]).astimezone(timezone.utc)

            # Rebuild a clean summary from the section blocks (category + change
            # list), dropping the page's React hydration markers and data-* noise.
            parts: list[str] = []
            for sec in art.find_all("div", attrs={"data-component": "section"}):
                head = sec.find(["h2", "h3", "h4"])
                cat = head.get_text(" ", strip=True) if head else ""
                items = []
                for li in sec.select("li"):
                    span = li.find("span")
                    text = (span or li).get_text(" ", strip=True)
                    if text:
                        items.append(f"<li>{text}</li>")
                if items:
                    parts.append((f"<h4>{cat}</h4>" if cat else "") + "<ul>" + "".join(items) + "</ul>")
            summary = "".join(parts) or art.get_text(" ", strip=True)

            entries.append(
                {
                    "id": link,
                    "title": sanitize_xml(f"[Release] {version}"),
                    "link": link,
                    "summary": sanitize_xml(summary),
                    "date": published,
                    "source": "Release",
                }
            )
        except Exception as exc:  # one bad release never kills the source
            logger.warning("Skipping a changelog release: %s", exc)
    return entries


# --------------------------------------------------------------------------- #
# Source: opencode.cafe extensions (public Convex query)
# --------------------------------------------------------------------------- #
def fetch_extensions() -> list[dict]:
    try:
        resp = requests.post(
            CONVEX_QUERY_URL,
            json={"path": CONVEX_QUERY_PATH, "args": {"limit": 100}, "format": "json"},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        logger.warning("opencode.cafe Convex query failed: %s", exc)
        return []

    if payload.get("status") != "success":
        logger.warning("opencode.cafe query returned status %s", payload.get("status"))
        return []
    items = (payload.get("value") or {}).get("extensions", [])
    logger.info("Extensions: received %d items", len(items))

    entries: list[dict] = []
    for it in items:
        try:
            product_id = it.get("productId")
            name = it.get("displayName") or product_id
            repo = it.get("repoUrl")
            link = it.get("homepageUrl") or repo
            if not (product_id and name and link):
                continue
            kind = it.get("type", "extension")
            created_ms = it.get("createdAt") or it.get("_creationTime")
            date = (
                datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc) if created_ms else None
            )

            author = (it.get("author") or {}).get("name", "")
            desc = it.get("description", "")
            tags = it.get("tags") or []
            meta = " &middot; ".join(
                p
                for p in (
                    f"Type: {kind}",
                    f"By {author}" if author else "",
                    f'Repo: <a href="{repo}">{repo}</a>' if repo else "",
                    ("Tags: " + ", ".join(tags)) if tags else "",
                )
                if p
            )
            summary = f"<p>{desc}</p><p>{meta}</p>" if desc else f"<p>{meta}</p>"

            entries.append(
                {
                    "id": f"opencode.cafe:{product_id}",
                    "title": sanitize_xml(f"[Extension] {name} ({kind})"),
                    "link": link,
                    "summary": sanitize_xml(summary),
                    "date": date,
                    "source": "Extension",
                }
            )
        except Exception as exc:
            logger.warning("Skipping an extension: %s", exc)
    return entries


# --------------------------------------------------------------------------- #
# Feed
# --------------------------------------------------------------------------- #
def generate_atom_feed(entries: list[dict]):
    fg = FeedGenerator()
    fg.id(f"{BLOG_URL}#{FEED_NAME}")
    fg.title(FEED_TITLE)
    fg.subtitle(FEED_SUBTITLE)
    setup_feed_links(fg, BLOG_URL, FEED_NAME)
    fg.language("en")
    fg.author({"name": "OpenCode"})
    fg.updated(datetime.now(timezone.utc))
    fg.generator("travino-feeds opencode_combined.py")

    # entries are ascending (oldest first); feedgen reverses on write.
    for e in entries:
        fe = fg.add_entry()
        fe.id(e["id"])
        fe.title(e["title"])
        fe.link(href=e["link"], rel="alternate")
        if e.get("summary"):
            fe.content(e["summary"], type="html")
        if e.get("date"):
            fe.published(e["date"])
            fe.updated(e["date"])
        if e.get("source"):
            fe.category(term=e["source"])
    return fg


def save_atom_feed(fg) -> None:
    out = get_feeds_dir() / f"feed_{FEED_NAME}.xml"
    fg.atom_file(str(out), pretty=True)
    logger.info("Wrote %s", out)


def main(full: bool = False) -> bool:
    new_entries = fetch_changelog() + fetch_extensions()
    if not new_entries:
        logger.error("No entries from any source; preserving the last good feed")
        return False

    cached = (
        []
        if full
        else deserialize_entries(load_cache(FEED_NAME).get("entries", []), date_field="date")
    )
    merged = merge_entries(new_entries, cached, id_field="id", date_field="date")
    merged = sort_posts_for_feed(merged, date_field="date")
    if len(merged) > MAX_ENTRIES:
        merged = merged[-MAX_ENTRIES:]  # ascending, so the tail is newest

    save_cache(FEED_NAME, merged)
    save_atom_feed(generate_atom_feed(merged))
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the combined OpenCode Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
