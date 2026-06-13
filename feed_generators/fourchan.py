"""4chan feed: one combined Atom feed from selected worksafe topical boards
(via the official read-only JSON API) plus the official 4chan blog.

4chan has no native per-board feed, but it exposes a documented read-only JSON
API (https://github.com/4chan/4chan-API): ``GET /{board}/catalog.json`` returns
every OP thread on a board with its subject, comment, and timestamps. One
request per board yields the current thread list. We surface the newest threads
by OP *creation* time (not bump time, so the feed does not churn every run as
old threads get bumped) and accumulate history across runs in the JSON cache.

Boards included are the substantive worksafe topical ones worth following in a
reader:

  * ``/news/`` Current News
  * ``/g/``    Technology
  * ``/o/``    Auto
  * ``/tv/``   Television & Film
  * ``/v/``    Video Games
  * ``/mu/``   Music
  * ``/vip/``  Very Important Posts

plus the official blog (blog.4chan.org), a WordPress site folded in via its
native ``/feed/``.

Deliberately excluded (add the codes to ``BOARDS`` yourself if you want them):
``/b/`` (Random) and ``/trash/`` (Off-Topic) are NSFW boards dominated by
explicit content and slurs; ``/int/`` and ``/bant/`` are flame/nationalism
boards; ``/t/`` (Torrents) exists to share warez; ``/s4s/`` is low-signal
shitposting. None of them belong in an automated feed that republishes their
text.

Board content is user-generated and unmoderated; each entry's title is
prefixed with its board so the source is obvious in a reader. Thread comment
HTML is stripped to plain text and truncated. Per-board / per-source error
isolation means one failing board (or the blog) never sinks the run. Writes an
Atom feed to ``feeds/feed_4chan.xml``; caches to ``cache/4chan_posts.json``.
"""

import argparse
import datetime
import html
import sys
import time

import pytz
import requests
from bs4 import BeautifulSoup

from multi_rss import run
from utils import sanitize_xml, setup_logging

logger = setup_logging()

FEED_NAME = "4chan"
SITE_URL = "https://www.4chan.org/"
API_BASE = "https://a.4cdn.org"
BOARDS_BASE = "https://boards.4chan.org"

# (board code, human label) — substantive worksafe topical boards only.
BOARDS = [
    ("news", "/news/ News"),
    ("g", "/g/ Technology"),
    ("o", "/o/ Auto"),
    ("tv", "/tv/ TV & Film"),
    ("v", "/v/ Video Games"),
    ("mu", "/mu/ Music"),
    ("b", "/b/ Random"),
    ("trash", "/trash/ Off-Topic"),
    ("s4s", "/s4s/ Sh*t 4chan Says"),
    ("t", "/t/ Torrents"),
    ("vip", "/vip/ VIP"),
    ("int", "/int/ International"),
    ("bant", "/bant/ International/Random"),
]

# Official blog (WordPress) — folded in as a native RSS source.
BLOG_FEED = "https://blog.4chan.org/feed/"

PER_BOARD = 12        # newest OP threads to surface per board per run
DESC_LIMIT = 500
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; travino-feeds/1.0; "
                  "+https://github.com/travino/feeds)"
}


def _strip(com: str) -> str:
    """4chan comment/subject HTML -> sanitized plain text."""
    if not com:
        return ""
    text = BeautifulSoup(html.unescape(com), "html.parser").get_text(" ", strip=True)
    return sanitize_xml(text)


def scrape_board(board: str, label: str, known_links: set) -> list:
    """Pull the newest OP threads from one board's catalog. Returns [] on any
    failure so a single dead board never blocks the rest of the feed."""
    entries = []
    url = f"{API_BASE}/{board}/catalog.json"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            logger.warning(f"  [{label}] catalog HTTP {resp.status_code}")
            return entries
        pages = resp.json()
    except Exception as e:
        logger.warning(f"  [{label}] fetch/parse failed: {e}")
        return entries

    threads = []
    for page in pages:
        threads.extend(page.get("threads", []))
    # Newest OP threads first (creation time, not bump time -> no churn).
    threads.sort(key=lambda t: t.get("time", 0), reverse=True)

    for t in threads[:PER_BOARD]:
        try:
            no = t.get("no")
            if not no:
                continue
            link = f"{BOARDS_BASE}/{board}/thread/{no}"
            if link in known_links:
                continue
            sub = _strip(t.get("sub") or "")
            body = _strip(t.get("com") or "")
            headline = sub or (body[:80] + ("…" if len(body) > 80 else "")) or f"thread {no}"
            title = f"{label}: {headline}"
            ts = t.get("time")
            date_obj = (
                datetime.datetime.fromtimestamp(int(ts), tz=pytz.UTC) if ts else None
            )
            desc = (body or sub or headline)[:DESC_LIMIT]
            entries.append({
                "title": sanitize_xml(title),
                "link": link,
                "date": date_obj,
                "description": sanitize_xml(desc),
                "source": label,
            })
            logger.info(f"  [{label}] {headline}")
        except Exception as e:
            logger.warning(f"  [{label}] skipping malformed thread: {e}")

    time.sleep(1)  # 4chan API courtesy: at most one request per second
    return entries


def scrape_boards(known_links: set) -> list:
    entries = []
    for board, label in BOARDS:
        logger.info(f"Scraping {label} ...")
        entries += scrape_board(board, label, known_links)
    return entries


def main(full=False):
    return run(
        feed_name=FEED_NAME,
        title="4chan",
        subtitle="Newest threads from selected worksafe 4chan boards "
                 "(news, g, o, tv, v, mu, vip) via the read-only JSON API, "
                 "plus the official 4chan blog. Board posts are user-generated "
                 "and unmoderated; each title is prefixed with its board.",
        blog_url=SITE_URL,
        author="4chan",
        sources=[("4chan Blog", BLOG_FEED, 20)],
        extra_scrapers=[scrape_boards],
        max_entries=200,
        full=full,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the 4chan Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    sys.exit(0 if main(full=parser.parse_args().full) else 1)
