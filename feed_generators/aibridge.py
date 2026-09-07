"""AI-bridge feed: one combined Atom stream of AI labs and newsletters.

Native RSS sources: Thinking Machines, Ollama, Mistral, Interconnected
(Matt Webb), AI Clock (Substack), the Polish AI blogs Bielik, Promptowy and
Maistry, and Stability AI (news-updates, via the
Squarespace ?format=rss trick — see note below). On top of those it reuses
the existing scrapers for Perplexity's Framer sites (Blog/Changelog/Research
+ API docs changelog RSS) and The Batch / DeepLearning.AI (__NEXT_DATA__) —
same parsers, separate cache, so this feed stands alone even though the
sources overlap with feed_perplexity.xml and feed_thebatch.xml. Groq
(blog/newsroom/changelog + groq-changelog commits) is folded in the same way
via groq.scrape_all. MiniMax Research/Blog, MiniMax News and the PLLuM blog are
scraped from their HTML listings.

Stability AI: plain /news?format=rss and /news/rss.xml both 301-redirect to
the client-rendered /news-updates page, dropping the query string — but
appending the same ?format=rss straight onto /news-updates works (Squarespace
serves the collection's native RSS from there instead). /blog/rss.xml still
404s and isn't used.
"""

import argparse
import re
import sys
import time

from bs4 import BeautifulSoup
from groq import scrape_all as scrape_groq
from multi_rss import get_html, parse_date, run, scrape_feed
from perplexity import RSS_SOURCES as PERPLEXITY_RSS
from perplexity import scrape_framer_listings
from thebatch import scrape_blog as scrape_dlai_blog
from thebatch import scrape_thebatch
from utils import favicon_proxy, sanitize_xml, setup_logging, stable_fallback_date
from widocznosc import scrape_widocznosc_news

logger = setup_logging()
FEED_NAME = "aibridge"

# Slots in the written feed, per source. The "" key is the default.
PER_SOURCE_QUOTA = {
    "": 40,
    "CrewClaw": 12,
    "MiniMax": 30,
    "Perplexity Blog": 30,
    "Promptowy": 30,
}

ANSWER_AI_FEED = "https://www.answer.ai/index.xml"
ANSWER_AI_TOOLCALLING = "https://www.answer.ai/posts/2026-01-20-toolcalling.html"
ANSWER_AI_TOOLCALLING_DESCRIPTION = (
    "A security analysis of language models calling tools that were not explicitly "
    "provided, with demonstrations across several major AI providers."
)

SOURCES = [
    ("Thinking Machines", "https://thinkingmachines.ai/blog/index.xml", 40),
    ("Ollama", "https://ollama.com/blog/rss.xml", 40),
    ("Mistral", "https://mistral.ai/rss.xml", 40),
    ("Interconnected", "https://interconnected.org/home/feed", 40),
    ("AI Clock", "https://aiclock.substack.com/feed", 40),
    ("Stability AI", "https://stability.ai/news-updates?format=rss", 30),
    ("Bielik", "https://bielik.ai/feed/", 40),
    ("Promptowy", "https://promptowy.com/feed/", 40),
    ("Maistry", "https://maistry.pl/rss/", 40),
    ("Karpathy", "https://karpathy.bearblog.dev/feed/", 40),
    ("Karpathy (blog)", "https://karpathy.github.io/feed.xml", 40),
    ("Transformer", "https://www.transformernews.ai/feed", 40),
] + list(PERPLEXITY_RSS)


# Answer.AI shipped this item without a usable per-entry date and with build
# output as its summary. Without a fixed date feedgen assigns the generation
# time on every run, so readers repeatedly surface the same stable entry.
def repair_answer_ai_entry(entry):
    repaired = dict(entry)
    if repaired.get("link") == ANSWER_AI_TOOLCALLING:
        repaired["date"] = parse_date("2026-02-18")
        repaired["description"] = ANSWER_AI_TOOLCALLING_DESCRIPTION
    return repaired


def scrape_answer_ai(known_links):
    entries = scrape_feed("Answer.AI", ANSWER_AI_FEED, known_links, cap=40)
    return [repair_answer_ai_entry(entry) for entry in entries]


MINIMAX_BLOG_URL = "https://www.minimax.io/blog"
MINIMAX_NEWS_URL = "https://www.minimax.io/news"
MINIMAX_BASE_URL = "https://www.minimax.io"
MINIMAX_DETAIL_LIMIT = 30
MINIMAX_DETAIL_DELAY = 0.3
_MINIMAX_DATE_RE = re.compile(
    r"(20\d{2}[./-]\d{1,2}[./-]\d{1,2}|"
    r"\d{1,2}[./-]\d{1,2}[./-]20\d{2}|"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\.?\s+\d{1,2}(?:st|nd|rd|th)?\s*,?\s*20\d{2})",
    re.IGNORECASE,
)
_MINIMAX_LINK_RE = re.compile(
    r"(?:https?:)?//www\.minimax\.io/(?:news|blog)/[A-Za-z0-9][A-Za-z0-9_-]*"
    r"|(?<![A-Za-z0-9:/])/(?:news|blog)/[A-Za-z0-9][A-Za-z0-9_-]*"
    r"(?![/A-Za-z0-9_-])"
)
_MINIMAX_RESERVED_SLUGS = {"page", "tag", "tags", "category", "search"}


def _minimax_title_from_slug(link):
    slug = link.rstrip("/").split("/")[-1]
    title = re.sub(r"[-_]+", " ", slug).strip()
    return title[:1].upper() + title[1:]


def _normalize_minimax_link(href, section="news"):
    href = (href or "").split("?", 1)[0].split("#", 1)[0].rstrip("/")
    prefix = f"/{section}/"
    if href.startswith(f"//www.minimax.io{prefix}"):
        href = "https:" + href
    if re.match(rf"^https?://www\.minimax\.io{re.escape(prefix)}", href):
        href = MINIMAX_BASE_URL + href.split("www.minimax.io", 1)[1]
    elif href.startswith(prefix):
        href = MINIMAX_BASE_URL + href
    else:
        return None

    slug = href.rsplit("/", 1)[-1].lower()
    if not slug or slug in _MINIMAX_RESERVED_SLUGS:
        return None
    return href


def _minimax_date(soup, text):
    for attrs in (
        {"property": "article:published_time"},
        {"name": "date"},
        {"name": "publish_date"},
    ):
        meta = soup.find("meta", attrs=attrs)
        if meta and meta.get("content"):
            parsed = parse_date(meta["content"])
            if parsed:
                return parsed

    time_tag = soup.find("time", attrs={"datetime": True})
    if time_tag:
        parsed = parse_date(time_tag.get("datetime"))
        if parsed:
            return parsed

    for script in soup.find_all("script"):
        script_text = script.string or script.get_text(" ", strip=True)
        match = re.search(r'"datePublished"\s*:\s*"([^"]+)"', script_text or "")
        if match:
            parsed = parse_date(match.group(1))
            if parsed:
                return parsed

    match = _MINIMAX_DATE_RE.search(text)
    return parse_date(match.group(0)) if match else None


def _minimax_entry(link, html, *, full_page=False, fallback_date=True):
    soup = BeautifulSoup(html, "html.parser")
    scope = soup
    if full_page:
        scope = soup.find("article") or soup.find("main") or soup.body or soup

    heading_tags = ["h1"] if full_page else ["h1", "h2", "h3", "h4"]
    heading = scope.find(heading_tags)
    title = heading.get_text(" ", strip=True) if heading else ""
    if not title and full_page:
        og_title = soup.find("meta", attrs={"property": "og:title"})
        if og_title and og_title.get("content"):
            title = og_title["content"]
    title = re.sub(r"\s+", " ", title or _minimax_title_from_slug(link)).strip()

    text = re.sub(r"\s+", " ", scope.get_text(" ", strip=True)).strip()
    date = _minimax_date(soup, text)

    description = ""
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        description = meta["content"]
    if not description:
        paragraph = scope.find("p")
        if paragraph:
            description = paragraph.get_text(" ", strip=True)
    if not description:
        description = text
        date_match = _MINIMAX_DATE_RE.search(description)
        if date_match:
            description = description.replace(date_match.group(0), " ", 1)
        if title and title in description:
            description = description.replace(title, " ", 1)
        description = re.sub(
            r"\bRead More\b", " ", description, flags=re.IGNORECASE
        )
    description = re.sub(r"\s+", " ", description).strip()

    return {
        "title": sanitize_xml(title[:200]),
        "link": link,
        "date": date or (stable_fallback_date(link) if fallback_date else None),
        "description": sanitize_xml((description or title)[:500]),
        "source": "MiniMax",
    }


def _scrape_minimax_listing(known_links, listing_url, section):
    html = get_html(listing_url)
    if not html:
        return []

    known = {link.rstrip("/") for link in known_links}
    soup = BeautifulSoup(html, "html.parser")
    candidates = {}
    for anchor in soup.select("a[href]"):
        link = _normalize_minimax_link(anchor.get("href", ""), section)
        if link:
            candidates.setdefault(link, anchor)

    # MiniMax has served listings both with cards in HTML and with paths only
    # in its hydrated payload. Only scan the payload fallback when cards are
    # absent, and keep candidates scoped to the requested section.
    hydration_only = not candidates
    if hydration_only:
        scan_html = html.replace("\\/", "/").replace("\\u002F", "/")
        for match in _MINIMAX_LINK_RE.finditer(scan_html):
            link = _normalize_minimax_link(match.group(0), section)
            if link:
                candidates.setdefault(link, None)

    if not candidates:
        logger.warning(
            "  [MiniMax] no %s entries matched; layout or rendering may have changed",
            section,
        )
        return []

    pending = [(link, anchor) for link, anchor in candidates.items() if link not in known]
    entries = []
    detail_fetches = 0

    def fetch_detail(link):
        nonlocal detail_fetches
        if detail_fetches >= MINIMAX_DETAIL_LIMIT:
            return None
        if detail_fetches:
            time.sleep(MINIMAX_DETAIL_DELAY)
        detail_fetches += 1
        return get_html(link)

    for link, anchor in pending:
        if anchor is not None:
            entry = _minimax_entry(link, str(anchor), fallback_date=False)
            if entry["date"] is None:
                article_html = fetch_detail(link)
                if article_html:
                    entry = _minimax_entry(link, article_html, full_page=True)
                else:
                    entry["date"] = stable_fallback_date(link)
            entries.append(entry)
            if len(entries) >= 40:
                break
            continue

        article_html = fetch_detail(link)
        if not article_html:
            if detail_fetches >= MINIMAX_DETAIL_LIMIT:
                break
            continue
        entry = _minimax_entry(
            link, article_html, full_page=True, fallback_date=False
        )
        # Hydration payloads may contain utility paths. Real MiniMax articles
        # carry a publication date, so dateless pages are ignored here.
        if entry["date"] is not None:
            entries.append(entry)
        if len(entries) >= 40:
            break

    if pending and not entries:
        logger.warning("  [MiniMax] %s paths found but no article pages parsed", section)
        return []

    entries.sort(key=lambda entry: entry["date"], reverse=True)
    return entries[:40]


def scrape_minimax_news(known_links):
    return _scrape_minimax_listing(known_links, MINIMAX_NEWS_URL, "news")


def scrape_minimax_blog(known_links):
    return _scrape_minimax_listing(known_links, MINIMAX_BLOG_URL, "blog")


# CrewClaw blog has no native feed: a static grid of /blog/<slug> cards whose
# text is "<Category> <Title> YYYY-MM-DD · N min read <Title again>...".
CREWCLAW_URL = "https://crewclaw.com/blog"
_CC_DATE_RE = re.compile(r"(20\d\d-\d\d-\d\d)")


def scrape_crewclaw(known_links):
    html = get_html(CREWCLAW_URL)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    seen, entries = set(), []
    for a in soup.select("a[href*='/blog/']"):
        href = a.get("href", "").split("?")[0].split("#")[0]
        # real posts are /blog/<slug>; /blog and /blog/<category> hubs are skipped
        if len([p for p in href.split("/blog/")[-1].split("/") if p]) != 1:
            continue
        text = a.get_text(" ", strip=True)
        m = _CC_DATE_RE.search(text)
        if not m:
            continue
        link = href if href.startswith("http") else "https://crewclaw.com" + href
        if link in seen or link in known_links:
            continue
        # Title is the prose after "min read"; fall back to the card's heading.
        title = ""
        if "min read" in text:
            title = text.split("min read", 1)[1].strip()
        if len(title) < 12:
            h = a.find(["h2", "h3"])
            title = h.get_text(" ", strip=True) if h else title
        title = re.sub(r"\s+", " ", title).strip()
        if len(title) < 12:
            continue
        seen.add(link)
        entries.append(
            {
                "title": sanitize_xml(title[:200]),
                "link": link,
                "date": parse_date(m.group(1)),
                "description": sanitize_xml(title[:200]),
                "source": "CrewClaw",
            }
        )
    # CrewClaw lists a large SEO archive; keep only the newest so it doesn't
    # swamp the combined feed (undated cards sink to the bottom).
    entries.sort(key=lambda e: (e["date"] is not None, e["date"] or ""), reverse=True)
    return entries[:40]


PLLUM_BLOG_URL = "https://pllum.org.pl/blog"


def scrape_pllum_blog(known_links):
    html = get_html(PLLUM_BLOG_URL)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    seen, entries = set(), []
    for article in soup.select("article"):
        anchor = article.select_one("a[href^='/blog/posts/']")
        if not anchor:
            continue
        href = anchor.get("href", "").split("?", 1)[0].split("#", 1)[0]
        link = href if href.startswith("http") else "https://pllum.org.pl" + href
        if link in seen or link in known_links:
            continue

        heading = article.find(["h2", "h3"])
        title = (
            heading.get_text(" ", strip=True)
            if heading
            else anchor.get("aria-label", "")
        )
        time_tag = article.find("time", attrs={"datetime": True})
        date = parse_date(time_tag.get("datetime")) if time_tag else None
        if not title or date is None:
            continue

        description_node = article.find(
            "div", class_=lambda value: value and "line-clamp-3" in value
        )
        description = (
            description_node.get_text(" ", strip=True) if description_node else title
        )
        seen.add(link)
        entries.append(
            {
                "title": sanitize_xml(title[:200]),
                "link": link,
                "date": date,
                "description": sanitize_xml(description[:500]),
                "source": "PLLuM",
            }
        )

    entries.sort(key=lambda entry: entry["date"], reverse=True)
    return entries[:40]


def main(full=False):
    return run(
        feed_name=FEED_NAME,
        title="AI-bridge",
        subtitle="Combined AI feed: Thinking Machines, Ollama, Mistral, "
        "Interconnected, AI Clock, Stability AI, Bielik, Promptowy, Maistry, "
        "Karpathy (bearblog + old blog), Transformer, MiniMax News/Blog, PLLuM, "
        "Perplexity (blog/changelog/research/API changelog), "
        "The Batch / DeepLearning.AI, and Groq (blog/newsroom/changelog).",
        blog_url="https://thinkingmachines.ai/blog/",
        icon=favicon_proxy("thinkingmachines.ai"),
        author="various",
        sources=SOURCES,
        extra_scrapers=[
            scrape_answer_ai,
            scrape_minimax_news,
            scrape_minimax_blog,
            scrape_framer_listings,
            scrape_thebatch,
            scrape_dlai_blog,
            scrape_groq,
            scrape_crewclaw,
            scrape_pllum_blog,
            scrape_widocznosc_news,
        ],
        max_entries=400,
        # Volume here is wildly uneven: CrewClaw is an SEO archive that landed
        # 108 posts in a single month and had taken 214 of the feed's slots,
        # while Interconnected publishes a handful. Quotas keep the content
        # farms from burying the labs.
        per_source_cap=PER_SOURCE_QUOTA,
        # Glama (blog, MCP Servers, release notes) all moved to the skillsllm
        # feed; evict any leftover Glama-sourced cache entries so they don't
        # linger here until they age past the cap.
        cache_filter=lambda e: not str(e.get("source", "")).startswith("Glama"),
        cache_transform=repair_answer_ai_entry,
        full=full,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the AI-bridge Atom feed")
    parser.add_argument(
        "--full", action="store_true", help="Ignore cache and rebuild from scratch"
    )
    sys.exit(0 if main(full=parser.parse_args().full) else 1)
