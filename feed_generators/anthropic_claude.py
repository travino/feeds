"""Combined Anthropic + Claude feed generator.

Aggregates several Anthropic / Claude sources that lack a single shared feed
into one **Atom** feed written to ``feeds/feed_anthropic_claude.xml``:

    - Anthropic Newsroom      https://www.anthropic.com/news
    - Anthropic Research      https://www.anthropic.com/research
    - Anthropic Engineering   https://www.anthropic.com/engineering
    - Claude Blog             https://claude.com/blog
    - Claude Code Changelog   https://code.claude.com/docs/en/changelog/rss.xml

Two of the originally requested URLs are intentionally not included:
``https://www.anthropic.com/`` is a landing page (not an article stream), and
``https://www.anthropic.com/features`` returns HTTP 404.

The Anthropic listing pages render article cards in static HTML (no JS), so a
plain ``requests`` fetch is enough — no browser automation. Titles and
summaries for anthropic.com articles are read from each article's
``og:title`` / ``og:description`` meta tags; the Claude blog title comes from
the listing card; the changelog is parsed from its native RSS.

History accumulates across hourly runs via the shared JSON cache
(``cache/anthropic_claude_posts.json``); only links not already cached trigger
a per-article metadata fetch, so steady-state runs are cheap.
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
    fetch_page,
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

FEED_NAME = "anthropic_claude"
BLOG_URL = "https://www.anthropic.com/"

# Anthropic listing sources: (source label, listing URL, site base, href prefix)
ANTHROPIC_SOURCES = [
    ("Anthropic Newsroom", "https://www.anthropic.com/news", "https://www.anthropic.com", "/news/"),
    ("Anthropic Research", "https://www.anthropic.com/research", "https://www.anthropic.com", "/research/"),
    ("Anthropic Engineering", "https://www.anthropic.com/engineering", "https://www.anthropic.com", "/engineering/"),
]

CLAUDE_BLOG_LISTING = "https://claude.com/blog"
CLAUDE_BLOG_BASE = "https://claude.com"

CHANGELOG_RSS = "https://code.claude.com/docs/en/changelog/rss.xml"
CHANGELOG_LABEL = "Claude Code Changelog"

# Research listing also links team/index pages, which are not articles.
RESEARCH_SKIP = re.compile(r"^/research/(team/|$)")

# Human dates in cards, e.g. "May 28, 2026" / "Apr 08, 2026".
DATE_RE = re.compile(r"([A-Z][a-z]{2,8}\.?\s+\d{1,2},\s+\d{4})")

# Default og:description served site-wide on some anthropic.com pages; not a
# real per-article summary, so we drop it.
ANTHROPIC_BOILERPLATE = "Anthropic is an AI safety and research company"

# Polite delay between per-article metadata fetches.
SLEEP_BETWEEN = 0.4

# Cap the merged feed so the committed XML stays a reasonable size.
MAX_ENTRIES = 100


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


def title_from_slug(href):
    """Last-resort title derived from the URL slug."""
    slug = href.rstrip("/").split("/")[-1]
    return slug.replace("-", " ").replace("_", " ").strip().capitalize()


def _meta(soup, *keys):
    for key in keys:
        tag = soup.find("meta", property=key) or soup.find("meta", attrs={"name": key})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


def fetch_article_meta(url):
    """Return {'title', 'summary'} for an anthropic.com article via meta tags."""
    title = summary = None
    try:
        soup = BeautifulSoup(fetch_page(url), "html.parser")
        title = _meta(soup, "og:title", "twitter:title")
        if title:
            title = re.split(r"\s[\\|]\s", title)[0].strip()
        summary = _meta(soup, "og:description", "description")
        if summary and summary.startswith(ANTHROPIC_BOILERPLATE):
            summary = None
    except Exception as e:
        logger.warning(f"Could not fetch article meta for {url}: {e}")
    time.sleep(SLEEP_BETWEEN)
    return {"title": title, "summary": summary}


def scrape_anthropic(label, listing_url, base, prefix, known_links):
    """Scrape an Anthropic listing page; skip links already in the cache."""
    entries = []
    try:
        soup = BeautifulSoup(fetch_page(listing_url), "html.parser")
    except Exception as e:
        logger.warning(f"Could not fetch {listing_url}: {e}")
        return entries

    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith(prefix) or href == prefix or href in seen:
            continue
        if prefix == "/research/" and RESEARCH_SKIP.match(href):
            continue
        seen.add(href)

        text = a.get_text(" ", strip=True)
        m = DATE_RE.search(text)
        if not m:  # cards without a date aren't real articles
            continue
        date_obj = parse_date(m.group(1))
        link = href if href.startswith("http") else base + href

        if link in known_links:
            continue  # already cached, no need to refetch metadata

        meta = fetch_article_meta(link)
        title = sanitize_xml(meta["title"] or title_from_slug(href))
        summary = sanitize_xml(meta["summary"] or title)
        entries.append({
            "title": title,
            "link": link,
            "date": date_obj,
            "description": summary,
            "source": label,
        })
        logger.info(f"  [{label}] {title}")
    return entries


def scrape_claude_blog(known_links):
    """Scrape the Claude blog listing; titles come from the card text."""
    entries = []
    try:
        soup = BeautifulSoup(fetch_page(CLAUDE_BLOG_LISTING), "html.parser")
    except Exception as e:
        logger.warning(f"Could not fetch {CLAUDE_BLOG_LISTING}: {e}")
        return entries

    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("/blog/") or href == "/blog/" or href in seen:
            continue
        seen.add(href)
        link = CLAUDE_BLOG_BASE + href
        if link in known_links:
            continue

        # Climb to the smallest container whose text carries a date, then take
        # the title as everything before that date (minus "Read more").
        card, card_text, m = a, a.get_text(" ", strip=True), None
        for _ in range(5):
            m = DATE_RE.search(card_text)
            if m:
                break
            if not card.parent:
                break
            card = card.parent
            card_text = card.get_text(" ", strip=True)

        title, date_obj = None, None
        if m:
            date_obj = parse_date(m.group(1))
            head = re.sub(r"\bRead more\b", " ", card_text[: m.start()])
            head = re.sub(r"\s{2,}", " ", head).strip(" |·-—\u2022")
            title = head or None
        if not title:
            title = title_from_slug(href)

        title = sanitize_xml(title)
        entries.append({
            "title": title,
            "link": link,
            "date": date_obj,
            "description": title,
            "source": "Claude Blog",
        })
        logger.info(f"  [Claude Blog] {title}")
    return entries


def scrape_changelog(known_links):
    """Parse the Claude Code changelog's native RSS feed."""
    entries = []
    try:
        soup = BeautifulSoup(fetch_page(CHANGELOG_RSS), "xml")
    except Exception as e:
        logger.warning(f"Could not fetch {CHANGELOG_RSS}: {e}")
        return entries

    for item in soup.find_all("item"):
        link_el = item.find("link")
        link = link_el.get_text(strip=True) if link_el else CHANGELOG_RSS
        if link in known_links:
            continue
        title_el = item.find("title")
        title = sanitize_xml(title_el.get_text(strip=True)) if title_el else "Claude Code update"
        pub_el = item.find("pubDate")
        date_obj = parse_date(pub_el.get_text(strip=True)) if pub_el else None
        desc_el = item.find("description")
        if desc_el:
            desc = BeautifulSoup(desc_el.get_text(), "html.parser").get_text(" ", strip=True)
            desc = sanitize_xml(desc)[:500]
        else:
            desc = title
        entries.append({
            "title": title,
            "link": link,
            "date": date_obj,
            "description": desc or title,
            "source": CHANGELOG_LABEL,
        })
        logger.info(f"  [{CHANGELOG_LABEL}] {title}")
    return entries


def scrape_all(known_links):
    """Collect new entries from every source, skipping already-cached links."""
    new_entries = []
    for label, listing, base, prefix in ANTHROPIC_SOURCES:
        logger.info(f"Scraping {label} ...")
        new_entries += scrape_anthropic(label, listing, base, prefix, known_links)
    logger.info("Scraping Claude Blog ...")
    new_entries += scrape_claude_blog(known_links)
    logger.info("Scraping Claude Code Changelog ...")
    new_entries += scrape_changelog(known_links)
    return new_entries


def generate_atom_feed(articles, feed_name=FEED_NAME):
    """Build an Atom FeedGenerator from the merged article list."""
    fg = FeedGenerator()
    fg.id(f"https://www.anthropic.com/{feed_name}")
    fg.title("Anthropic & Claude — Combined Feed")
    fg.subtitle(
        "Anthropic Newsroom, Research, and Engineering posts, the Claude blog, "
        "and the Claude Code changelog, in one feed."
    )
    setup_feed_links(fg, BLOG_URL, feed_name)
    fg.language("en")
    fg.author({"name": "Anthropic"})

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
    """Write the feed to feeds/feed_<name>.xml in Atom format."""
    output_file = get_feeds_dir() / f"feed_{feed_name}.xml"
    fg.atom_file(str(output_file), pretty=True)
    logger.info(f"Saved Atom feed to {output_file}")
    return output_file


def main(full=False):
    """Scrape every source, merge with cache, and write the Atom feed."""
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
    merged = sort_posts_for_feed(merged, date_field="date")

    # sort_posts_for_feed returns ascending (feedgen reverses on write), so keep
    # the newest MAX_ENTRIES by taking the tail.
    if len(merged) > MAX_ENTRIES:
        merged = merged[-MAX_ENTRIES:]

    save_cache(FEED_NAME, merged)

    fg = generate_atom_feed(merged)
    save_atom_feed(fg)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the combined Anthropic/Claude Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
