"""Visual Crossing daily forecast feed generator.

Turns the Visual Crossing Timeline API
(https://www.visualcrossing.com/resources/documentation/weather-api/timeline-weather-api/)
into a daily-forecast Atom feed. Unlike raw 3-hourly sources, this endpoint
returns ready-made **daily** aggregates (high/low, precip probability, wind,
humidity, UV, sunrise/sunset, etc.), and with ``lang=pl`` the ``conditions`` and
``description`` text is already localized to Polish — so each entry reads
naturally without any rollup on our side.

Weather **alerts** returned by the API are emitted as their own entries.

The API key is read from ``VISUALCROSSING_API_KEY`` (a GitHub Actions secret in
CI) and never committed. Location defaults to ``32-500 Kasztanowa`` (Chrzanów) and
is overridable with ``VISUALCROSSING_LOCATION``; ``VISUALCROSSING_UNITS``
(default ``metric``) and ``VISUALCROSSING_LANG`` (default ``pl``) are also
configurable.

Each day is one Atom entry keyed by ``urn:visualcrossing:{loc}:{date}``; alerts
by ``urn:visualcrossing:{loc}:alert:{hash}``. A JSON cache
(``cache/visualcrossing_posts.json``) accumulates history across hourly runs:
past days are preserved, upcoming days are refreshed in place as the forecast is
revised, and an entry's ``updated`` timestamp only changes when its summary
actually changes — so unchanged days don't churn the feed. Writes an **Atom**
feed to ``feeds/feed_visualcrossing.xml``.
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.parse
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

FEED_NAME = "visualcrossing"

# Configuration (env-driven so the key is never committed).
API_KEY = os.getenv("VISUALCROSSING_API_KEY", "").strip()
LOCATION = os.getenv("VISUALCROSSING_LOCATION", "32-500 Kasztanowa").strip()
UNITS = os.getenv("VISUALCROSSING_UNITS", "metric").strip().lower()
LANG = os.getenv("VISUALCROSSING_LANG", "pl").strip().lower()

BASE_URL = (
    "https://weather.visualcrossing.com/VisualCrossingWebServices/"
    "rest/services/timeline"
)

# Air-quality / extra elements appended to the default element set.
# `add:` keeps all default day fields and adds these on top.
EXTRA_ELEMENTS = ",".join(
    f"add:{e}"
    for e in (
        "aqieur", "aqielement",
        "pm1", "pm2p5", "pm10",
        "o3", "no2", "so2", "co",
        "lightningrisk",
    )
)

# European Air Quality Index (CAMS) levels, 1 (best) .. 6 (worst).
AQI_EUR_LEVELS = {
    "pl": {1: "bardzo dobra", 2: "dobra", 3: "umiarkowana",
           4: "zła", 5: "bardzo zła", 6: "ekstremalnie zła"},
    "en": {1: "good", 2: "fair", 3: "moderate",
           4: "poor", 5: "very poor", 6: "extremely poor"},
}

# Unit symbols by `unitGroup`.
TEMP_UNIT = {"metric": "°C", "us": "°F", "uk": "°C", "base": "K"}.get(UNITS, "°C")
WIND_UNIT = {"metric": "km/h", "us": "mph", "uk": "mph", "base": "m/s"}.get(UNITS, "km/h")
PRECIP_UNIT = {"metric": "mm", "us": "in", "uk": "mm", "base": "mm"}.get(UNITS, "mm")

# Keep ~a month of history; the forecast spans ~7 days ahead.
MAX_ENTRIES = 45

# Polish day/month names so we don't depend on a system locale being installed.
PL_WEEKDAYS = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]
PL_MONTHS = [
    "stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
    "lipca", "sierpnia", "września", "października", "listopada", "grudnia",
]

# UI labels, localized for the default Polish feed (fall back to English).
LABELS = {
    "pl": {
        "temp": "Temperatura", "minmax": "Min/Maks", "feels": "Odczuwalna",
        "precip_prob": "Szansa opadów", "precip": "Opady", "snow": "Śnieg",
        "wind": "Wiatr", "gust": "porywy", "humidity": "Wilgotność",
        "uv": "Indeks UV", "cloud": "Zachmurzenie", "sunrise": "Wschód słońca",
        "sunset": "Zachód słońca", "alert": "Ostrzeżenie pogodowe",
        "aqi": "Jakość powietrza (AQI EU)", "aqi_dominant": "dominuje",
        "pm": "Pyły", "gases": "Gazy", "lightning": "Ryzyko burz",
    },
}
DEFAULT_LABELS = {
    "temp": "Temperature", "minmax": "Min/Max", "feels": "Feels like",
    "precip_prob": "Chance of precipitation", "precip": "Precipitation",
    "snow": "Snow", "wind": "Wind", "gust": "gusts", "humidity": "Humidity",
    "uv": "UV index", "cloud": "Cloud cover", "sunrise": "Sunrise",
    "sunset": "Sunset", "alert": "Weather alert",
    "aqi": "Air quality (EU AQI)", "aqi_dominant": "dominant",
    "pm": "Particulates", "gases": "Gases", "lightning": "Lightning risk",
}
L = LABELS.get(LANG, DEFAULT_LABELS)


def fetch_timeline(retries: int = 3, backoff: float = 2.0):
    """Fetch the Timeline forecast JSON for LOCATION, or None on failure."""
    if not API_KEY:
        logger.error(
            "VISUALCROSSING_API_KEY is not set. Export it locally or add it as "
            "a GitHub Actions secret; skipping to preserve the last good feed."
        )
        return None

    loc = urllib.parse.quote(LOCATION, safe="")
    params = urllib.parse.urlencode(
        {
            "unitGroup": UNITS,
            "include": "days,alerts",
            "elements": EXTRA_ELEMENTS,
            "key": API_KEY,
            "lang": LANG,
            "contentType": "json",
        }
    )
    url = f"{BASE_URL}/{loc}/today/next6days?{params}"
    safe_url = url.replace(API_KEY, "***")

    for attempt in range(1, retries + 1):
        try:
            body = fetch_page(url)
            return json.loads(body)
        except Exception as e:
            logger.warning(f"Timeline fetch failed for {safe_url} (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(backoff * attempt)
    return None


def _r(value) -> str:
    """Round a number for display, dropping a trailing .0."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return "—"
    return str(int(round(f)))


def _loc_slug() -> str:
    return urllib.parse.quote(LOCATION.lower().replace(" ", ""), safe="")


def _pl_date(local_date: datetime) -> str:
    """e.g. 'niedziela, 31 maja' (no locale dependency)."""
    if LANG == "pl":
        return f"{PL_WEEKDAYS[local_date.weekday()]}, {local_date.day} {PL_MONTHS[local_date.month - 1]}"
    return local_date.strftime("%a %d %b")


def _air_quality_lines(day: dict) -> list[str]:
    """Render air-quality <li> lines for a day, or [] if no AQ data."""
    lines = []
    aqi = day.get("aqieur")
    if aqi is not None:
        level = AQI_EUR_LEVELS.get(LANG, AQI_EUR_LEVELS["en"]).get(int(aqi), "")
        dominant = (
            (day.get("aqielement") or "")
            .replace("pm2p5", "PM2.5").replace("pm10", "PM10").replace("pm1", "PM1")
            .replace("o3", "O₃").replace("no2", "NO₂").replace("so2", "SO₂")
            .replace("co", "CO").replace(",", ", ")
        )
        text = f"{L['aqi']}: {int(aqi)}/6"
        if level:
            text += f" ({level})"
        if dominant:
            text += f" — {L['aqi_dominant']}: {dominant}"
        lines.append(f"<li>{text}</li>")

    pm = [
        f"{name} {_r(day[key])}"
        for key, name in (("pm1", "PM1"), ("pm2p5", "PM2.5"), ("pm10", "PM10"))
        if day.get(key) is not None
    ]
    if pm:
        lines.append(f"<li>{L['pm']}: {' · '.join(pm)} µg/m³</li>")

    gases = [
        f"{name} {_r(day[key])}"
        for key, name in (("o3", "O₃"), ("no2", "NO₂"), ("so2", "SO₂"), ("co", "CO"))
        if day.get(key) is not None
    ]
    if gases:
        lines.append(f"<li>{L['gases']}: {' · '.join(gases)} µg/m³</li>")

    risk = day.get("lightningrisk")
    if risk:
        lines.append(f"<li>{L['lightning']}: {_r(risk)}%</li>")
    return lines


def build_day_entries(data: dict) -> list[dict]:
    """Build one entry per forecast day from the Timeline `days` array."""
    tz_offset = float(data.get("tzoffset", 0))
    tz = timezone(timedelta(hours=tz_offset))
    address = data.get("resolvedAddress", LOCATION)
    lat = data.get("latitude")
    lon = data.get("longitude")
    link = "https://www.visualcrossing.com/weather-history/" + urllib.parse.quote(LOCATION)

    entries = []
    for day in data.get("days", []):
        date_str = day["datetime"]
        local_date = datetime.fromisoformat(date_str).replace(tzinfo=tz)

        conditions = (day.get("conditions") or "").strip()
        description = (day.get("description") or conditions or "").strip()
        t_hi, t_lo = day.get("tempmax"), day.get("tempmin")
        feels_hi, feels_lo = day.get("feelslikemax"), day.get("feelslikemin")
        pop = day.get("precipprob") or 0
        precip = day.get("precip") or 0
        snow = day.get("snow") or 0
        wind = day.get("windspeed") or 0
        gust = day.get("windgust") or 0
        humidity = day.get("humidity") or 0
        uv = day.get("uvindex")
        cloud = day.get("cloudcover")
        sunrise = day.get("sunrise", "")[:5]
        sunset = day.get("sunset", "")[:5]

        title = sanitize_xml(
            f"{_pl_date(local_date)}: {conditions or '—'}, "
            f"{_r(t_lo)}–{_r(t_hi)}{TEMP_UNIT}"
        )

        lines = []
        if description:
            lines.append(f"<p>{description}</p>")
        lines.append("<ul>")
        lines.append(f"<li>{L['minmax']}: {_r(t_lo)}{TEMP_UNIT} / {_r(t_hi)}{TEMP_UNIT}</li>")
        if feels_lo is not None and feels_hi is not None:
            lines.append(f"<li>{L['feels']}: {_r(feels_lo)}{TEMP_UNIT} / {_r(feels_hi)}{TEMP_UNIT}</li>")
        lines.append(f"<li>{L['precip_prob']}: {_r(pop)}%</li>")
        if precip:
            lines.append(f"<li>{L['precip']}: {precip:.1f} {PRECIP_UNIT}</li>")
        if snow:
            lines.append(f"<li>{L['snow']}: {snow:.1f} {PRECIP_UNIT}</li>")
        lines.append(f"<li>{L['wind']}: {_r(wind)} {WIND_UNIT} ({L['gust']} {_r(gust)} {WIND_UNIT})</li>")
        lines.append(f"<li>{L['humidity']}: {_r(humidity)}%</li>")
        if uv is not None:
            lines.append(f"<li>{L['uv']}: {_r(uv)}</li>")
        if cloud is not None:
            lines.append(f"<li>{L['cloud']}: {_r(cloud)}%</li>")
        if sunrise and sunset:
            lines.append(f"<li>{L['sunrise']}: {sunrise} · {L['sunset']}: {sunset}</li>")
        lines.extend(_air_quality_lines(day))
        lines.append("</ul>")
        description_html = sanitize_xml("\n".join(lines))

        guid = f"urn:visualcrossing:{_loc_slug()}:{date_str}"
        entries.append(
            {
                "guid": guid,
                "title": f"{address} — {title}",
                "link": link,
                "description": description_html,
                "date": local_date,
                "updated": datetime.now(pytz.UTC),
                "kind": "day",
                "summary_hash": hashlib.sha1(
                    (title + description_html).encode("utf-8")
                ).hexdigest(),
            }
        )
    return entries


def build_alert_entries(data: dict) -> list[dict]:
    """Build entries from any weather alerts in the response."""
    tz_offset = float(data.get("tzoffset", 0))
    tz = timezone(timedelta(hours=tz_offset))
    address = data.get("resolvedAddress", LOCATION)
    entries = []
    for alert in data.get("alerts", []) or []:
        event = (alert.get("event") or L["alert"]).strip()
        headline = (alert.get("headline") or "").strip()
        body = (alert.get("description") or "").strip()
        onset = alert.get("onset") or alert.get("date") or ""
        try:
            when = datetime.fromisoformat(onset).replace(tzinfo=tz) if onset else datetime.now(tz)
        except ValueError:
            when = datetime.now(tz)

        raw = (event + headline + body + str(onset)).encode("utf-8")
        guid = f"urn:visualcrossing:{_loc_slug()}:alert:{hashlib.sha1(raw).hexdigest()[:16]}"
        parts = []
        if headline:
            parts.append(f"<p><strong>{sanitize_xml(headline)}</strong></p>")
        if body:
            parts.append(f"<p>{sanitize_xml(body)}</p>")
        description_html = "\n".join(parts) or sanitize_xml(event)

        entries.append(
            {
                "guid": guid,
                "title": f"⚠️ {address} — {sanitize_xml(event)}",
                "link": alert.get("link") or "https://www.visualcrossing.com/",
                "description": description_html,
                "date": when,
                "updated": datetime.now(pytz.UTC),
                "kind": "alert",
                "summary_hash": hashlib.sha1((event + description_html).encode("utf-8")).hexdigest(),
            }
        )
    return entries


def merge_forecast(new_entries: list[dict], cached: list[dict]) -> list[dict]:
    """Refresh entries in place by guid; preserve `updated` when unchanged."""
    by_guid = {e["guid"]: e for e in cached}
    for entry in new_entries:
        old = by_guid.get(entry["guid"])
        if old and old.get("summary_hash") == entry["summary_hash"]:
            entry["updated"] = old.get("updated", entry["updated"])
        by_guid[entry["guid"]] = entry
    return sort_posts_for_feed(list(by_guid.values()), date_field="date")


def _deserialize(cached: list[dict]) -> list[dict]:
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


def generate_atom_feed(entries: list[dict], data: dict | None = None,
                       feed_name: str = FEED_NAME) -> FeedGenerator:
    address = (data or {}).get("resolvedAddress", LOCATION)
    fg = FeedGenerator()
    fg.id(f"urn:visualcrossing:{_loc_slug()}")
    if LANG == "pl":
        fg.title(f"Prognoza pogody — {address}")
        fg.subtitle("Dzienna prognoza pogody (Visual Crossing)")
    else:
        fg.title(f"Daily weather forecast — {address}")
        fg.subtitle("Daily forecast from the Visual Crossing Timeline API")
    blog_url = entries[0]["link"] if entries else "https://www.visualcrossing.com/"
    setup_feed_links(fg, blog_url, feed_name)
    fg.language(LANG)
    fg.author({"name": "Visual Crossing", "uri": "https://www.visualcrossing.com/"})

    for entry in entries:
        fe = fg.add_entry()
        fe.id(entry["guid"])
        fe.title(entry["title"])
        fe.link(href=entry["link"])
        fe.content(entry["description"], type="html")
        fe.category(term="alert" if entry.get("kind") == "alert" else "weather")
        if entry.get("date"):
            fe.published(entry["date"])
        fe.updated(entry.get("updated") or entry.get("date"))

    logger.info("Generated Atom feed")
    return fg


def save_atom_feed(fg: FeedGenerator, feed_name: str = FEED_NAME):
    output_file = get_feeds_dir() / f"feed_{feed_name}.xml"
    fg.atom_file(str(output_file), pretty=True)
    logger.info(f"Saved Atom feed to {output_file}")
    return output_file


def main(full: bool = False) -> bool:
    data = fetch_timeline()
    if data is None:
        logger.error("No forecast data — skipping write to preserve the last good feed")
        return False

    new_entries = build_day_entries(data) + build_alert_entries(data)
    if not new_entries:
        logger.warning("Timeline returned no usable days — skipping write")
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
    save_atom_feed(generate_atom_feed(merged, data))
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the Visual Crossing daily forecast Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
