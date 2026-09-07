"""Scraper for the widocznosc.ai GenAI news listing."""

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from multi_rss import get_html, parse_date
from utils import sanitize_xml

WIDOCZNOSC_NEWS_URL = "https://widocznosc.ai/news/"
WIDOCZNOSC_BASE_URL = "https://widocznosc.ai"

_POLISH_MONTHS = {
    "stycznia": 1,
    "lutego": 2,
    "marca": 3,
    "kwietnia": 4,
    "maja": 5,
    "czerwca": 6,
    "lipca": 7,
    "sierpnia": 8,
    "września": 9,
    "wrzesnia": 9,
    "października": 10,
    "pazdziernika": 10,
    "listopada": 11,
    "grudnia": 12,
}
_POLISH_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+([a-ząćęłńóśźż]+)\s+(20\d{2})\b", re.IGNORECASE
)


def _parse_polish_date(text):
    match = _POLISH_DATE_RE.search(text or "")
    if not match:
        return None
    day, month_name, year = match.groups()
    month = _POLISH_MONTHS.get(month_name.lower())
    if month is None:
        return None
    return parse_date(f"{year}-{month:02d}-{int(day):02d}")


def _normalize_news_link(href):
    href = (href or "").split("#", 1)[0].split("?", 1)[0]
    link = urljoin(WIDOCZNOSC_BASE_URL, href)
    parsed = urlparse(link)
    if parsed.netloc not in {"widocznosc.ai", "www.widocznosc.ai"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2 or parts[0] != "news":
        return None
    return f"{WIDOCZNOSC_BASE_URL}/news/{parts[1]}/"


def scrape_widocznosc_news(known_links):
    html = get_html(WIDOCZNOSC_NEWS_URL)
    if not html:
        return []

    known = {str(link).rstrip("/") for link in known_links}
    soup = BeautifulSoup(html, "html.parser")
    seen, entries = set(), []

    for anchor in soup.select("a[href*='/news/']"):
        link = _normalize_news_link(anchor.get("href", ""))
        if not link or link.rstrip("/") in known or link in seen:
            continue

        text = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        date = _parse_polish_date(text)
        if date is None:
            continue

        heading = anchor.find(["h2", "h3", "h4"])
        title = heading.get_text(" ", strip=True) if heading else anchor.get("aria-label", "")
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue

        paragraph = anchor.find("p")
        description = paragraph.get_text(" ", strip=True) if paragraph else title
        description = re.sub(r"\s+", " ", description).strip()

        seen.add(link)
        entries.append(
            {
                "title": sanitize_xml(title[:200]),
                "link": link,
                "date": date,
                "description": sanitize_xml((description or title)[:500]),
                "source": "widocznosc.ai",
            }
        )

    entries.sort(key=lambda entry: entry["date"], reverse=True)
    return entries[:40]
