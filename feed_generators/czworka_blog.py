"""Generate Atom feed for Czwórka — Polskie Radio
(https://www.polskieradio.pl/10,czworka).

Czwórka runs on Polskie Radio's classic server-rendered ASP.NET CMS. The
homepage is fully static (no Selenium needed), but it's built almost entirely
from dateless promo carousels, and card titles have category labels glued on
("KulturaRuszyły zdjęcia…"). So the homepage is used only to *discover* article
links; the clean title, lead, and publish timestamp are read from each article
page's metadata:

* title  -> ``og:title``
* lead   -> ``og:description``
* date   -> ``span.time`` inside the main ``div.this-article`` header
            (``DD.MM.YYYY HH:MM``, Europe/Warsaw)

The homepage embeds cross-promo boxes for other Polskie Radio stations
(Jedynka ``/7/`` etc.); only Czwórka articles (``/10/`` portal) are kept.

A JSON cache (``cache/czworka_posts.json``) accumulates history across hourly
runs and dedupes by canonical article id. Because already-cached articles are
skipped, the per-article fetch only happens once per article — a full run pays
for all of them, incremental runs only for genuinely new ones. Writes an Atom
feed to ``feeds/feed_czworka.xml``.
"""

import argparse
import re
import time
from datetime import datetime

import pytz
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

from utils import (
    deserialize_entries,
    fetch_page,
    load_cache,
    merge_entries,
    sanitize_xml,
    save_cache,
    save_atom_feed,
    setup_feed_links,
    setup_logging,
    sort_posts_for_feed,
    stable_fallback_date,
)

logger = setup_logging()

FEED_NAME = "czworka"
BLOG_URL = "https://www.polskieradio.pl/10,czworka"
BASE_URL = "https://www.polskieradio.pl"
WARSAW = pytz.timezone("Europe/Warsaw")

# Czwórka is portal id 10; article links look like /10/{sub}/Artykul/{id}[,slug].
_CZWORKA_LINK_RE = re.compile(r"^/10/\d+/Artykul/\d+", re.I)
_ARTICLE_ID_RE = re.compile(r"/Artykul/(\d+)", re.I)
_DATETIME_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})")

# Be polite during the big initial crawl.
FETCH_DELAY_SECONDS = 0.4


def _canonical(link: str) -> str:
    """Drop the trailing ,slug so an article dedupes stably across runs."""
    return re.sub(r"(/Artykul/\d+),.*$", r"\1", link)


def _meta(soup: BeautifulSoup, prop: str) -> str | None:
    tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
    return tag.get("content") if tag else None


def _parse_article_date(soup: BeautifulSoup, fallback_id: str) -> datetime:
    """Read the article-header timestamp (DD.MM.YYYY HH:MM) scoped to the main
    article container so sidebar/related dates don't leak in."""
    main = soup.find("div", class_="this-article") or soup
    for span in main.find_all("span", class_="time"):
        m = _DATETIME_RE.search(span.get_text(strip=True))
        if m:
            day, month, year, hh, mm = (int(g) for g in m.groups())
            try:
                return WARSAW.localize(datetime(year, month, day, hh, mm))
            except ValueError:
                break
    at = main.find("div", class_="article-time")
    if at:
        m = _DATETIME_RE.search(at.get_text(strip=True))
        if m:
            day, month, year, hh, mm = (int(g) for g in m.groups())
            try:
                return WARSAW.localize(datetime(year, month, day, hh, mm))
            except ValueError:
                pass
    return stable_fallback_date(fallback_id)


def discover_links(html: str) -> list[str]:
    """Collect unique Czwórka article URLs from the listing page."""
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not _CZWORKA_LINK_RE.match(href):
            continue
        full = href if href.startswith("http") else f"{BASE_URL}{href}"
        canon = _canonical(full)
        if canon in seen:
            continue
        seen.add(canon)
        links.append(full)
    logger.info("Discovered %d Czwórka article links", len(links))
    return links


def fetch_article(url: str) -> dict | None:
    """Fetch a single article page and extract title, lead, and date."""
    try:
        html = fetch_page(url)
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None

    soup = BeautifulSoup(html, "html.parser")
    title = _meta(soup, "og:title")
    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else None
    if not title:
        logger.warning("No title for %s; skipping", url)
        return None

    lead = _meta(soup, "og:description") or ""
    canon = _canonical(url)
    date = _parse_article_date(soup, canon)

    return {
        "link": canon,
        "title": sanitize_xml(title.strip()),
        "description": sanitize_xml(lead.strip()) or sanitize_xml(title.strip()),
        "date": date,
    }


def fetch_new_articles(links: list[str], known: set[str]) -> list[dict]:
    """Fetch only the article pages we haven't cached yet."""
    posts: list[dict] = []
    for url in links:
        if _canonical(url) in known:
            continue
        post = fetch_article(url)
        if post:
            posts.append(post)
        time.sleep(FETCH_DELAY_SECONDS)
    logger.info("Fetched %d new article pages", len(posts))
    return posts


def generate_rss_feed(posts: list[dict]) -> FeedGenerator:
    fg = FeedGenerator()
    fg.id("https://www.polskieradio.pl/10,czworka")
    fg.title("Czwórka – Polskie Radio")
    fg.description(
        "Najnowsze artykuły Czwórki Polskiego Radia: muzyka, życie, kultura "
        "i audycje czwartego programu."
    )
    fg.language("pl")
    fg.author({"name": "Polskie Radio – Czwórka"})
    fg.subtitle("Czwarty program Polskiego Radia")
    setup_feed_links(fg, blog_url=BLOG_URL, feed_name=FEED_NAME)

    for post in posts:
        fe = fg.add_entry()
        fe.title(post["title"])
        fe.description(post["description"])
        fe.link(href=post["link"])
        fe.id(post["link"])
        if post.get("date"):
            fe.published(post["date"])

    logger.info("Generated Atom feed with %d entries", len(posts))
    return fg


def main(full_reset: bool = False) -> bool:
    cache = load_cache(FEED_NAME)
    cached_entries = deserialize_entries(cache.get("entries", []))
    known = set() if full_reset else {e["link"] for e in cached_entries}

    html = fetch_page(BLOG_URL)
    links = discover_links(html)
    new_posts = fetch_new_articles(links, known)

    if full_reset or not cached_entries:
        mode = "full reset" if full_reset else "no cache exists"
        logger.info("Running full fetch (%s)", mode)
        posts = sort_posts_for_feed(new_posts, date_field="date")
    else:
        logger.info("Running incremental update")
        posts = merge_entries(new_posts, cached_entries)

    if not posts:
        logger.warning("No posts fetched — skipping feed update to avoid overwriting with empty feed")
        return False

    save_cache(FEED_NAME, posts)
    feed = generate_rss_feed(posts)
    save_atom_feed(feed, FEED_NAME)
    logger.info("Done!")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Czwórka (Polskie Radio) Atom feed")
    parser.add_argument("--full", action="store_true", help="Force full reset (ignore cache)")
    args = parser.parse_args()
    main(full_reset=args.full)
