"""OpenWeather daily forecast feed generator.

Turns OpenWeather's free **5 day / 3 hour forecast** API
(https://openweathermap.org/forecast5) into a daily-forecast Atom feed. The
3-hour slots are aggregated into one entry per calendar day (in the city's own
timezone): daytime headline condition, high/low, chance of precipitation, wind,
humidity and total rain/snow.

This endpoint works with a standard free OpenWeather API key — no separate One
Call subscription is needed. Provide the key via the ``OPENWEATHER_API_KEY``
environment variable (a GitHub Actions secret in CI). The location defaults to
``Chrzanów,PL`` and can be overridden with ``OPENWEATHER_LOCATION``; units
default to metric and can be changed with ``OPENWEATHER_UNITS``
(``metric`` | ``imperial`` | ``standard``).

Each day is one Atom entry keyed by a synthetic ``urn:openweather:{loc}:{date}``
guid. A JSON cache (``cache/openweather_posts.json``) accumulates history across
hourly runs: past days are preserved as a record, while upcoming days are
refreshed in place as the forecast is revised — an entry's ``updated`` timestamp
only changes when its summary actually changes, so unchanged days don't churn
the feed. Writes an **Atom** feed to ``feeds/feed_openweather.xml``.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytz
from feedgen.feed import FeedGenerator

from utils import (
    fetch_page,
    get_feeds_dir,
    load_cache,
    sanitize_xml,
    save_cache,
    setup_feed_links,
    setup_logging,
    sort_posts_for_feed,
)

logger = setup_logging()

FEED_NAME = "openweather"

# Configuration (env-driven so the key is never committed).
API_KEY = os.getenv("OPENWEATHER_API_KEY", "").strip()
LOCATION = os.getenv("OPENWEATHER_LOCATION", "Chrzanów,PL").strip()
UNITS = os.getenv("OPENWEATHER_UNITS", "metric").strip().lower()

FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"

# Unit symbols by `units` mode.
TEMP_UNIT = {"metric": "°C", "imperial": "°F", "standard": "K"}.get(UNITS, "°C")
WIND_UNIT = {"metric": "m/s", "imperial": "mph", "standard": "m/s"}.get(UNITS, "m/s")

# Keep ~a month of history; the forecast itself only spans ~5 days ahead.
MAX_ENTRIES = 40


def fetch_forecast(retries: int = 3, backoff: float = 2.0):
    """Fetch the 5-day/3-hour forecast JSON for LOCATION, or None on failure."""
    if not API_KEY:
        logger.error(
            "OPENWEATHER_API_KEY is not set. Export it locally or add it as a "
            "GitHub Actions secret; skipping to preserve the last good feed."
        )
        return None

    params = f"?q={LOCATION}&appid={API_KEY}&units={UNITS}"
    url = FORECAST_URL + params
    safe_url = url.replace(API_KEY, "***")

    for attempt in range(1, retries + 1):
        try:
            body = fetch_page(url)
            data = json.loads(body)
            # OpenWeather returns cod as string "200" on success here.
            if str(data.get("cod")) != "200":
                logger.error(f"OpenWeather error for {LOCATION}: {data.get('message', data)}")
                return None
            return data
        except Exception as e:
            logger.warning(f"Forecast fetch failed for {safe_url} (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(backoff * attempt)
    return None


def _fmt_temp(value) -> str:
    return f"{round(value)}{TEMP_UNIT}"


def aggregate_daily(data: dict) -> list[dict]:
    """Collapse 3-hour slots into per-day summaries in the city's timezone."""
    city = data.get("city", {})
    tz_offset = int(city.get("timezone", 0))  # seconds east of UTC
    tz = timezone(timedelta(seconds=tz_offset))
    city_name = city.get("name", LOCATION)
    country = city.get("country", "")
    city_id = city.get("id")

    # Group slots by local calendar date.
    days: dict[str, list[dict]] = {}
    for slot in data.get("list", []):
        local_dt = datetime.fromtimestamp(slot["dt"], tz)
        days.setdefault(local_dt.date().isoformat(), []).append((local_dt, slot))

    entries = []
    for date_str, slots in days.items():
        slots.sort(key=lambda s: s[0])
        temps = [s[1]["main"]["temp"] for s in slots]
        t_hi, t_lo = max(temps), min(temps)

        # Headline condition: the slot closest to 13:00 local (daytime weather).
        midday_dt, midday_slot = min(slots, key=lambda s: abs(s[0].hour - 13))
        weather = (midday_slot.get("weather") or [{}])[0]
        # If midday is calm but the day is dominated by another condition, prefer
        # the most frequent description across the day.
        descs = [(s[1].get("weather") or [{}])[0].get("description", "") for s in slots]
        common_desc = Counter(d for d in descs if d).most_common(1)
        description = (common_desc[0][0] if common_desc else weather.get("description", "")) or "no data"
        description = description.strip().capitalize()

        pop = max((s[1].get("pop", 0) or 0) for s in slots)
        humidity = round(sum(s[1]["main"].get("humidity", 0) for s in slots) / len(slots))
        wind = max((s[1].get("wind", {}).get("speed", 0) or 0) for s in slots)
        feels = midday_slot["main"].get("feels_like", midday_slot["main"]["temp"])
        rain = sum((s[1].get("rain", {}).get("3h", 0) or 0) for s in slots)
        snow = sum((s[1].get("snow", {}).get("3h", 0) or 0) for s in slots)

        local_date = datetime.fromisoformat(date_str).replace(tzinfo=tz)
        weekday = local_date.strftime("%a %d %b")

        title = sanitize_xml(
            f"{weekday} — {description}, {round(t_lo)}–{round(t_hi)}{TEMP_UNIT}"
        )

        lines = [
            f"<p><strong>{description}</strong> · High {_fmt_temp(t_hi)} · Low {_fmt_temp(t_lo)}</p>",
            "<ul>",
            f"<li>Chance of precipitation: {round(pop * 100)}%</li>",
            f"<li>Feels like (midday): {_fmt_temp(feels)}</li>",
            f"<li>Wind: up to {wind:.1f} {WIND_UNIT}</li>",
            f"<li>Humidity: {humidity}%</li>",
        ]
        if rain:
            lines.append(f"<li>Rain: {rain:.1f} mm</li>")
        if snow:
            lines.append(f"<li>Snow: {snow:.1f} mm</li>")
        lines.append("</ul>")
        if len(slots) < 5:
            lines.append("<p><em>Partial day (forecast window does not cover all hours).</em></p>")
        description_html = sanitize_xml("\n".join(lines))

        # Stable per-location, per-day id; refreshed in place across runs.
        loc_slug = LOCATION.lower().replace(" ", "").replace(",", "-")
        guid = f"urn:openweather:{loc_slug}:{date_str}"
        link = (
            f"https://openweathermap.org/city/{city_id}"
            if city_id
            else "https://openweathermap.org/"
        )
        place = f"{city_name}, {country}".strip(", ")

        entries.append(
            {
                "guid": guid,
                "title": f"{place}: {title}",
                "link": link,
                "description": description_html,
                "date": local_date,  # day midnight, used for ordering + published
                "updated": datetime.now(pytz.UTC),
                "summary_hash": hashlib.sha1(
                    (title + description_html).encode("utf-8")
                ).hexdigest(),
            }
        )
    return entries


def merge_forecast(new_entries: list[dict], cached: list[dict]) -> list[dict]:
    """Refresh upcoming days in place, keep past days as history.

    New data overwrites the cached entry for the same day. If the day's summary
    is unchanged, the original ``updated`` timestamp is preserved so the feed
    doesn't churn; otherwise ``updated`` reflects the latest revision.
    """
    by_guid = {e["guid"]: e for e in cached}
    for entry in new_entries:
        old = by_guid.get(entry["guid"])
        if old and old.get("summary_hash") == entry["summary_hash"]:
            entry["updated"] = old.get("updated", entry["updated"])
        by_guid[entry["guid"]] = entry
    return sort_posts_for_feed(list(by_guid.values()), date_field="date")


def _deserialize(cached: list[dict]) -> list[dict]:
    """Restore datetime fields (date, updated) from ISO strings in the cache."""
    out = []
    for entry in cached:
        e = entry.copy()
        for field in ("date", "updated"):
            if isinstance(e.get(field), str):
                try:
                    e[field] = datetime.fromisoformat(e[field])
                except ValueError:
                    e[field] = None
        out.append(e)
    return out


def generate_atom_feed(entries: list[dict], feed_name: str = FEED_NAME) -> FeedGenerator:
    fg = FeedGenerator()
    fg.id(f"urn:openweather:{LOCATION.lower().replace(' ', '').replace(',', '-')}")
    fg.title(f"Daily weather forecast — {LOCATION}")
    fg.subtitle("Daily forecast aggregated from OpenWeather's 5-day/3-hour data")
    blog_url = entries[0]["link"] if entries else "https://openweathermap.org/"
    setup_feed_links(fg, blog_url, feed_name)
    fg.language("en")
    fg.author({"name": "OpenWeather", "uri": "https://openweathermap.org/"})

    for entry in entries:
        fe = fg.add_entry()
        fe.id(entry["guid"])
        fe.title(entry["title"])
        fe.link(href=entry["link"])
        fe.content(entry["description"], type="html")
        fe.category(term="weather")
        if entry.get("date"):
            fe.published(entry["date"])
        if entry.get("updated"):
            fe.updated(entry["updated"])
        elif entry.get("date"):
            fe.updated(entry["date"])

    logger.info("Generated Atom feed")
    return fg


def save_atom_feed(fg: FeedGenerator, feed_name: str = FEED_NAME):
    output_file = get_feeds_dir() / f"feed_{feed_name}.xml"
    fg.atom_file(str(output_file), pretty=True)
    logger.info(f"Saved Atom feed to {output_file}")
    return output_file


def main(full: bool = False) -> bool:
    data = fetch_forecast()
    if data is None:
        logger.error("No forecast data — skipping write to preserve the last good feed")
        return False

    new_entries = aggregate_daily(data)
    if not new_entries:
        logger.warning("Forecast returned no usable days — skipping write")
        return False

    if full:
        logger.info("Full reset requested — ignoring existing cache")
        cached = []
    else:
        cache = load_cache(FEED_NAME)
        cached = _deserialize(cache.get("entries", []))

    merged = merge_forecast(new_entries, cached)
    if len(merged) > MAX_ENTRIES:
        merged = merged[-MAX_ENTRIES:]

    save_cache(FEED_NAME, merged)
    save_atom_feed(generate_atom_feed(merged))
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the OpenWeather daily forecast Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
