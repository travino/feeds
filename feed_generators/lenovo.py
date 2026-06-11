"""Lenovo feed: combined Atom from Lenovo's native feeds across newsroom,
Polish channels, gaming, and the CDRT blog.

Sources:
  * Lenovo StoryHub (news.lenovo.com) — global newsroom, EN
  * lenovo24.pl — Polish partner news (native RSS at /rss.xml; items carry no
    dates, so they surface as dateless entries)
  * lenovogaming.pl — Polish Legion/gaming site, PL
  * Lenovo CDRT blog (blog.lenovocdrt.com) — commercial deployment readiness
    team, EN

The Legion Gaming Community forum (gaming.lenovo.com) is reCAPTCHA-gated and
returns empty bodies to automated clients, so it is deliberately not a source.
"""

import argparse
import sys

from multi_rss import run

FEED_NAME = "lenovo"

SOURCES = [
    ("StoryHub", "https://news.lenovo.com/feed/", 40),
    ("lenovo24.pl", "https://lenovo24.pl/rss.xml", 40),
    ("Lenovo Gaming PL", "https://lenovogaming.pl/feed/", 40),
    ("CDRT Blog", "https://blog.lenovocdrt.com/feed.xml", 40),
]


def main(full=False):
    return run(
        feed_name=FEED_NAME,
        title="Lenovo",
        subtitle="Combined Lenovo feed: StoryHub newsroom, lenovo24.pl, "
                 "Lenovo Gaming PL, and the CDRT blog.",
        blog_url="https://news.lenovo.com/",
        author="Lenovo",
        sources=SOURCES,
        full=full,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the Lenovo Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    sys.exit(0 if main(full=parser.parse_args().full) else 1)
