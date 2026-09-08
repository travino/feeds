#!/usr/bin/env python3
"""Discover RSS/Atom/JSON feed candidates for a site.

Manual scouting tool, not part of the hourly generator pipeline. Use this
when adding a new source to feeds.yaml, to find native feed URLs before
reaching for a scraper.

Usage:
    uv run feed_generators/discover.py <url>

Tries the local feedsearch-crawler library first and falls back to the hosted
feedsearch.dev API. It also checks the site's llms.txt, when present, and probes
a bounded set of feed-, changelog-, blog-, and news-oriented links for extra
native feeds. llms.txt failures never block ordinary discovery.
"""

import sys

import requests

from llms_discovery import discover_llms_candidates

MAX_LLMS_PROBES = 6


def discover_local(url: str):
    try:
        from feedsearch_crawler import search_with_info
    except ImportError:
        # Optional dependency (`uv sync --group discover`) — it pulls in uvloop,
        # which does not build on Windows. Absent it, main() falls through to
        # the hosted API, which is what the module docstring already promises.
        print("feedsearch-crawler not installed; skipping local crawl", file=sys.stderr)
        return None

    result = search_with_info(url, include_stats=False)
    if result.root_error:
        print(f"local crawl error: {result.root_error.message}", file=sys.stderr)
        return None
    return list(result.feeds)


def discover_hosted(url: str):
    resp = requests.get(
        "https://feedsearch.dev/api/v1/search",
        params={"url": url, "info": "true"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def discover_target(url: str):
    feeds = discover_local(url)
    source = "local"
    if not feeds:
        feeds = discover_hosted(url)
        source = "hosted"
    return list(feeds or []), source


def feed_value(feed, name: str, default=""):
    if isinstance(feed, dict):
        return feed.get(name, default)
    return getattr(feed, name, default)


def merge_feeds(found: dict[str, tuple[object, str]], feeds, source: str) -> None:
    for feed in feeds:
        url = str(feed_value(feed, "url")).strip()
        if url and url not in found:
            found[url] = (feed, source)


def llms_candidates(url: str):
    try:
        return discover_llms_candidates(url, limit=MAX_LLMS_PROBES)
    except (requests.RequestException, UnicodeError, ValueError) as exc:
        print(f"llms.txt discovery skipped: {exc}", file=sys.stderr)
        return []


def main():
    if len(sys.argv) != 2:
        print("usage: discover.py <url>", file=sys.stderr)
        sys.exit(1)
    url = sys.argv[1]

    feeds, source = discover_target(url)
    found: dict[str, tuple[object, str]] = {}
    merge_feeds(found, feeds, source)

    candidates = llms_candidates(url)
    for candidate in candidates:
        print(
            f"llms.txt candidate: score={candidate.score} {candidate.title} -> {candidate.url}",
            file=sys.stderr,
        )
        try:
            candidate_feeds, candidate_source = discover_target(candidate.url)
        except requests.RequestException as exc:
            print(f"candidate probe failed: {candidate.url}: {exc}", file=sys.stderr)
            continue
        merge_feeds(found, candidate_feeds, f"llms-{candidate_source}")

    if not found:
        if candidates:
            print("no native feeds found; llms.txt candidates above may be scraper sources", file=sys.stderr)
        else:
            print("no feeds found", file=sys.stderr)
        sys.exit(1)

    sources = ", ".join(dict.fromkeys(item[1] for item in found.values()))
    print(f"# sources: {sources}", file=sys.stderr)
    for feed, _ in found.values():
        print(
            f"{feed_value(feed, 'url')}\t{feed_value(feed, 'version')}\t"
            f"score={feed_value(feed, 'score')}\t{feed_value(feed, 'title')}"
        )


if __name__ == "__main__":
    main()
