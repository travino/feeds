"""TVP (Telewizja Polska) feed: combined Atom from TVP's public services.

Sources:
  * TVP Info (tvp.info) — native RSS at the legacy ``rss+xml.php`` endpoint,
    the main rolling news service (~30 items, dated).
  * TVP Sport (sport.tvp.pl) — native RSS at ``/rss`` (~50 items, dated).
  * www.tvp.pl portal sections — the portal is an Angular SPA that renders its
    listings client-side, but every directory is backed by a clean v4 JSON
    block API. For each section we resolve its primary "news" grid block and
    pull the latest articles:
      - Informacje  (/83939255/informacje)   — national/world news
      - Rozrywka    (/85859082/aktualnosci)  — entertainment
      - Kultura     (/44233674/aktualnosci)  — culture
      - Moto        (/82262988/moto)         — automotive

Block-API mechanics: ``window.__directoryData`` in each section page carries
the page id and its directory ``type``. When that type is a "grid", the page
id is itself the article block (``/api/platform/block?id=<pageId>``); otherwise
the page is a section-group landing whose article grids are listed by
``/api/platform/block/list?id=<pageId>`` (we take the first ``objectType ==
"news"`` block). Item dates arrive as epoch milliseconds in ``release_date`` /
``publication_start``.

The Moto landing currently exposes only a menu (no flat article grid), so it
contributes nothing until TVP populates a grid there; it is kept in the list
so it starts working automatically if that changes. centruminformacji.tvp.pl
is deliberately not a source: it is a static corporate landing page (sections
like "nasze akcje", "patronaty", "przetargi") with no article stream and no
native feed.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone

from multi_rss import get_html, logger, run
from utils import sanitize_xml

FEED_NAME = "tvp"

PORTAL_API = "https://www.tvp.pl/api/platform"
PER_SECTION = 30

SOURCES = [
    ("TVP Info", "http://www.tvp.info/tvp.info/rss+xml.php", 40),
    ("TVP Sport", "https://sport.tvp.pl/rss", 40),
]

# (source label, section landing URL)
PORTAL_SECTIONS = [
    ("TVP Informacje", "https://www.tvp.pl/83939255/informacje"),
    ("TVP Rozrywka", "https://www.tvp.pl/85859082/aktualnosci"),
    ("TVP Kultura", "https://www.tvp.pl/44233674/aktualnosci"),
    ("TVP Moto", "https://www.tvp.pl/82262988/moto"),
]


def _epoch_ms_to_dt(value):
    """Convert a TVP epoch-milliseconds timestamp to a UTC datetime, or None."""
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _resolve_block_id(section_url):
    """Find the primary news-grid block id backing a section landing page."""
    html = get_html(section_url)
    if not html:
        return None
    m = re.search(r"window\.__directoryData\s*=\s*(\{.*?\});", html, re.S)
    if not m:
        return None
    try:
        directory = json.loads(m.group(1))
    except (ValueError, TypeError):
        return None

    page_id = directory.get("id")
    params = directory.get("params") or {}
    if "grid" in (params.get("type") or ""):
        return page_id

    listing = get_html(f"{PORTAL_API}/block/list?id={page_id}")
    if not listing:
        return None
    try:
        items = json.loads(listing).get("data", {}).get("items", [])
    except (ValueError, TypeError, AttributeError):
        return None
    for block in items:
        if (block.get("params") or {}).get("objectType") == "news":
            return block.get("_id")
    return None


def _scrape_section(label, section_url, known_links):
    entries = []
    block_id = _resolve_block_id(section_url)
    if not block_id:
        return entries
    body = get_html(f"{PORTAL_API}/block?id={block_id}")
    if not body:
        return entries
    try:
        items = json.loads(body).get("data", {}).get("items", []) or []
    except (ValueError, TypeError, AttributeError):
        return entries

    for item in items[:PER_SECTION]:
        try:
            link = (item.get("url") or "").strip()
            if not link or link in known_links:
                continue
            title = sanitize_xml((item.get("title") or "").strip())
            if not title:
                continue
            desc = (item.get("lead") or item.get("description") or "").strip()
            date = _epoch_ms_to_dt(item.get("release_date") or item.get("publication_start"))
            entries.append({
                "title": title,
                "link": link,
                "date": date,
                "description": sanitize_xml(desc or title)[:500],
                "source": label,
            })
        except Exception:
            continue
    return entries


def scrape_portal(known_links):
    """Pull the latest articles from each www.tvp.pl portal section via the v4
    block API. Each section is isolated so one failure never sinks the rest."""
    entries = []
    for label, url in PORTAL_SECTIONS:
        try:
            entries += _scrape_section(label, url, known_links)
        except Exception as e:  # noqa: BLE001 — keep other sections alive
            logger.warning(f"Portal section {label} failed: {e}")
    return entries


def main(full=False):
    return run(
        feed_name=FEED_NAME,
        title="TVP",
        subtitle="Combined Telewizja Polska feed: TVP Info, TVP Sport, and the "
                 "www.tvp.pl portal sections (Informacje, Rozrywka, Kultura, Moto).",
        blog_url="https://www.tvp.pl/",
        author="Telewizja Polska",
        sources=SOURCES,
        extra_scrapers=(scrape_portal,),
        language="pl",
        full=full,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the TVP Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    sys.exit(0 if main(full=parser.parse_args().full) else 1)
