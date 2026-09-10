#!/usr/bin/env python3
"""Probe every source docs/sources.md lists and report the ones that are gone.

The document is derived from the generators now, so it is always an accurate
list of what they *intend* to read. It says nothing about whether those URLs
still answer - and a source that started 404ing does not fail anything: the
generator logs a warning nobody reads, the feed keeps publishing from its other
sources, and the dead one just quietly stops contributing. Combined feeds hide
this best, which is exactly where most sources live.

    python tools/check_sources.py                 # every source, grouped by feed
    python tools/check_sources.py --broken        # only what needs fixing
    python tools/check_sources.py --feed lemmy    # one feed

Exits 1 when something is broken, so it works as a manual gate.

Deliberately not part of validate_feeds.py: it needs the network and talks to
507+ third-party hosts, so wiring it into the scheduled run would let someone
else's outage fail a build that produced perfectly good feeds.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "feed_generators"))

from docs_sources import collect_sources, load_yaml_feeds  # noqa: E402

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    )
}
TIMEOUT = 20
WORKERS = 12


def _impersonated_status(url: str) -> int | None:
    """Status from the same client the generators use for hostile origins."""
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        return None
    try:
        return curl_requests.get(url, impersonate="chrome", timeout=TIMEOUT).status_code
    except Exception:
        return None


def probe(url: str) -> tuple[bool, str]:
    """Return (ok, note) for one source URL.

    A HEAD would be cheaper but too many of these hosts answer it wrongly - 405
    from CDNs, 404 from WAFs that only route GET - so this issues a streaming
    GET and reads nothing.

    Anything other than 200 is retried through curl_cffi before being called
    broken, because that is what the generators use: euronews answers 406 and
    every Meta changelog 400 to a plain requests fingerprint while serving the
    same URL fine to a browser one. Reporting those as dead would be crying
    wolf about twelve working sources.
    """
    try:
        response = requests.get(
            url, headers=HEADERS, timeout=TIMEOUT, stream=True, allow_redirects=True
        )
        response.close()
        status = response.status_code
    except requests.RequestException as exc:
        status, note = None, type(exc).__name__

    if status == 200:
        return True, "200"

    retried = _impersonated_status(url)
    if retried == 200:
        return True, "200 (tylko przez curl_cffi)"
    if retried in (401, 403, 429) or status in (401, 403, 429):
        return True, f"HTTP {retried or status} (blokada bota, generator to obchodzi)"
    if status is None and retried is None:
        return False, note
    return False, f"HTTP {retried or status}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--broken", action="store_true", help="list only what is broken")
    parser.add_argument("--feed", help="check a single feed by registry name")
    args = parser.parse_args()

    registry = load_yaml_feeds()
    if args.feed:
        if args.feed not in registry:
            print(f"unknown feed: {args.feed}", file=sys.stderr)
            return 1
        registry = {args.feed: registry[args.feed]}

    by_feed = {name: collect_sources(name, cfg)[0] for name, cfg in sorted(registry.items())}

    # One probe per distinct URL: feeds share sources more often than you would
    # think, and a Google News query appears under half a dozen names.
    unique = sorted({url for pairs in by_feed.values() for _, url in pairs})
    print(f"sprawdzam {len(unique)} unikalnych zrodel z {len(by_feed)} feedow ...\n")
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        verdicts = dict(zip(unique, pool.map(probe, unique)))

    tally = Counter()
    broken_total = 0
    for feed, pairs in by_feed.items():
        broken = [(label, url, verdicts[url][1]) for label, url in pairs if not verdicts[url][0]]
        tally["zrodla"] += len(pairs)
        tally["martwe"] += len(broken)
        broken_total += len(broken)
        if broken:
            print(f"{feed} ({len(broken)} z {len(pairs)}):")
            for label, url, note in broken:
                print(f"    {note:34s} {label} - {url}")
        elif not args.broken:
            print(f"{feed}: wszystkie {len(pairs)} zrodel odpowiadaja")

    print(f"\n{tally['martwe']} z {tally['zrodla']} zrodel nie odpowiada")
    return 1 if broken_total else 0


if __name__ == "__main__":
    sys.exit(main())
