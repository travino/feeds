#!/usr/bin/env python3
"""Combined Atom feed generator for HashiCorp / HCP.

Merges two HashiCorp sources into a single Atom feed:

* HashiCorp Blog   https://www.hashicorp.com/blog
      Has a native Atom feed at /blog/feed.xml (the locale-prefixed
      /en/blog/feed.xml is rate-limited, so we read the bare path). Each post
      already carries a real permalink and an ``updated`` timestamp, so we just
      re-publish its entries tagged ``[Blog]``.
* HCP Change Log   https://developer.hashicorp.com/hcp/docs/changelog
      A server-rendered docs page with no native feed. Entries are a flat run
      of ``<h3 id="YYYY-MM-DD">`` date headings, each followed by the body
      content (paragraphs / lists) up to the next heading. Each entry links
      back to its dated anchor and is tagged ``[Changelog]``.

Entries from both sources share one rolling JSON cache so ids stay stable and
history survives even if a source truncates. Output is newest-first Atom.

Usage:
    python hcp_combined.py          # incremental: merge new entries into cache
    python hcp_combined.py --full   # ignore cache, rebuild from sources only

Output:
    feeds/feed_hcp.xml              # combined Atom feed
    cache/hcp_posts.json            # entry cache (history)
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from feedgen.feed import FeedGenerator
from lxml import etree

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

FEED_NAME = "hcp"
FEED_TITLE = "HCP"
FEED_SUBTITLE = "HashiCorp blog posts and HashiCorp Cloud Platform changelog"
BLOG_URL = "https://www.hashicorp.com/blog"

BLOG_FEED_URL = "https://www.hashicorp.com/blog/feed.xml"
CHANGELOG_URL = "https://developer.hashicorp.com/hcp/docs/changelog"
CHANGELOG_BASE = "https://developer.hashicorp.com"

MAX_ENTRIES = 200  # two sources share one archive
ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}
_DATE_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------- #
# Fetch
# --------------------------------------------------------------------------- #
def _get(url: str, *, binary: bool = False):
    """Fetch a URL, impersonating Chrome (curl_cffi) to clear TLS-fingerprint
    blocks, falling back to plain requests. Returns bytes/str, or None on
    failure so a single bad source never aborts the whole run."""
    try:
        from curl_cffi import requests as creq

        resp = creq.get(url, impersonate="chrome", timeout=30)
    except ImportError:
        import requests

        logger.warning("curl_cffi unavailable; using plain requests for %s", url)
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0"},
            timeout=30,
        )
    except Exception as exc:  # network error, timeout, etc.
        logger.warning("Fetch failed for %s: %s", url, exc)
        return None

    if resp.status_code != 200:
        logger.warning("Fetch for %s returned HTTP %s", url, resp.status_code)
        return None
    return resp.content if binary else resp.text


# --------------------------------------------------------------------------- #
# Source: HashiCorp Blog (native Atom feed)
# --------------------------------------------------------------------------- #
def fetch_blog() -> list[dict]:
    xml = _get(BLOG_FEED_URL, binary=True)
    if not xml:
        return []
    try:
        root = etree.fromstring(xml)
    except etree.XMLSyntaxError as exc:
        logger.warning("Blog feed did not parse as XML: %s", exc)
        return []

    entries: list[dict] = []
    for e in root.findall("a:entry", ATOM_NS):
        try:
            title = (e.findtext("a:title", namespaces=ATOM_NS) or "").strip()
            link = None
            for ln in e.findall("a:link", ATOM_NS):
                if ln.get("rel", "alternate") == "alternate":
                    link = ln.get("href")
                    break
            if not (title and link):
                continue
            summary = (
                e.findtext("a:summary", namespaces=ATOM_NS)
                or e.findtext("a:content", namespaces=ATOM_NS)
                or ""
            ).strip()
            updated = e.findtext("a:updated", namespaces=ATOM_NS) or e.findtext(
                "a:published", namespaces=ATOM_NS
            )
            date = date_parser.parse(updated).astimezone(timezone.utc) if updated else None
            entries.append(
                {
                    "id": link,
                    "title": sanitize_xml(f"[Blog] {title}"),
                    "link": link,
                    "summary": sanitize_xml(summary),
                    "date": date,
                    "source": "Blog",
                }
            )
        except Exception as exc:  # one bad entry never kills the source
            logger.warning("Skipping a blog entry: %s", exc)
    logger.info("Blog: parsed %d entries", len(entries))
    return entries


# --------------------------------------------------------------------------- #
# Source: HCP Change Log (scraped docs page)
# --------------------------------------------------------------------------- #
def _absolutize(node) -> str:
    for a in node.find_all("a", href=True):
        a["href"] = urljoin(CHANGELOG_BASE + "/", a["href"])
    return str(node)


def fetch_changelog() -> list[dict]:
    html = _get(CHANGELOG_URL)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    headings = [h for h in soup.find_all("h3") if _DATE_ID_RE.match(h.get("id") or "")]
    logger.info("Changelog: found %d dated entries", len(headings))

    entries: list[dict] = []
    for h in headings:
        try:
            date_text = h["id"]
            published = datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=timezone.utc)

            blocks = []
            for sib in h.find_next_siblings():
                if getattr(sib, "name", None) in ("h1", "h2", "h3"):
                    break
                if getattr(sib, "name", None):
                    blocks.append(sib)
            if not blocks:
                continue

            body_html = "".join(_absolutize(b) for b in blocks)
            body_text = " ".join(b.get_text(" ", strip=True) for b in blocks).strip()
            first = re.split(r"(?<=[.!?])\s+", body_text, maxsplit=1)[0] if body_text else ""
            snippet = (first[:99].rstrip() + "\u2026") if len(first) > 100 else first
            title = f"[Changelog] {date_text}"
            if snippet:
                title = f"{title}: {snippet}"

            entries.append(
                {
                    "id": f"{CHANGELOG_URL}#{date_text}",
                    "title": sanitize_xml(title),
                    "link": f"{CHANGELOG_URL}#{date_text}",
                    "summary": sanitize_xml(body_html),
                    "date": published,
                    "source": "Changelog",
                }
            )
        except Exception as exc:
            logger.warning("Skipping a changelog entry: %s", exc)
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
    fg.author({"name": "HashiCorp"})
    fg.updated(datetime.now(timezone.utc))
    fg.generator("travino-feeds hcp_combined.py")

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
    new_entries = fetch_blog() + fetch_changelog()
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
    parser = argparse.ArgumentParser(description="Generate the combined HCP Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
