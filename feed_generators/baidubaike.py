"""Baidu Baike daily hot-search terms feed.

Baidu Baike does not expose a native RSS/Atom feed for its homepage. The mobile
homepage does expose a dated ``热搜词条`` section, so this generator turns those
currently trending encyclopedia entries into a rolling Feedseek feed.
"""

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from bs4 import BeautifulSoup
from multi_rss import get_html, run
from utils import sanitize_xml, setup_logging

logger = setup_logging()

FEED_NAME = "baidubaike"
BLOG_URL = "https://baike.baidu.com/"
SOURCE_URL = "https://wapbaike.baidu.com/"

_DATE_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}$")
_CHINA_TZ = timezone(timedelta(hours=8))
_SECTION_STOPS = ("V百科", "百科博物馆计划", "秒懂百科", "反馈")
_MAX_DAILY_TERMS = 6


def _page_strings(html):
    """Return normalized visible-ish strings while ignoring script/style noise."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return [
        re.sub(r"\s+", " ", text).strip()
        for text in soup.stripped_strings
        if text.strip()
    ]


def _hot_section(strings):
    """Find the dated hot-term section, ignoring mentions in the intro copy."""
    for index, text in enumerate(strings):
        if text != "热搜词条":
            continue
        for date_index in range(index + 1, min(index + 12, len(strings))):
            if _DATE_RE.fullmatch(strings[date_index]):
                return date_index, strings[date_index]
            if strings[date_index] == "热搜词条":
                break
    return None, None


def extract_hot_terms(html):
    """Extract the dated Baidu Baike hot terms as Feedseek entry dictionaries."""
    strings = _page_strings(html)
    date_index, date_text = _hot_section(strings)
    if date_index is None:
        logger.warning("Could not find the dated 热搜词条 section")
        return []

    published = datetime.strptime(date_text, "%Y.%m.%d").replace(tzinfo=_CHINA_TZ)
    iso_date = published.date().isoformat()
    entries = []
    seen = set()

    for text in strings[date_index + 1 :]:
        if text == "更多" or any(text.startswith(stop) for stop in _SECTION_STOPS):
            break
        if text in {"热搜词条", date_text} or _DATE_RE.fullmatch(text):
            continue

        title = sanitize_xml(text)
        if not title or title in seen:
            continue
        seen.add(title)

        rank = len(entries) + 1
        link = f"https://baike.baidu.com/item/{quote(title, safe='')}"
        entries.append(
            {
                "title": title,
                "link": link,
                "date": published,
                "description": f"百度百科热搜词条 · {iso_date} · 排名 #{rank}",
                "source": "百度百科热搜词条",
            }
        )
        if len(entries) >= _MAX_DAILY_TERMS:
            break

    return entries


def scrape_baidu_baike_hot_terms(known_links):
    """Fetch today's Baidu Baike hot terms and return only previously unseen ones."""
    html = get_html(SOURCE_URL)
    if not html:
        return []
    return [entry for entry in extract_hot_terms(html) if entry["link"] not in known_links]


def main(full=False):
    return run(
        feed_name=FEED_NAME,
        title="Baidu Baike 热搜词条",
        subtitle="Daily trending encyclopedia entries from Baidu Baike (百度百科).",
        blog_url=BLOG_URL,
        author="Baidu Baike",
        extra_scrapers=[scrape_baidu_baike_hot_terms],
        max_entries=200,
        language="zh-CN",
        full=full,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the Baidu Baike hot terms feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    sys.exit(0 if main(full=parser.parse_args().full) else 1)
