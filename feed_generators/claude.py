"""Claude feed generator.

Aggregates the various Claude product update sources into one **Atom** feed
written to ``feeds/feed_claude.xml``:

    - Claude Blog                 https://claude.com/blog
    - Claude Code                  https://code.claude.com/docs/en/whats-new/rss.xml   (native RSS)
                                   https://code.claude.com/docs/en/changelog/rss.xml   (native RSS)
    - Claude Apps Release notes     https://support.claude.com/en/articles/12138966-release-notes  (HTML)
    - Claude Platform release notes https://platform.claude.com/docs/en/release-notes/overview         (Mintlify .md)
    - Claude Platform system prompts https://platform.claude.com/docs/en/release-notes/system-prompts  (Mintlify .md)

Source handling:
  * Blog          — listing card title + date (static HTML).
  * RSS feeds     — parsed natively; each item already has title/link/date.
  * Support page  — each dated ``<h3>`` (with a stable ``id``) becomes an entry;
                    the body text up to the next heading is the summary.
  * Platform pages — fetched as Mintlify raw markdown (``<path>.md``). The
                    overview is keyed by ``### <date>`` sections; the system
                    prompts page is keyed by ``## <model>`` sections (dated from
                    the first date inside each section).

History accumulates across hourly runs via the shared JSON cache
(``cache/claude_posts.json``); entries dedupe by link.
"""

import argparse
import re
import sys

import pytz
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from feedgen.feed import FeedGenerator

from utils import (
    DEFAULT_HEADERS,
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

FEED_NAME = "claude"
BLOG_URL = "https://claude.com/blog"

CLAUDE_BLOG_LISTING = "https://claude.com/blog"
CLAUDE_BLOG_BASE = "https://claude.com"

# Both Claude Code RSS sources fold under one "Claude Code" category. Each item
# keeps its own distinct title (e.g. "Week 22" vs "2.1.160") and link, so they
# stay separate entries; only the category label is shared.
RSS_SOURCES = [
    ("Claude Code", "https://code.claude.com/docs/en/whats-new/rss.xml"),
    ("Claude Code", "https://code.claude.com/docs/en/changelog/rss.xml"),
]

SUPPORT_RELEASE_NOTES = "https://support.claude.com/en/articles/12138966-release-notes"

# Mintlify pages: (label, html_url, markdown_url, section_heading_level, title_is_date)
PLATFORM_OVERVIEW = (
    "Claude Platform release notes",
    "https://platform.claude.com/docs/en/release-notes/overview",
    "https://platform.claude.com/docs/en/release-notes/overview.md",
)
PLATFORM_SYSPROMPTS = (
    "Claude Platform system prompts",
    "https://platform.claude.com/docs/en/release-notes/system-prompts",
    "https://platform.claude.com/docs/en/release-notes/system-prompts.md",
)

# Human dates, e.g. "May 28, 2026" / "Apr 08, 2026" / "Sept 9th, 2024".
DATE_RE = re.compile(
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December"
    r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})"
)
DATE_ONLY_RE = re.compile(r"^\s*" + DATE_RE.pattern + r"\s*$")

# Ordinal suffix on the day number ("12th") trips up dateutil; strip it.
_ORDINAL_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)", re.IGNORECASE)

MAX_ENTRIES = 150


def parse_date(date_str):
    """Parse a date string into a UTC datetime, or None on failure."""
    try:
        cleaned = _ORDINAL_RE.sub(r"\1", date_str)
        dt = date_parser.parse(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.UTC)
        return dt.astimezone(pytz.UTC)
    except (ValueError, TypeError, OverflowError) as e:
        logger.warning(f"Could not parse date '{date_str}': {e}")
        return None


def title_from_slug(href):
    slug = href.rstrip("/").split("/")[-1]
    return slug.replace("-", " ").replace("_", " ").strip().capitalize()


def slugify(text):
    """Mintlify/GitHub-style heading anchor: lowercase, non-alnum -> hyphen."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s


def clean_markdown(text, limit=500):
    """Reduce markdown to readable plain text for a feed summary."""
    text = re.sub(r"<[^>]+>", " ", text)                 # JSX/HTML components
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)      # images
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)   # links -> link text
    text = re.sub(r"[`*_>#]", " ", text)                   # md punctuation
    text = re.sub(r"^\s*[-+]\s+", "", text, flags=re.MULTILINE)  # bullets
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


# --------------------------------------------------------------------------- #
# Claude blog (static HTML listing)
# --------------------------------------------------------------------------- #


def scrape_claude_blog(known_links):
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


# --------------------------------------------------------------------------- #
# Native RSS feeds (What's new, Changelog)
# --------------------------------------------------------------------------- #


def scrape_rss(label, rss_url, known_links):
    entries = []
    try:
        soup = BeautifulSoup(fetch_page(rss_url), "xml")
    except Exception as e:
        logger.warning(f"Could not fetch {rss_url}: {e}")
        return entries

    for item in soup.find_all("item"):
        link_el = item.find("link")
        link = link_el.get_text(strip=True) if link_el else rss_url
        if not link or link in known_links:
            continue
        title_el = item.find("title")
        title = sanitize_xml(title_el.get_text(strip=True)) if title_el else label
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
            "source": label,
        })
        logger.info(f"  [{label}] {title}")
    return entries


# --------------------------------------------------------------------------- #
# Support release notes (Intercom HTML; dated <h3 id=...> sections)
# --------------------------------------------------------------------------- #


def scrape_support_release_notes(known_links):
    label = "Claude Apps Release notes"
    entries = []
    try:
        soup = BeautifulSoup(fetch_page(SUPPORT_RELEASE_NOTES), "html.parser")
    except Exception as e:
        logger.warning(f"Could not fetch {SUPPORT_RELEASE_NOTES}: {e}")
        return entries

    root = soup.find("main") or soup
    for h in root.find_all("h3"):
        head_text = h.get_text(" ", strip=True)
        if not DATE_ONLY_RE.match(head_text):
            continue
        date_obj = parse_date(head_text)
        anchor = h.get("id")
        link = f"{SUPPORT_RELEASE_NOTES}#{anchor}" if anchor else f"{SUPPORT_RELEASE_NOTES}#{slugify(head_text)}"
        if link in known_links:
            continue

        # Collect text from following elements until the next h2/h3.
        parts, seen_txt = [], set()
        for el in h.next_elements:
            name = getattr(el, "name", None)
            if name in ("h2", "h3") and el is not h:
                break
            if name in ("p", "li", "span"):
                t = el.get_text(" ", strip=True)
                if t and t not in seen_txt:
                    seen_txt.add(t)
                    parts.append(t)
        body = " ".join(parts).strip()
        # Lead phrase makes a better title than the bare date.
        lead = body.split(". ")[0][:90] if body else ""
        title = sanitize_xml(f"{lead} — {head_text}" if lead else f"Claude Apps — {head_text}")
        entries.append({
            "title": title,
            "link": link,
            "date": date_obj,
            "description": sanitize_xml(body or head_text)[:500],
            "source": label,
        })
        logger.info(f"  [{label}] {title}")
    return entries


# --------------------------------------------------------------------------- #
# Platform release notes & system prompts (Mintlify raw markdown)
# --------------------------------------------------------------------------- #


def _fetch_markdown(md_url):
    try:
        return fetch_page(md_url, headers=DEFAULT_HEADERS)
    except Exception as e:
        logger.warning(f"Could not fetch {md_url}: {e}")
        return None


def _split_md_sections(md_text, level):
    """Split markdown into [(heading, body)] for the given ATX heading level."""
    marker = "#" * level + " "
    sections, cur_head, cur_body = [], None, []
    for line in md_text.splitlines():
        if line.startswith(marker) and not line.startswith(marker + "#"):
            if cur_head is not None:
                sections.append((cur_head, "\n".join(cur_body)))
            cur_head = line[len(marker):].strip()
            cur_body = []
        elif cur_head is not None:
            cur_body.append(line)
    if cur_head is not None:
        sections.append((cur_head, "\n".join(cur_body)))
    return sections


def scrape_platform_overview(known_links):
    label, page_url, md_url = PLATFORM_OVERVIEW
    entries = []
    md = _fetch_markdown(md_url)
    if not md:
        return entries
    for heading, body in _split_md_sections(md, level=3):
        if not DATE_ONLY_RE.match(heading):
            continue  # only dated release sections
        date_obj = parse_date(heading)
        link = f"{page_url}#{slugify(heading)}"
        if link in known_links:
            continue
        title = sanitize_xml(f"Claude Platform — {heading}")
        entries.append({
            "title": title,
            "link": link,
            "date": date_obj,
            "description": sanitize_xml(clean_markdown(body) or heading),
            "source": label,
        })
        logger.info(f"  [{label}] {title}")
    return entries


def scrape_platform_sysprompts(known_links):
    label, page_url, md_url = PLATFORM_SYSPROMPTS
    entries = []
    md = _fetch_markdown(md_url)
    if not md:
        return entries
    for heading, body in _split_md_sections(md, level=2):
        # Sections are model names (e.g. "Claude Opus 4.7"); date is inside.
        m = DATE_RE.search(body)
        date_obj = parse_date(m.group(1)) if m else None
        link = f"{page_url}#{slugify(heading)}"
        if link in known_links:
            continue
        title = sanitize_xml(f"System prompt — {heading}")
        summary = clean_markdown(body)
        entries.append({
            "title": title,
            "link": link,
            "date": date_obj,
            "description": sanitize_xml(summary or heading),
            "source": label,
        })
        logger.info(f"  [{label}] {title}")
    return entries


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def scrape_all(known_links):
    new_entries = []
    logger.info("Scraping Claude Blog ...")
    new_entries += scrape_claude_blog(known_links)
    for label, url in RSS_SOURCES:
        logger.info(f"Scraping {label} ...")
        new_entries += scrape_rss(label, url, known_links)
    logger.info("Scraping Claude Apps Release notes ...")
    new_entries += scrape_support_release_notes(known_links)
    logger.info("Scraping Claude Platform release notes ...")
    new_entries += scrape_platform_overview(known_links)
    logger.info("Scraping Claude Platform system prompts ...")
    new_entries += scrape_platform_sysprompts(known_links)
    return new_entries


def generate_atom_feed(articles, feed_name=FEED_NAME):
    fg = FeedGenerator()
    fg.id(f"https://claude.com/{feed_name}")
    fg.title("Claude")
    fg.subtitle(
        "Claude product updates: the Claude blog, Claude Code (what's-new and "
        "changelog), Claude Apps release notes, and Claude Platform release "
        "notes and system prompts."
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
    merged = sort_posts_for_feed(merged, date_field="date")

    # Keep full history in the cache so already-seen links are never re-evaluated
    # on later runs; only the rendered feed is capped to the newest MAX_ENTRIES.
    save_cache(FEED_NAME, merged)

    feed_items = merged[-MAX_ENTRIES:] if len(merged) > MAX_ENTRIES else merged

    fg = generate_atom_feed(feed_items)
    save_atom_feed(fg)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the Claude Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
