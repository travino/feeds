"""ESA feed: combined Atom from the European Space Agency's native RSS feeds —
the Newsroom and Corporate News, the per-activity feeds (Space News, Space
Science, Operations, Observing the Earth, Launchers, Navigation,
Telecommunications), the Week in Images, and the Webb/Hubble imagery feeds.

Notes on the source set (probed against esa.int):
  * The www.esa.int portal pages (Newsroom, Science_Exploration, Enabling_Support,
    …) are JS-rendered Magnolia CMS and expose no dates on article pages, but ESA
    publishes a matching ``/rssfeed/<Section_path>`` for most of them — those
    native feeds are used instead of scraping.
  * ``/rssfeed/Our_Activities`` is identical to ``Our_Activities/Space_News`` and
    ``/rssfeed/EOB`` is identical to ``Observing_the_Earth``, so only one of each
    pair is listed (cross-source dedupe would drop the rest anyway).
  * Science_Exploration / Enabling_Support / Applications have no top-level RSS;
    their content flows through the per-activity feeds above.
  * Press Releases (and the /pl language variant) have no RSS feed; the English
    Newsroom feed covers that ground.
  * esahubble.org/images shares no entries with the Webb or Hubble News feeds, so
    it is kept rather than skipped.
"""

import argparse
import sys

from multi_rss import run

FEED_NAME = "esa"

_ACT = "https://www.esa.int/rssfeed/Our_Activities"
SOURCES = [
    ("Newsroom", "https://www.esa.int/rssfeed/Newsroom", 30),
    ("Corporate News", "https://www.esa.int/rssfeed/About_Us/Corporate_news", 30),
    ("Space News", f"{_ACT}/Space_News", 30),
    ("Space Science", f"{_ACT}/Space_Science", 30),
    ("Operations", f"{_ACT}/Operations", 30),
    ("Observing the Earth", f"{_ACT}/Observing_the_Earth", 30),
    ("Launchers", f"{_ACT}/Launchers", 30),
    ("Navigation", f"{_ACT}/Navigation", 30),
    ("Telecommunications", f"{_ACT}/Telecommunications_Integrated_Applications", 30),
    ("Week in Images", "https://www.esa.int/rssfeed/About_Us/Week_in_images", 10),
    ("Webb News", "https://feeds.feedburner.com/esawebb/news/", 20),
    ("Webb Images", "https://feeds.feedburner.com/esawebb/images/", 30),
    ("Hubble News", "https://feeds.feedburner.com/hubble_news/", 20),
    ("Hubble Images", "https://esahubble.org/images/feed/", 30),
]


def main(full=False):
    return run(
        feed_name=FEED_NAME,
        title="ESA",
        subtitle="Combined European Space Agency feed: Newsroom, Corporate News, "
                 "the per-activity feeds (Space News, Space Science, Operations, "
                 "Observing the Earth, Launchers, Navigation, Telecommunications), "
                 "the Week in Images, and the Webb and Hubble imagery feeds.",
        blog_url="https://www.esa.int/",
        author="ESA",
        sources=SOURCES,
        full=full,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the ESA Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    sys.exit(0 if main(full=parser.parse_args().full) else 1)
