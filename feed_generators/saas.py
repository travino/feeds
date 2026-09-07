"""Combined Atom feed for assorted SaaS / web-product vendors.

Merges three low-volume vendor feeds that previously lived on their own into a
single Atom stream written to ``feeds/feed_saas.xml``:

    - HashiCorp / HCP   blog (native Atom) + HCP changelog (scraped)
    - Bitly             blog + press room + MCP changelog
    - Common Ninja      blog
    - Vercel            blog (native Atom) + changelog (native RSS)
                        + Chat SDK / Flags SDK / Workflow SDK / AI Elements
                        docs feeds (native RSS)
    - Apify             blog (native RSS)
    - Zapier            blog (native RSS)
    - Fastly            blog (native RSS)
    - Postman           blog (native RSS) + app release notes (first-party JSON)
                        + press room (scraped)
    - Exa               changelog (native RSS) + blog (sitemap + per-post fetch)
    - Home Assistant    blog (native Atom)
    - Upstash           Workflow SDK releases (native Atom; blog lives in SkillsLLM)
    - Xweather          blog (scraped index) + weather-api changelog (scraped)
                        + mcp-server changelog (scraped)
    - Cursor            changelog (native RSS) + blog (scraped dated anchors)
    - NeuralTrust       resources / blog (scraped dated anchors)
    - Abnormal          blog + newsroom press releases (scraped dated anchors)
    - Character.AI      blog (native RSS)
    - Astral Codex Ten  Substack (native RSS)
    - Behance           blog (FeedBurner RSS)
    - CodeRabbit        blog + changelog (native RSS) + newsroom (scraped)
    - Netlify           blog + changelog + knowledge base (native RSS)
    - Stripe            newsroom + developer blog + API changelog (scraped)

Note: exa.ai/research is a client-rendered listing with no sitemap entries and
no server-rendered post list, so it isn't aggregated here (would need a
browser to enumerate posts).

Each source's parser is reused verbatim from its original module
(``hcp``, ``bitly``, ``commoninja``), so there is exactly one
place that knows how to scrape each site. This generator only normalizes the
entries to a common shape, tags every entry with a per-vendor ``<category>``,
and keeps one rolling JSON cache (``cache/saas_posts.json``) so history
survives even when a source truncates its listing.

HCP entries carry rich HTML bodies (``content_html``) which are emitted as
``<content type="html">``; the other sources only have plain summaries.

Usage:
    python saas.py          # incremental: merge new entries into cache
    python saas.py --full   # ignore cache, rebuild from sources only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

import bitly
import commoninja
import hcp
import multi_rss
from enrich import enrich_entries
from utils import (
    add_entry_media,
    allocate_fair_share,
    deserialize_entries,
    load_cache,
    merge_entries,
    sanitize_xml,
    save_atom_feed,
    save_cache,
    setup_feed_extensions,
    setup_feed_links,
    setup_logging,
    sort_posts_for_feed,
    stable_fallback_date,
)

logger = setup_logging()

FEED_NAME = "saas"
FEED_TITLE = "SaaS vendors"
FEED_SUBTITLE = (
    "Combined updates from HashiCorp / HCP (blog + changelog), "
    "Bitly (blog + press + MCP changelog), Common Ninja, "
    "Vercel (blog + changelog + SDK docs), Apify, Zapier, Fastly, "
    "Postman (blog + app release notes + press), "
    "Exa (blog + changelog), Home Assistant, "
    "Upstash Workflow releases, "
    "Xweather (blog + API + MCP changelogs), "
    "Cursor (blog + changelog), NeuralTrust, "
    "Abnormal (blog + newsroom), Character.AI, "
    "Astral Codex Ten, Behance (blog), CodeRabbit (blog + changelog + newsroom), "
    "Netlify (blog + changelog + knowledge base), and "
    "Stripe (newsroom + developer blog + API changelog)."
)
BLOG_URL = "https://www.hashicorp.com/blog"
MAX_ENTRIES = 600  # all vendors share one archive
PER_SOURCE_CAP = 50  # stop any single high-churn source from swamping the feed

_TAG_PREFIX_RE = re.compile(r"^\[[^\]]+\]\s*")


def _text(html: str) -> str:
    """Plain-text rendering of an HTML fragment, collapsed and trimmed."""
    if not html:
        return ""
    return re.sub(r"\s+", " ", BeautifulSoup(html, "html.parser").get_text(" ", strip=True)).strip()


# --------------------------------------------------------------------------- #
# Per-vendor adapters: reuse the original scrapers, normalize to one shape
#   {id, title, link, date, description, content_html?, source}
# --------------------------------------------------------------------------- #
def collect_hcp() -> list[dict]:
    """HashiCorp blog (native Atom) + HCP changelog (scraped). Both already
    return rich HTML in ``summary``; relabel the source and drop the redundant
    ``[Blog]`` / ``[Changelog]`` title prefix (we tag via <category>)."""
    out: list[dict] = []
    label = {"Blog": "HashiCorp Blog", "Changelog": "HCP Changelog"}
    try:
        raw = hcp.fetch_blog() + hcp.fetch_changelog()
    except Exception as exc:
        logger.warning("HCP sources failed: %s", exc)
        return out
    for e in raw:
        body = e.get("summary") or ""
        out.append({
            "id": e["id"],
            "title": sanitize_xml(_TAG_PREFIX_RE.sub("", e["title"])),
            "link": e["link"],
            "date": e.get("date"),
            "description": sanitize_xml(_text(body))[:500] or sanitize_xml(_TAG_PREFIX_RE.sub("", e["title"])),
            "content_html": body or None,
            "source": label.get(e.get("source"), e.get("source") or "HashiCorp"),
        })
    logger.info("HCP: %d entries", len(out))
    return out


def collect_bitly(known_links: set[str]) -> list[dict]:
    """Bitly blog + press + MCP changelog via bitly.scrape_all (already in the
    common {title, link, date, description, source} shape)."""
    out: list[dict] = []
    try:
        for e in bitly.scrape_all(known_links):
            out.append({
                "id": e["link"],
                "title": e["title"],
                "link": e["link"],
                "date": e.get("date"),
                "description": e.get("description") or e["title"],
                "content_html": None,
                "source": e.get("source") or "Bitly",
            })
    except Exception as exc:
        logger.warning("Bitly sources failed: %s", exc)
    logger.info("Bitly: %d entries", len(out))
    return out


# --------------------------------------------------------------------------- #
# Native RSS/Atom vendor feeds — parsed via the shared multi_rss helper.
# (label, url, cap): cap trims high-volume archives to the most recent items.
# --------------------------------------------------------------------------- #
# Svelte is deliberately absent: js_node.py already carries
# https://svelte.dev/blog/rss.xml, and keeping it here published every Svelte
# post twice, once in each feed.
NATIVE_FEEDS = [
    ("Vercel", "https://vercel.com/atom", 40),
    ("Vercel Changelog", "https://vercel.com/changelog/rss.xml", 40),
    ("Netlify Blog", "https://www.netlify.com/feed.xml", 40),
    ("Netlify Changelog", "https://www.netlify.com/changelog/feed.xml", 40),
    ("Netlify Knowledge Base", "https://www.netlify.com/knowledge-base/feed.xml", 40),
    ("Chat SDK", "https://chat-sdk.dev/rss.xml", 40),
    ("Flags SDK", "https://flags-sdk.dev/rss.xml", 40),
    ("Workflow SDK", "https://workflow-sdk.dev/rss.xml", 40),
    ("AI Elements", "https://elements.ai-sdk.dev/rss.xml", 40),
    ("Apify", "https://blog.apify.com/rss/", None),
    ("Zapier", "https://zapier.com/blog/feeds/latest/", None),
    ("Fastly", "https://www.fastly.com/blog_rss.xml", 40),
    ("Postman", "https://blog.postman.com/feed/", 40),
    ("Exa Changelog", "https://exa.ai/docs/changelog/rss.xml", 40),
    ("Home Assistant", "https://www.home-assistant.io/atom.xml", 40),
    (
        "Upstash Workflow Releases",
        "https://github.com/upstash/workflow-js/releases.atom",
        40,
    ),
    ("Cursor Changelog", "https://cursor.com/changelog/rss.xml", 40),
    ("CodeRabbit Blog", "https://www.coderabbit.ai/feed", 50),
    ("CodeRabbit Changelog", "https://docs.coderabbit.ai/changelog/rss.xml", 40),
    ("Character.AI", "https://blog.character.ai/rss/", 40),
    ("Astral Codex Ten", "https://www.astralcodexten.com/feed", 40),
    ("Behance Blog", "http://feeds.feedburner.com/behance/vorr", 40),
]

# Sources intentionally moved to another aggregate. Filter their old cache rows
# so the migration takes effect on the first post-merge generation.
RETIRED_CACHE_SOURCES = {"Upstash Blog", "Upstash Workflow Changelog"}


def _active_cached_entries(entries: list[dict]) -> list[dict]:
    """Drop cached rows for sources no longer maintained by this feed."""
    return [e for e in entries if e.get("source") not in RETIRED_CACHE_SOURCES]


def collect_native_feeds(known_links: set[str]) -> list[dict]:
    """Pull each native RSS/Atom vendor feed via multi_rss.scrape_feed and
    normalize to the saas entry shape. Per-source failures are isolated."""
    out: list[dict] = []
    for label, url, cap in NATIVE_FEEDS:
        try:
            for e in multi_rss.scrape_feed(label, url, known_links, cap=cap):
                out.append({
                    "id": e["link"],
                    "title": e["title"],
                    "link": e["link"],
                    "date": e.get("date"),
                    "description": e.get("description") or e["title"],
                    "content_html": None,
                    "source": label,
                })
        except Exception as exc:
            logger.warning("%s feed failed: %s", label, exc)
    logger.info("Native feeds: %d entries", len(out))
    return out


CODERABBIT_NEWSROOM_URL = "https://www.coderabbit.ai/newsroom"
CODERABBIT_NEWSROOM_MAX = 50
POSTMAN_APP_RELEASE_NOTES_URL = "https://www.postman.com/release-notes/postman-app/"
POSTMAN_APP_RELEASE_NOTES_DATA_URL = (
    "https://mkt.cdn.postman.com/www-next/release-notes/app-release-notes.json"
)
POSTMAN_APP_RELEASE_NOTES_MAX = 40
_POSTMAN_RELEASE_DATE_RE = re.compile(r"(?m)^[A-Z][a-z]+ \d{1,2}, 20\d{2}\s*$")
_POSTMAN_VERSION_RE = re.compile(r"^(\d+)\.\d+\.\d+(?:[-+][\w.-]+)?$")
_POSTMAN_MD_LINK_RE = re.compile(r"!?\[([^]\n]+)\]\([^)]*\)")


def doc_sources():
    return [
        ("CodeRabbit Newsroom", CODERABBIT_NEWSROOM_URL),
        ("Postman App Release Notes", POSTMAN_APP_RELEASE_NOTES_URL),
        ("Stripe Newsroom", STRIPE_NEWSROOM_URL),
        ("Stripe Developer Blog", STRIPE_DEV_URL),
        ("Stripe Changelog", STRIPE_CHANGELOG_URL),
    ]


def collect_coderabbit_newsroom(known_links: set[str]) -> list[dict]:
    """Scrape CodeRabbit's server-rendered newsroom story cards."""
    out: list[dict] = []
    try:
        html = multi_rss.get_html(CODERABBIT_NEWSROOM_URL)
    except Exception as exc:
        logger.warning("CodeRabbit Newsroom fetch failed: %s", exc)
        return out
    if not html:
        return out

    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    for anchor in soup.select("a[href^='/newsroom/']"):
        href = anchor.get("href", "").split("?", 1)[0].split("#", 1)[0]
        title_el = anchor.find("h3")
        time_el = anchor.find("time", attrs={"datetime": True})
        if not href or not title_el or not time_el:
            continue
        link = "https://www.coderabbit.ai" + href
        if link in seen or link in known_links:
            continue
        title = sanitize_xml(title_el.get_text(" ", strip=True))
        if not title:
            continue
        desc_el = anchor.find("p")
        description = sanitize_xml(desc_el.get_text(" ", strip=True)) if desc_el else title
        seen.add(link)
        out.append({
            "id": link,
            "title": title[:200],
            "link": link,
            "date": multi_rss.parse_date(time_el.get("datetime")) or stable_fallback_date(link),
            "description": description[:500] or title,
            "content_html": None,
            "source": "CodeRabbit Newsroom",
        })

    out.sort(key=lambda e: e["date"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    logger.info("CodeRabbit Newsroom: %d entries", len(out))
    return out[:CODERABBIT_NEWSROOM_MAX]


def _postman_release_description(content: str, title: str) -> str:
    """Turn one release-note Markdown body into a compact plain summary."""
    lines = content.splitlines()
    if lines and lines[0].lstrip().startswith("## "):
        lines = lines[1:]
    if lines and _POSTMAN_RELEASE_DATE_RE.fullmatch(lines[0].strip()):
        lines = lines[1:]
    body = "\n".join(lines)
    body = _POSTMAN_MD_LINK_RE.sub(r"\1", body)
    body = re.sub(r"(?m)^#{1,6}\s*", "", body)
    body = re.sub(r"[*_`]+", "", body)
    body = re.sub(r"(?m)^\s*[-+]\s+", "", body)
    body = sanitize_xml(re.sub(r"\s+", " ", body).strip())
    return body[:500] or title


def parse_postman_app_release_notes(raw: str, known_links: set[str] | None = None) -> list[dict]:
    """Parse Postman's first-party app release-notes JSON, newest major only."""
    known_links = known_links or set()
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    notes = payload.get("notes") if isinstance(payload, dict) else None
    if not isinstance(notes, list):
        return []

    majors = []
    for note in notes:
        version = str(note.get("version") or "") if isinstance(note, dict) else ""
        match = _POSTMAN_VERSION_RE.fullmatch(version.strip())
        if match:
            majors.append(int(match.group(1)))
    if not majors:
        return []
    current_major = max(majors)

    out: list[dict] = []
    seen: set[str] = set()
    for note in notes:
        if not isinstance(note, dict):
            continue
        version = str(note.get("version") or "").strip()
        match = _POSTMAN_VERSION_RE.fullmatch(version)
        if not match or int(match.group(1)) != current_major:
            continue
        content = str(note.get("content") or "").strip()
        title = sanitize_xml(f"Postman {version}")
        anchor = re.sub(r"[^\w-]+", "", version.replace(".", "-").lower())
        link = f"{POSTMAN_APP_RELEASE_NOTES_URL}#{anchor}"
        if link in known_links or link in seen:
            continue
        date_match = _POSTMAN_RELEASE_DATE_RE.search(content)
        date = multi_rss.parse_date(date_match.group(0)) if date_match else None
        if date is None:
            date = multi_rss.parse_date(note.get("createdAt"))
        out.append({
            "id": link,
            "title": title,
            "link": link,
            "date": date or stable_fallback_date(link),
            "description": _postman_release_description(content, title),
            "content_html": None,
            "source": "Postman App Release Notes",
        })
        seen.add(link)

    out.sort(key=lambda entry: entry["date"], reverse=True)
    return out[:POSTMAN_APP_RELEASE_NOTES_MAX]


def collect_postman_app_release_notes(known_links: set[str]) -> list[dict]:
    """Fetch Postman's app release notes from the JSON used by its own frontend."""
    raw = multi_rss.get_html(POSTMAN_APP_RELEASE_NOTES_DATA_URL)
    if not raw:
        return []
    entries = parse_postman_app_release_notes(raw, known_links)
    logger.info("Postman App Release Notes: %d entries", len(entries))
    return entries


import datetime as _dt  # noqa: E402

# Postman press page: no feed. Each release is an <h3> title linking to a
# BusinessWire URL whose /home/<YYYYMMDD...> segment carries the date.
POSTMAN_PRESS_URL = "https://www.postman.com/company/press-media/"

_BW_DATE_RE = re.compile(r"/home/(20\d{2})(\d{2})(\d{2})")


def collect_postman_press(known_links: set[str]) -> list[dict]:
    out: list[dict] = []
    try:
        html = multi_rss.get_html(POSTMAN_PRESS_URL)
    except Exception as exc:
        logger.warning("Postman press fetch failed: %s", exc)
        return out
    if not html:
        return out
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    for h3 in soup.find_all("h3"):
        title = h3.get_text(" ", strip=True)
        if not title:
            continue
        a = h3.find("a", href=True) or h3.find_parent("a", href=True) or h3.find_next("a", href=True)
        if not a:
            continue
        link = a["href"].split("?")[0]
        if link in seen or link in known_links:
            continue
        m = _BW_DATE_RE.search(link)
        date = None
        if m:
            try:
                date = _dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=_dt.timezone.utc)
            except ValueError:
                date = None
        seen.add(link)
        out.append({
            "id": link,
            "title": sanitize_xml(title[:200]),
            "link": link,
            "date": date,
            "description": sanitize_xml(title[:200]),
            "content_html": None,
            "source": "Postman Press",
        })
    logger.info("Postman Press: %d entries", len(out))
    return out


def collect_commoninja() -> list[dict]:
    """Common Ninja blog: fetch the listing and reuse its card parser."""
    out: list[dict] = []
    try:
        html = commoninja.fetch_listing()
        if html:
            for e in commoninja.parse_items(html):
                out.append({
                    "id": e["link"],
                    "title": e["title"],
                    "link": e["link"],
                    "date": e.get("date") or stable_fallback_date(e["link"]),
                    "description": e.get("description") or e["title"],
                    "content_html": None,
                    "source": "Common Ninja",
                })
    except Exception as exc:
        logger.warning("Common Ninja source failed: %s", exc)
    logger.info("Common Ninja: %d entries", len(out))
    return out


# --------------------------------------------------------------------------- #
# Exa: changelog is native RSS (see NATIVE_FEEDS); the blog has no feed and
# its listing page is client-rendered, but the sitemap stamps every
# /blog/<slug> with a real <lastmod> and each post page is server-rendered
# with a proper <title>/<meta description> — same discover+fetch shape as
# skillsllm.py's sitemap sources.
# --------------------------------------------------------------------------- #
EXA_SITEMAP_URL = "https://exa.ai/sitemap.xml"
EXA_BLOG_MAX = 30
_EXA_TITLE_SUFFIX_RE = re.compile(r"\s*\|\s*Exa Blog\s*$")


def collect_exa_blog(known_links: set[str]) -> list[dict]:
    out: list[dict] = []
    try:
        xml = multi_rss.get_html(EXA_SITEMAP_URL)
    except Exception as exc:
        logger.warning("Exa sitemap fetch failed: %s", exc)
        return out
    if not xml:
        logger.warning("Exa sitemap unavailable; continuing")
        return out
    soup = BeautifulSoup(xml, "xml")
    candidates = []
    for url_el in soup.find_all("url"):
        loc_el = url_el.find("loc")
        if not loc_el:
            continue
        loc = loc_el.get_text(strip=True)
        if "/blog/" not in loc or loc.rstrip("/").endswith("/blog"):
            continue
        lastmod_el = url_el.find("lastmod")
        date = multi_rss.parse_date(lastmod_el.get_text(strip=True)) if lastmod_el else None
        candidates.append((loc, date))
    candidates.sort(key=lambda t: (t[1] or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)

    for link, date in candidates[:EXA_BLOG_MAX]:
        if link in known_links:
            continue
        try:
            html = multi_rss.get_html(link)
            if not html:
                continue
            page = BeautifulSoup(html, "html.parser")
            title_el = page.find("title")
            title = sanitize_xml(title_el.get_text(strip=True)) if title_el else ""
            title = _EXA_TITLE_SUFFIX_RE.sub("", title).strip()
            if not title:
                logger.warning("Exa Blog: no usable title for %s; skipping", link)
                continue
            desc_el = page.find("meta", attrs={"name": "description"})
            description = sanitize_xml(desc_el["content"].strip()) if desc_el and desc_el.get("content") else title
            out.append({
                "id": link,
                "title": title,
                "link": link,
                "date": date or stable_fallback_date(link),
                "description": description or title,
                "content_html": None,
                "source": "Exa Blog",
            })
        except Exception as exc:
            logger.warning("Exa Blog: skipping %s: %s", link, exc)
    logger.info("Exa Blog: %d entries", len(out))
    return out


# --------------------------------------------------------------------------- #
# Xweather blog: no feed, but the index is server-rendered — every post is an
# <article> with a cover-link, an h2/h3 title, and either a <time datetime>
# (list cards) or a plain date span (the hero card). Scraped directly, no
# per-post fetch needed.
# --------------------------------------------------------------------------- #
XWEATHER_BLOG_URL = "https://www.xweather.com/blog"
_XWEATHER_DATE_RE = re.compile(r"[A-Z][a-z]{2,8} \d{1,2}, 20\d{2}")


def collect_xweather_blog() -> list[dict]:
    out: list[dict] = []
    try:
        html = multi_rss.get_html(XWEATHER_BLOG_URL)
    except Exception as exc:
        logger.warning("Xweather Blog fetch failed: %s", exc)
        return out
    if not html:
        logger.warning("Xweather Blog unavailable; continuing")
        return out
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    for art in soup.find_all("article"):
        a = art.find("a", class_="cover-link", href=True)
        if not a:
            continue
        heading = a.find(["h2", "h3"])
        if not heading:
            continue
        title = sanitize_xml(heading.get_text(" ", strip=True))
        if not title:
            continue
        href = a["href"]
        link = href if href.startswith("http") else "https://www.xweather.com" + href
        if link in seen:
            continue
        seen.add(link)

        date = None
        time_el = art.find("time")
        if time_el and time_el.get("datetime"):
            date = multi_rss.parse_date(time_el["datetime"])
        if date is None:
            date_el = art.find("span", string=_XWEATHER_DATE_RE)
            if date_el:
                date = multi_rss.parse_date(date_el.get_text(strip=True))

        desc_el = art.find("div", class_=re.compile("simpleRichText"))
        description = _text(str(desc_el)) if desc_el else title

        out.append({
            "id": link,
            "title": title,
            "link": link,
            "date": date or stable_fallback_date(link),
            "description": sanitize_xml(description)[:500] or title,
            "content_html": None,
            "source": "Xweather Blog",
        })
    logger.info("Xweather Blog: %d entries", len(out))
    return out


# --------------------------------------------------------------------------- #
# Xweather docs changelogs (weather-api, mcp-server): Nextra-style single
# page, ``<h2 id="..">version</h2>`` followed by a sibling ``<p>`` date
# (sometimes wrapped in ``<em>``, sometimes not) and a sibling ``<ul>`` of
# bullet points, newest first. No per-entry permalink, so the h2's own id
# becomes a stable ``#fragment``.
# --------------------------------------------------------------------------- #
XWEATHER_CHANGELOGS = [
    ("Xweather Weather API Changelog", "https://www.xweather.com/docs/weather-api/changelog"),
    ("Xweather MCP Server Changelog", "https://www.xweather.com/docs/mcp-server/changelog"),
]
CHANGELOG_MAX_ENTRIES = 30


def _parse_docs_changelog(html: str, base_url: str, label: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for h2 in soup.find_all("h2", id=True):
        version = h2.get_text(strip=True)
        if not version:
            continue
        date = None
        p = h2.find_next_sibling("p")
        if p:
            em = p.find("em")
            date_text = em.get_text(strip=True) if em else p.get_text(strip=True)
            date = multi_rss.parse_date(date_text)
        bullets = []
        ul = h2.find_next_sibling("ul")
        if ul:
            bullets = [li.get_text(" ", strip=True) for li in ul.find_all("li")]
        description = "; ".join(bullets)[:500] or version
        link = f"{base_url}#{h2['id']}"
        out.append({
            "id": link,
            "title": sanitize_xml(f"{label} {version}"),
            "link": link,
            "date": date or stable_fallback_date(link),
            "description": sanitize_xml(description),
            "content_html": None,
            "source": label,
        })
    out.sort(key=lambda e: e["date"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return out[:CHANGELOG_MAX_ENTRIES]


def collect_xweather_changelogs() -> list[dict]:
    out: list[dict] = []
    for label, url in XWEATHER_CHANGELOGS:
        try:
            html = multi_rss.get_html(url)
            if not html:
                logger.warning("%s fetch failed", label)
                continue
            out += _parse_docs_changelog(html, url, label)
        except Exception as exc:
            logger.warning("%s failed: %s", label, exc)
    logger.info("Xweather changelogs: %d entries", len(out))
    return out


# --------------------------------------------------------------------------- #
# Generic dated-anchor listing scraper.
#
# Cursor blog, NeuralTrust resources, and Abnormal blog + newsroom are all the
# same shape: a server-rendered page that is a flat list of <a href="/post">
# whose visible text carries a date ("Jul 8, 2026" / "July 16, 2026") plus the
# post title. One parser handles them all -- match post anchors by an href
# pattern, pull the date out of the anchor text, and take the remaining text as
# the title. Non-post anchors (nav, category chips, undated CTAs) carry no date
# and are dropped.
# --------------------------------------------------------------------------- #
_ANCHOR_DATE_RE = re.compile(r"[A-Z][a-z]{2,8} \d{1,2},? 20\d\d")
_READMORE_RE = re.compile(r"\bread more\b", re.I)
_TITLE_SITE_SUFFIX_RE = re.compile(r"\s*[|\u00b7\u2013\u2014-]\s*[A-Za-z. ]{2,20}\s*$")


def _clean_title_from_page(link: str) -> str | None:
    """Fetch a post page and return a clean title (h1 -> og:title -> <title>),
    stripping a trailing ' | Site' / ' \u00b7 Site' suffix. Used for listings
    whose anchor text mixes the title with category/author/body noise."""
    try:
        html = multi_rss.get_html(link)
    except Exception:
        return None
    if not html:
        return None
    page = BeautifulSoup(html, "html.parser")
    title = ""
    h1 = page.find("h1")
    if h1:
        title = h1.get_text(" ", strip=True)
    if not title:
        og = page.find("meta", property="og:title")
        if og and og.get("content"):
            title = og["content"].strip()
    if not title:
        t = page.find("title")
        title = t.get_text(strip=True) if t else ""
    title = _TITLE_SITE_SUFFIX_RE.sub("", title).strip()
    return sanitize_xml(title) or None


def collect_dated_anchors(url: str, source: str, href_pat: str, base: str,
                          cap: int = 30, fetch_title: bool = False) -> list[dict]:
    out: list[dict] = []
    try:
        html = multi_rss.get_html(url)
    except Exception as exc:
        logger.warning("%s fetch failed: %s", source, exc)
        return out
    if not html:
        logger.warning("%s unavailable; continuing", source)
        return out
    soup = BeautifulSoup(html, "html.parser")
    pat = re.compile(href_pat)
    seen: set[str] = set()
    for a in soup.select("a[href]"):
        href = a.get("href", "").split("?")[0].split("#")[0]
        if not pat.search(href.rstrip("/")):
            continue
        link = href if href.startswith("http") else base + href
        if link in seen:
            continue
        text = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        m = _ANCHOR_DATE_RE.search(text)
        if not m:
            continue
        after = text[m.end():].strip(" \u00b7\u2014-|")
        before = text[: m.start()].strip(" \u00b7\u2014-|")
        title = after if len(after) >= 12 else before
        title = _READMORE_RE.sub("", title).strip(" \u00b7\u2014-|")
        if len(title) < 12:
            continue
        seen.add(link)
        if fetch_title:
            clean = _clean_title_from_page(link)
            if clean and len(clean) >= 8:
                title = clean
        out.append({
            "id": link,
            "title": sanitize_xml(title[:200]),
            "link": link,
            "date": multi_rss.parse_date(m.group(0)),
            "description": sanitize_xml(title[:200]),
            "content_html": None,
            "source": source,
        })
    out.sort(key=lambda e: e["date"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    logger.info("%s: %d entries", source, len(out))
    return out[:cap]


# (url, source, href_pat, base, fetch_title): fetch_title pulls each post's
# real title from its page when the listing anchor text is noisy (Cursor mixes
# in category/author/read-time; Abnormal press cards trail into the body).
DATED_ANCHOR_SOURCES = [
    ("https://cursor.com/blog", "Cursor Blog", r"/blog/[a-z0-9-]+$", "https://cursor.com", True),
    ("https://neuraltrust.ai/resources", "NeuralTrust", r"/blog/[a-z0-9-]+$", "https://neuraltrust.ai", False),
    ("https://abnormal.ai/blog", "Abnormal Blog", r"/blog/[a-z0-9-]+$", "https://abnormal.ai", False),
    ("https://abnormal.ai/newsroom/press-releases", "Abnormal Newsroom",
     r"/newsroom/press-releases/[a-z0-9-]+$", "https://abnormal.ai", True),
]


def collect_dated_anchor_sources() -> list[dict]:
    out: list[dict] = []
    for url, source, href_pat, base, fetch_title in DATED_ANCHOR_SOURCES:
        out += collect_dated_anchors(url, source, href_pat, base, fetch_title=fetch_title)
    return out



# --------------------------------------------------------------------------- #
# Stripe: all three requested surfaces are server-rendered but expose no
# reliable native feed. Keep the public URLs as the documented sources and use
# their fuller listing pages internally where available.
# --------------------------------------------------------------------------- #
STRIPE_NEWSROOM_URL = "https://stripe.com/en-pl/newsroom"
_STRIPE_NEWSROOM_LIST_URL = "https://stripe.com/en-pl/newsroom/news"
STRIPE_DEV_URL = "https://stripe.dev/"
_STRIPE_DEV_BLOG_URL = "https://stripe.dev/blog"
STRIPE_CHANGELOG_URL = "https://docs.stripe.com/changelog"
STRIPE_MAX_ENTRIES = 50
_STRIPE_NEWS_DATE_RE = re.compile(r"\b\d{1,2}\s+[A-Z][a-z]+\s+20\d{2}\b")
_STRIPE_DEV_DATE_RE = re.compile(r"\b20\d{2}\.\d{1,2}\.\d{1,2}\b")
_STRIPE_CHANGELOG_LINK_RE = re.compile(
    r"/changelog/(?:[a-z0-9-]+/)?(20\d{2}-\d{2}-\d{2})/[^?#]+",
    re.I,
)


def _stripe_date(value: str):
    """Parse Stripe's three listing-date formats into UTC datetimes."""
    parsed = multi_rss.parse_date(value)
    if parsed is not None:
        return parsed
    for fmt in ("%d %B %Y", "%Y.%m.%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _stripe_link(href: str, base: str) -> str:
    """Normalize a Stripe listing href to a stable absolute URL."""
    href = (href or "").split("?", 1)[0].split("#", 1)[0]
    return href if href.startswith("http") else base + href


def parse_stripe_newsroom(html: str, known_links: set[str] | None = None) -> list[dict]:
    """Parse Stripe newsroom cards without depending on presentation classes."""
    known_links = known_links or set()
    grouped: dict[str, list[str]] = {}
    soup = BeautifulSoup(html or "", "html.parser")
    for anchor in soup.select("a[href*='/newsroom/news/']"):
        link = _stripe_link(anchor.get("href", ""), "https://stripe.com")
        if link.rstrip("/").endswith("/newsroom/news"):
            continue
        anchor_text = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        if anchor_text:
            grouped.setdefault(link, []).append(anchor_text)

    out = []
    for link, texts in grouped.items():
        if link in known_links:
            continue
        date_text = next((item for item in texts if _STRIPE_NEWS_DATE_RE.fullmatch(item)), "")
        titles = [
            item
            for item in texts
            if not _STRIPE_NEWS_DATE_RE.fullmatch(item)
            and item.lower() not in {"product", "corporate", "latest"}
            and len(item) >= 12
        ]
        if not titles:
            continue
        title = sanitize_xml(max(titles, key=len))[:200]
        out.append(
            {
                "id": link,
                "title": title,
                "link": link,
                "date": _stripe_date(date_text) or stable_fallback_date(link),
                "description": title,
                "content_html": None,
                "source": "Stripe Newsroom",
            }
        )
    out.sort(key=lambda entry: entry["date"], reverse=True)
    return out[:STRIPE_MAX_ENTRIES]


def parse_stripe_dev_blog(html: str, known_links: set[str] | None = None) -> list[dict]:
    """Parse stripe.dev cards, whose visible metadata includes YYYY.M.DD."""
    known_links = known_links or set()
    soup = BeautifulSoup(html or "", "html.parser")
    out, seen = [], set()
    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "")
        if not re.search(r"(?:^|stripe\.dev)/blog/[^/?#]+", href):
            continue
        link = _stripe_link(href, "https://stripe.dev")
        if link in seen or link in known_links:
            continue
        card = anchor
        card_text = re.sub(r"\s+", " ", card.get_text(" ", strip=True)).strip()
        for _ in range(5):
            if _STRIPE_DEV_DATE_RE.search(card_text):
                break
            if not getattr(card, "parent", None):
                break
            card = card.parent
            card_text = re.sub(r"\s+", " ", card.get_text(" ", strip=True)).strip()
        date_match = _STRIPE_DEV_DATE_RE.search(card_text)
        if not date_match:
            continue
        title = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        title = _STRIPE_DEV_DATE_RE.sub("", title).strip(" ·—-|")
        if len(title) < 8 or title.lower() in {"read", "read more"}:
            heading = card.find(["h1", "h2", "h3", "h4"])
            title = heading.get_text(" ", strip=True) if heading else ""
        if not title:
            continue
        title = sanitize_xml(title)[:200]
        seen.add(link)
        out.append(
            {
                "id": link,
                "title": title,
                "link": link,
                "date": _stripe_date(date_match.group(0)) or stable_fallback_date(link),
                "description": title,
                "content_html": None,
                "source": "Stripe Developer Blog",
            }
        )
    out.sort(key=lambda entry: entry["date"], reverse=True)
    return out[:STRIPE_MAX_ENTRIES]


def parse_stripe_changelog(html: str, known_links: set[str] | None = None) -> list[dict]:
    """Parse dated Stripe API changelog links and canonicalize Markdown URLs."""
    known_links = known_links or set()
    soup = BeautifulSoup(html or "", "html.parser")
    out, seen = [], set()
    for anchor in soup.select("a[href*='/changelog/']"):
        link = _stripe_link(anchor.get("href", ""), "https://docs.stripe.com")
        match = _STRIPE_CHANGELOG_LINK_RE.search(link)
        if not match:
            continue
        if link.endswith(".md"):
            link = link[:-3]
        if link in seen or link in known_links:
            continue
        title = sanitize_xml(anchor.get_text(" ", strip=True))[:200]
        if not title:
            continue
        seen.add(link)
        out.append(
            {
                "id": link,
                "title": title,
                "link": link,
                "date": _stripe_date(match.group(1)) or stable_fallback_date(link),
                "description": title,
                "content_html": None,
                "source": "Stripe Changelog",
            }
        )
    out.sort(key=lambda entry: entry["date"], reverse=True)
    return out[:STRIPE_MAX_ENTRIES]


def collect_stripe(known_links: set[str]) -> list[dict]:
    """Collect Stripe surfaces independently so one outage cannot sink the rest."""
    out: list[dict] = []
    sources = (
        ("Stripe Newsroom", _STRIPE_NEWSROOM_LIST_URL, parse_stripe_newsroom),
        ("Stripe Developer Blog", _STRIPE_DEV_BLOG_URL, parse_stripe_dev_blog),
        ("Stripe Changelog", STRIPE_CHANGELOG_URL, parse_stripe_changelog),
    )
    for label, url, parser in sources:
        try:
            html = multi_rss.get_html(url)
            if not html:
                logger.warning("%s unavailable; continuing", label)
                continue
            entries = parser(html, known_links)
            out.extend(entries)
            logger.info("%s: %d entries", label, len(entries))
        except Exception as exc:
            logger.warning("%s failed: %s", label, exc)
    return out

# --------------------------------------------------------------------------- #
# Feed
# --------------------------------------------------------------------------- #
def generate_atom_feed(entries: list[dict]) -> FeedGenerator:
    fg = FeedGenerator()
    fg.id(f"{BLOG_URL}#{FEED_NAME}")
    fg.title(FEED_TITLE)
    fg.subtitle(FEED_SUBTITLE)
    setup_feed_links(fg, BLOG_URL, FEED_NAME)
    setup_feed_extensions(fg)
    fg.language("en")
    fg.author({"name": "various"})
    fg.updated(datetime.now(timezone.utc))
    fg.generator("trvny-feeds saas.py")

    # entries are ascending (oldest first); feedgen reverses on write.
    for e in entries:
        fe = fg.add_entry()
        fe.id(e["id"])
        fe.title(e["title"])
        fe.link(href=e["link"], rel="alternate")
        if e.get("content_html"):
            fe.content(e["content_html"], type="html")
        else:
            fe.description(e.get("description") or e["title"])
        if e.get("source"):
            fe.category(term=e["source"], label=e["source"])
        add_entry_media(
            fe,
            e.get("image"),
            width=e.get("image_width"),
            height=e.get("image_height"),
        )
        if e.get("date"):
            fe.published(e["date"])
            fe.updated(e["date"])
    logger.info("Generated Atom feed with %d entries", len(entries))
    return fg


def main(full: bool = False) -> bool:
    raw_cached = (
        []
        if full
        else deserialize_entries(
            load_cache(FEED_NAME).get("entries", []), date_field="date"
        )
    )
    cached = _active_cached_entries(raw_cached)
    retired_entries_removed = len(cached) != len(raw_cached)
    known_links = {e.get("link") for e in cached}

    new_entries = (
        collect_hcp()
        + collect_bitly(known_links)
        + collect_commoninja()
        + collect_native_feeds(known_links)
        + collect_stripe(known_links)
        + collect_coderabbit_newsroom(known_links)
        + collect_postman_app_release_notes(known_links)
        + collect_postman_press(known_links)
        + collect_exa_blog(known_links)
        + collect_xweather_blog()
        + collect_xweather_changelogs()
        + collect_dated_anchor_sources()
    )
    if not new_entries and not cached:
        if retired_entries_removed:
            logger.warning(
                "Retired cache rows removed, but no active entries are available; "
                "preserving the last good feed"
            )
            save_cache(FEED_NAME, [])
            return True
        logger.error("No entries from any source; preserving the last good feed")
        return False

    merged = merge_entries(new_entries, cached, id_field="id", date_field="date")
    merged = sort_posts_for_feed(merged, date_field="date")
    merged = allocate_fair_share(
        merged, MAX_ENTRIES, per_source_cap={"": PER_SOURCE_CAP}
    )

    enrich_entries(merged)

    save_cache(FEED_NAME, merged)
    save_atom_feed(generate_atom_feed(merged), FEED_NAME)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the combined SaaS-vendors Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
