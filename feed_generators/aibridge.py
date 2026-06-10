"""AI-bridge feed: one combined Atom stream of AI labs and newsletters.

Native RSS sources: Thinking Machines, Ollama, Mistral, Interconnected
(Matt Webb), and AI Clock (Substack). On top of those it reuses the existing
scrapers for Perplexity's Framer sites (Blog/Changelog/Research + API docs
changelog RSS) and The Batch / DeepLearning.AI (__NEXT_DATA__) — same parsers,
separate cache, so this feed stands alone even though the sources overlap with
feed_perplexity.xml and feed_thebatch.xml.
"""

import argparse
import sys

from multi_rss import run
from perplexity import RSS_SOURCES as PERPLEXITY_RSS
from perplexity import scrape_framer_listings
from thebatch import scrape_blog as scrape_dlai_blog
from thebatch import scrape_thebatch

FEED_NAME = "aibridge"

SOURCES = [
    ("Thinking Machines", "https://thinkingmachines.ai/blog/index.xml", 40),
    ("Ollama", "https://ollama.com/blog/rss.xml", 40),
    ("Mistral", "https://mistral.ai/rss.xml", 40),
    ("Interconnected", "https://interconnected.org/home/feed", 40),
    ("AI Clock", "https://aiclock.substack.com/feed", 40),
] + list(PERPLEXITY_RSS)


def main(full=False):
    return run(
        feed_name=FEED_NAME,
        title="AI-bridge",
        subtitle="Combined AI feed: Thinking Machines, Ollama, Mistral, "
                 "Interconnected, AI Clock, Perplexity (blog/changelog/research/"
                 "API changelog), and The Batch / DeepLearning.AI.",
        blog_url="https://thinkingmachines.ai/blog/",
        author="various",
        sources=SOURCES,
        extra_scrapers=[scrape_framer_listings, scrape_thebatch, scrape_dlai_blog],
        max_entries=300,
        full=full,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the AI-bridge Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    sys.exit(0 if main(full=parser.parse_args().full) else 1)
