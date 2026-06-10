"""Microsoft feed: combined Atom from Microsoft's native RSS feeds — the
Official Microsoft Blog, Microsoft Source, Microsoft Signal, and the Tech
Community blogs firehose."""

import argparse
import sys

from multi_rss import run

FEED_NAME = "microsoft"

SOURCES = [
    ("Official Microsoft Blog", "https://blogs.microsoft.com/feed/", 40),
    ("Microsoft Source", "https://news.microsoft.com/source/feed/", 40),
    ("Microsoft Signal", "https://news.microsoft.com/signal/feed", 40),
    ("Microsoft 365 Blog", "https://www.microsoft.com/en-us/microsoft-365/blog/feed/", 40),
    ("Tech Community",
     "https://techcommunity.microsoft.com/t5/s/gxcuf89792/rss/Community"
     "?interaction.style=blog&feeds.replies=false", 40),
]


def main(full=False):
    return run(
        feed_name=FEED_NAME,
        title="Microsoft",
        subtitle="Combined Microsoft feed: Official Microsoft Blog, Source, "
                 "Signal, the Microsoft 365 Blog, and the Tech Community blogs.",
        blog_url="https://blogs.microsoft.com/",
        author="Microsoft",
        sources=SOURCES,
        full=full,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the Microsoft Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    sys.exit(0 if main(full=parser.parse_args().full) else 1)
