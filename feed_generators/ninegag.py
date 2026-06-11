"""9GAG feed: scraped Atom feed of the 9GAG Hot page.

9GAG has no native feed; the Hot page ships its post list in a
``window._config = JSON.parse("...")`` blob (``data.posts``), so one
curl_cffi fetch yields ~10 posts with id, title, type, timestamps, and image
renditions. NSFW posts are included and tagged [NSFW]; each entry embeds the post image
(``images.image700``) in its description. History accumulates run over run,
so the feed grows past the per-fetch window.
"""

import argparse
import datetime
import json
import re
import sys

import pytz

from multi_rss import get_html, run
from utils import sanitize_xml, setup_logging

logger = setup_logging()

FEED_NAME = "9gag"
HOT_URL = "https://9gag.com/"

_CONFIG_RE = re.compile(r'window\._config\s*=\s*JSON\.parse\((".*?")\);', re.S)


def scrape_hot(known_links):
    label = "9GAG Hot"
    entries = []
    html = get_html(HOT_URL)
    if html is None:
        return entries

    m = _CONFIG_RE.search(html)
    if not m:
        logger.warning(f"  [{label}] window._config not found — page structure may have changed")
        return entries
    try:
        cfg = json.loads(json.loads(m.group(1)))
        posts = cfg.get("data", {}).get("posts", [])
    except Exception as e:
        logger.warning(f"  [{label}] could not parse _config JSON: {e}")
        return entries
    if not posts:
        logger.warning(f"  [{label}] no posts in _config — page structure may have changed")
        return entries

    for post in posts:
        try:
            link = (post.get("url") or "").replace("http://", "https://")
            if not link or link in known_links:
                continue
            title = sanitize_xml(post.get("title") or post.get("id") or "9GAG post")
            if post.get("nsfw"):
                title = f"[NSFW] {title}"
            ts = post.get("creationTs")
            date_obj = (
                datetime.datetime.fromtimestamp(int(ts), tz=pytz.UTC) if ts else None
            )
            img = (post.get("images") or {}).get("image700") or {}
            img_src = img.get("url")
            if img_src:
                desc = sanitize_xml(
                    f'<p><a href="{link}"><img src="{img_src}" alt="{title}" /></a></p>'
                )
            else:
                desc = title
            entries.append({
                "title": title,
                "link": link,
                "date": date_obj,
                "description": desc,
                "source": label,
            })
            logger.info(f"  [{label}] {title}")
        except Exception as e:
            logger.warning(f"  [{label}] skipping malformed post: {e}")
    return entries


def main(full=False):
    return run(
        feed_name=FEED_NAME,
        title="9GAG",
        subtitle="Hot posts from 9gag.com (no native feed; parsed from the page's "
                 "window._config JSON). NSFW posts are tagged [NSFW].",
        blog_url=HOT_URL,
        author="9GAG",
        extra_scrapers=[scrape_hot],
        max_entries=150,
        full=full,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the 9GAG Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    sys.exit(0 if main(full=parser.parse_args().full) else 1)
