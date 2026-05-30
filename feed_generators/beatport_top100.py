"""Beatport Top 100 feed generator.

Beatport's Top 100 page (https://www.beatport.com/top-100) is a Next.js app
with no native RSS/Atom feed, but the full 100-track chart is embedded in the
page's ``__NEXT_DATA__`` JSON blob — so a plain ``requests`` fetch is enough
(no Selenium needed).

The chart is a *ranking* that changes over time, which doesn't map cleanly onto
a date-ordered feed. So instead of re-emitting the same 100 positions every run,
this generator treats the feed as **"tracks as they enter the Top 100"**: each
track becomes one Atom entry keyed by its Beatport URL, dated by the moment it
is first observed on the chart, with the rank it debuted at preserved in the
summary. New chart entrants therefore surface as fresh feed items, while the
JSON cache (``cache/beatport_top100_posts.json``) accumulates history across
hourly runs and dedupes by track URL.

Writes an **Atom** feed to ``feeds/feed_beatport_top100.xml``.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta

import pytz
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

from utils import (
    deserialize_entries,
    get_feeds_dir,
    load_cache,
    merge_entries,
    sanitize_xml,
    save_cache,
    setup_feed_links,
    setup_logging,
    sort_posts_for_feed,
)

logger = setup_logging()

FEED_NAME = "beatport_top100"
BLOG_URL = "https://www.beatport.com/top-100"
TRACK_URL_TMPL = "https://www.beatport.com/track/{slug}/{id}"

# The chart accumulates over time; cap the committed XML at a sensible size.
MAX_ENTRIES = 200


def fetch_chart(retries=3, backoff=2.0):
    """Fetch the Top 100 HTML, returning the body or None.

    Beatport sits behind Cloudflare, which fingerprints the TLS handshake (JA3)
    and returns HTTP 403 to plain ``requests``/urllib3 even with browser-like
    headers. ``curl_cffi`` impersonates a real Chrome TLS fingerprint and gets
    through; we fall back to the shared ``fetch_page`` only if it isn't
    installed (which will likely 403, but keeps the import non-fatal).
    """
    try:
        from curl_cffi import requests as creq
    except ImportError:
        logger.warning("curl_cffi not installed; falling back to plain requests (likely 403)")
        from utils import fetch_page

        try:
            return fetch_page(BLOG_URL)
        except Exception as e:
            logger.error(f"Fallback fetch failed: {e}")
            return None

    for attempt in range(1, retries + 1):
        try:
            resp = creq.get(BLOG_URL, impersonate="chrome", timeout=30)
            if resp.status_code == 200 and "__NEXT_DATA__" in resp.text:
                logger.info(f"Fetched chart ({len(resp.text)} bytes)")
                return resp.text
            logger.warning(f"Unexpected response (status {resp.status_code}) on attempt {attempt}")
        except Exception as e:
            logger.warning(f"Fetch failed (attempt {attempt}/{retries}): {e}")
        if attempt < retries:
            time.sleep(backoff * attempt)
    return None


def extract_tracks(html):
    """Pull the 100-track results array out of the page's __NEXT_DATA__ blob."""
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag is None or not tag.string:
        logger.error("__NEXT_DATA__ script not found — page layout may have changed")
        return []
    try:
        data = json.loads(tag.string)
        queries = data["props"]["pageProps"]["dehydratedState"]["queries"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error(f"Could not parse __NEXT_DATA__ structure: {e}")
        return []

    for q in queries:
        results = (q.get("state", {}).get("data", {}) or {}).get("results")
        if isinstance(results, list) and results and isinstance(results[0], dict) and "mix_name" in results[0]:
            return results

    logger.error("Could not locate the track results array in __NEXT_DATA__")
    return []


def build_entries(tracks, now):
    """Convert the raw chart tracks into feed-entry dicts.

    *now* is the first-seen timestamp applied to tracks seen in this run; the
    cache preserves the original timestamp for tracks already known, so the
    rank stored here is effectively each track's debut rank. Within a single
    run every track shares the same observation time, so we subtract the rank
    (in seconds) to keep the chart in order: higher-ranked tracks get the
    newer timestamp and therefore sort first in the feed.
    """
    entries = []
    seen_links = set()

    for rank, track in enumerate(tracks, start=1):
        try:
            entry_date = now - timedelta(seconds=rank)
            track_id = track.get("id")
            name = (track.get("name") or "").strip()
            if not track_id or not name:
                continue

            slug = track.get("slug") or "track"
            link = TRACK_URL_TMPL.format(slug=slug, id=track_id)
            if link in seen_links:
                continue
            seen_links.add(link)

            mix = (track.get("mix_name") or "").strip()
            full_title = f"{name} ({mix})" if mix and mix.lower() != "original mix" else name

            artists = [a["name"] for a in track.get("artists", []) if a.get("name")]
            remixers = [r["name"] for r in track.get("remixers", []) if r.get("name")]
            artist_str = ", ".join(artists) or "Unknown Artist"

            release = track.get("release") or {}
            label = (release.get("label") or {}).get("name", "")
            genre = (track.get("genre") or {}).get("name", "")
            bpm = track.get("bpm")
            key = track.get("key")
            key_name = key.get("name") if isinstance(key, dict) else key
            length = track.get("length", "")

            title = sanitize_xml(f"{artist_str} - {full_title}")

            bits = [f"Entered the Beatport Top 100 at #{rank}", f"Artists: {artist_str}"]
            if remixers:
                bits.append(f"Remixers: {', '.join(remixers)}")
            if genre:
                bits.append(f"Genre: {genre}")
            if bpm:
                bits.append(f"BPM: {bpm}")
            if key_name:
                bits.append(f"Key: {key_name}")
            if length:
                bits.append(f"Length: {length}")
            if label:
                bits.append(f"Label: {label}")
            description = sanitize_xml(" · ".join(bits))

            entries.append(
                {
                    "title": title,
                    "link": link,
                    "date": entry_date,
                    "description": description,
                }
            )
        except Exception as e:  # never let one bad track kill the run
            logger.warning(f"Skipping malformed track at rank {rank}: {e}")
            continue

    logger.info(f"Built {len(entries)} entries from the chart")
    return entries


def generate_atom_feed(entries, feed_name=FEED_NAME):
    """Build an Atom FeedGenerator from the entry list."""
    fg = FeedGenerator()
    fg.id(f"https://www.beatport.com/{feed_name}")
    fg.title("Beatport Top 100")
    fg.subtitle("Tracks as they enter the Beatport Top 100 chart")
    setup_feed_links(fg, BLOG_URL, feed_name)
    fg.language("en")
    fg.author({"name": "Beatport"})

    for entry in entries:
        fe = fg.add_entry()
        fe.id(entry["link"])
        fe.title(entry["title"])
        fe.link(href=entry["link"])
        fe.description(entry["description"])
        if entry.get("date"):
            fe.published(entry["date"])
            fe.updated(entry["date"])

    logger.info("Generated Atom feed")
    return fg


def save_atom_feed(fg, feed_name=FEED_NAME):
    """Write the feed to feeds/feed_<name>.xml in Atom format."""
    output_file = get_feeds_dir() / f"feed_{feed_name}.xml"
    fg.atom_file(str(output_file), pretty=True)
    logger.info(f"Saved Atom feed to {output_file}")
    return output_file


def main(full=False):
    """Fetch the chart, merge with cache, and write the Atom feed."""
    html = fetch_chart()
    if html is None:
        logger.error(
            "Could not fetch the Beatport Top 100 (Cloudflare may be blocking this IP). "
            "Skipping write so the last good feed is preserved."
        )
        return False

    tracks = extract_tracks(html)
    if not tracks:
        logger.warning("No tracks extracted — skipping write to avoid an empty feed")
        return False

    now = datetime.now(pytz.UTC)
    new_entries = build_entries(tracks, now)
    if not new_entries:
        logger.warning("No usable entries built — skipping write to avoid an empty feed")
        return False

    if full:
        logger.info("Full reset requested — ignoring existing cache")
        cached = []
    else:
        cache = load_cache(FEED_NAME)
        cached = deserialize_entries(cache.get("entries", []), date_field="date")

    # Dedupe by track URL; cached tracks keep their original first-seen date and
    # debut-rank description, so only genuinely new chart entrants are appended.
    merged = merge_entries(new_entries, cached, id_field="link", date_field="date")
    merged = sort_posts_for_feed(merged, date_field="date")

    # sort_posts_for_feed returns ascending (feedgen reverses on write), so keep
    # the tail to retain the most recently charted tracks.
    if len(merged) > MAX_ENTRIES:
        merged = merged[-MAX_ENTRIES:]

    save_cache(FEED_NAME, merged)

    fg = generate_atom_feed(merged)
    save_atom_feed(fg)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the Beatport Top 100 Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
