"""Open-Meteo feed generator.

Turns three free, keyless Open-Meteo APIs (https://open-meteo.com/) into one
Atom feed for a single location (default 50.1298, 19.4243 — Trzebinia):

- **Daily forecast** (`api.open-meteo.com/v1/forecast`, ``daily`` block):
  one entry per day — WMO condition (in Polish), temperatures (real and
  apparent), precipitation sum/probability/hours, wind, UV, sunshine and
  daylight, sunrise/sunset, CAPE. Upcoming days are refreshed in place as the
  forecast is revised.
- **Current conditions + air quality** (``current`` block +
  `air-quality-api.open-meteo.com/v1/air-quality`): one entry per day,
  refreshed in place with the latest reading — temperature, wind, pressure,
  cloud cover, plus European AQI, PM2.5/PM10, gases, and pollen.
- **Solar radiation** (`satellite-api.open-meteo.com/v1/archive`): one entry
  per past day with the measured shortwave radiation sum and sunshine duration
  (satellite data lags ~1–2 days, so days fill in as they become available).

No API key is needed. Each endpoint is fetched in isolation — one failing API
never blocks the others — and the run only fails (exit 1) when *everything*
comes back empty, preserving the last good feed. An entry's ``updated``
timestamp only changes when its content actually changes, so unchanged days
don't churn the feed.

Configuration (env, all optional): ``OPEN_METEO_LAT``, ``OPEN_METEO_LON``,
``OPEN_METEO_PLACE`` (display name), ``OPEN_METEO_DAYS`` (forecast horizon).

Writes an **Atom** feed to ``feeds/feed_open_meteo.xml``; caches to
``cache/open_meteo_posts.json``.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import date, datetime, timedelta

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

FEED_NAME = "open_meteo"
SITE_URL = "https://open-meteo.com/"

LAT = os.getenv("OPEN_METEO_LAT", "50.1298").strip()
LON = os.getenv("OPEN_METEO_LON", "19.4243").strip()
PLACE = os.getenv("OPEN_METEO_PLACE", "Trzebinia").strip()
FORECAST_DAYS = int(os.getenv("OPEN_METEO_DAYS", "7"))

PL_TZ = pytz.timezone("Europe/Warsaw")
LOC_SLUG = f"{LAT},{LON}"

FORECAST_URL = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={LAT}&longitude={LON}"
    "&daily=weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset,"
    "uv_index_max,rain_sum,showers_sum,snowfall_sum,precipitation_sum,"
    "precipitation_probability_max,precipitation_hours,daylight_duration,"
    "sunshine_duration,apparent_temperature_max,apparent_temperature_min,"
    "wind_speed_10m_max,wind_gusts_10m_max,wind_direction_10m_dominant,"
    "temperature_2m_mean,cape_mean"
    "&current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day,"
    "wind_speed_10m,wind_direction_10m,wind_gusts_10m,snowfall,showers,rain,"
    "precipitation,weather_code,cloud_cover,pressure_msl,surface_pressure"
    f"&models=best_match&timezone=auto&forecast_days={FORECAST_DAYS}"
)
AIR_QUALITY_URL = (
    "https://air-quality-api.open-meteo.com/v1/air-quality"
    f"?latitude={LAT}&longitude={LON}"
    "&current=european_aqi,pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,"
    "sulphur_dioxide,ozone,ammonia,uv_index,dust,aerosol_optical_depth,"
    "ragweed_pollen,olive_pollen,mugwort_pollen,grass_pollen,birch_pollen,"
    "alder_pollen&timezone=auto&forecast_days=1"
)
# NOTE: the archive's *daily* radiation aggregates come back null for the
# satellite models, but hourly values are populated — so we fetch hourly
# radiation plus daily astro fields and aggregate per day ourselves.
SATELLITE_URL_TMPL = (
    "https://satellite-api.open-meteo.com/v1/archive"
    f"?latitude={LAT}&longitude={LON}"
    "&hourly=shortwave_radiation,sunshine_duration"
    "&daily=sunrise,sunset,daylight_duration"
    "&models=satellite_radiation_seamless&timezone=auto"
    "&start_date={start}&end_date={end}"
)

# WMO weather interpretation codes, in Polish.
WMO_PL = {
    0: "bezchmurnie", 1: "przeważnie bezchmurnie", 2: "częściowe zachmurzenie",
    3: "pochmurno", 45: "mgła", 48: "mgła osadzająca szadź",
    51: "słaba mżawka", 53: "umiarkowana mżawka", 55: "gęsta mżawka",
    56: "słaba marznąca mżawka", 57: "gęsta marznąca mżawka",
    61: "słaby deszcz", 63: "umiarkowany deszcz", 65: "silny deszcz",
    66: "słaby marznący deszcz", 67: "silny marznący deszcz",
    71: "słabe opady śniegu", 73: "umiarkowane opady śniegu", 75: "silne opady śniegu",
    77: "ziarna śniegu", 80: "słabe przelotne opady deszczu",
    81: "umiarkowane przelotne opady deszczu", 82: "silne przelotne opady deszczu",
    85: "słabe przelotne opady śniegu", 86: "silne przelotne opady śniegu",
    95: "burza", 96: "burza z drobnym gradem", 99: "burza z silnym gradem",
}
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
WEEKDAY_PL = ["pon.", "wt.", "śr.", "czw.", "pt.", "sob.", "niedz."]

# 7 forecast days refreshed in place + 1 conditions + 1 solar per day -> weeks.
MAX_ENTRIES = 120


def fetch_json(url: str, retries: int = 3, backoff: float = 2.0):
    for attempt in range(1, retries + 1):
        try:
            data = json.loads(fetch_page(url))
            if isinstance(data, dict) and data.get("error"):
                logger.error(f"Open-Meteo API error: {data.get('reason', data)}")
                return None
            return data
        except Exception as e:
            logger.warning(f"Open-Meteo fetch failed (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(backoff * attempt)
    return None


def _hash(*parts: str) -> str:
    return hashlib.sha1("\u0000".join(parts).encode("utf-8")).hexdigest()


def wmo_desc(code) -> str:
    try:
        return WMO_PL.get(int(code), f"kod WMO {code}")
    except (TypeError, ValueError):
        return "b.d."


def compass(deg) -> str:
    try:
        return COMPASS[int((float(deg) / 22.5) + 0.5) % 16]
    except (TypeError, ValueError):
        return "b.d."


def _hm(seconds) -> str:
    try:
        m = int(round(float(seconds) / 60))
        return f"{m // 60} h {m % 60:02d} min"
    except (TypeError, ValueError):
        return "b.d."


def _t(value) -> str:
    return "b.d." if value is None else f"{round(float(value))}°C"


def _day_dt(date_str: str) -> datetime:
    return PL_TZ.localize(datetime.strptime(date_str, "%Y-%m-%d"))


def _col(daily: dict, key: str, i: int):
    values = daily.get(key)
    return values[i] if isinstance(values, list) and i < len(values) else None


# ---------------------------------------------------------------------------
# Source: daily forecast (one entry per day)
# ---------------------------------------------------------------------------


def forecast_day_entries(data: dict) -> list[dict]:
    daily = data.get("daily") or {}
    days = daily.get("time") or []
    entries = []
    for i, date_str in enumerate(days):
        try:
            desc = wmo_desc(_col(daily, "weather_code", i))
            t_max, t_min = _col(daily, "temperature_2m_max", i), _col(daily, "temperature_2m_min", i)
            day_dt = _day_dt(date_str)
            weekday = WEEKDAY_PL[day_dt.weekday()]
            title = f"{weekday} {day_dt.strftime('%d.%m')} — {desc}, {_t(t_min)} do {_t(t_max)}"

            sunrise = (_col(daily, "sunrise", i) or "T")[-5:]
            sunset = (_col(daily, "sunset", i) or "T")[-5:]
            precip = _col(daily, "precipitation_sum", i)
            lines = [
                f"<p><strong>{desc.capitalize()}</strong> · maks. {_t(t_max)} · min. {_t(t_min)} "
                f"(odczuwalna {_t(_col(daily, 'apparent_temperature_min', i))} do "
                f"{_t(_col(daily, 'apparent_temperature_max', i))})</p>",
                "<ul>",
                f"<li>Opady: {precip if precip is not None else 'b.d.'} mm "
                f"(prawdopodobieństwo {_col(daily, 'precipitation_probability_max', i)}%, "
                f"{_col(daily, 'precipitation_hours', i)} godz.)</li>",
                f"<li>Wiatr: do {_col(daily, 'wind_speed_10m_max', i)} km/h, "
                f"porywy do {_col(daily, 'wind_gusts_10m_max', i)} km/h, "
                f"kierunek {compass(_col(daily, 'wind_direction_10m_dominant', i))}</li>",
                f"<li>Indeks UV: {_col(daily, 'uv_index_max', i)}</li>",
                f"<li>Nasłonecznienie: {_hm(_col(daily, 'sunshine_duration', i))} "
                f"(dzień trwa {_hm(_col(daily, 'daylight_duration', i))})</li>",
                f"<li>Wschód {sunrise} · zachód {sunset}</li>",
            ]
            snow = _col(daily, "snowfall_sum", i)
            if snow:
                lines.append(f"<li>Śnieg: {snow} cm</li>")
            cape = _col(daily, "cape_mean", i)
            if cape is not None:
                lines.append(f"<li>CAPE (śr.): {round(float(cape))} J/kg</li>")
            lines.append("</ul>")

            title = sanitize_xml(f"{PLACE}: {title}")
            description = sanitize_xml("".join(lines))
            entries.append(
                {
                    "guid": f"urn:open-meteo:{LOC_SLUG}:day:{date_str}",
                    "kind": "forecast",
                    "title": title,
                    "link": SITE_URL,
                    "description": description,
                    "date": day_dt,
                    "updated": datetime.now(pytz.UTC),
                    "summary_hash": _hash(title, description),
                }
            )
        except Exception as e:
            logger.warning(f"Forecast: skipping day {date_str}: {e}")
    return entries


# ---------------------------------------------------------------------------
# Source: current conditions + air quality (one entry per day, refreshed)
# ---------------------------------------------------------------------------

AQI_LEVELS = [(20, "bardzo dobra"), (40, "dobra"), (60, "umiarkowana"),
              (80, "zła"), (100, "bardzo zła")]
POLLEN = [("grass_pollen", "trawy"), ("birch_pollen", "brzoza"), ("alder_pollen", "olcha"),
          ("mugwort_pollen", "bylica"), ("ragweed_pollen", "ambrozja"), ("olive_pollen", "oliwka")]


def aqi_label(value) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "b.d."
    for limit, label in AQI_LEVELS:
        if v <= limit:
            return label
    return "ekstremalnie zła"


def current_conditions_entry(forecast: dict | None, air: dict | None) -> list[dict]:
    cur = (forecast or {}).get("current") or {}
    aq = (air or {}).get("current") or {}
    if not cur and not aq:
        return []

    when = cur.get("time") or aq.get("time") or ""
    date_str = when[:10] or date.today().isoformat()
    hhmm = when[-5:] if "T" in when else "?"

    parts, lines = [], []
    if cur:
        desc = wmo_desc(cur.get("weather_code"))
        parts.append(f"{desc}, {_t(cur.get('temperature_2m'))}")
        lines += [
            f"<p><strong>{desc.capitalize()}</strong> · {_t(cur.get('temperature_2m'))} "
            f"(odczuwalna {_t(cur.get('apparent_temperature'))}) · stan z {hhmm}</p>",
            "<ul>",
            f"<li>Wiatr: {cur.get('wind_speed_10m')} km/h ({compass(cur.get('wind_direction_10m'))}), "
            f"porywy {cur.get('wind_gusts_10m')} km/h</li>",
            f"<li>Wilgotność: {cur.get('relative_humidity_2m')}% · zachmurzenie {cur.get('cloud_cover')}%</li>",
            f"<li>Ciśnienie: {cur.get('pressure_msl')} hPa (na poziomie morza)</li>",
        ]
        if cur.get("precipitation"):
            lines.append(f"<li>Opad: {cur['precipitation']} mm</li>")
        lines.append("</ul>")
    if aq:
        aqi = aq.get("european_aqi")
        parts.append(f"AQI {aqi} ({aqi_label(aqi)})")
        lines += [
            f"<p><strong>Jakość powietrza:</strong> europejski AQI {aqi} — {aqi_label(aqi)}</p>",
            "<ul>",
            f"<li>PM2.5: {aq.get('pm2_5')} µg/m³ · PM10: {aq.get('pm10')} µg/m³</li>",
            f"<li>NO₂: {aq.get('nitrogen_dioxide')} · O₃: {aq.get('ozone')} · "
            f"SO₂: {aq.get('sulphur_dioxide')} · CO: {aq.get('carbon_monoxide')} µg/m³</li>",
        ]
        pollen = [f"{label} {aq[key]}" for key, label in POLLEN if aq.get(key)]
        if pollen:
            lines.append(f"<li>Pyłki (ziarna/m³): {', '.join(pollen)}</li>")
        lines.append("</ul>")

    title = sanitize_xml(f"{PLACE} teraz ({hhmm}): " + " · ".join(parts))
    description = sanitize_xml("".join(lines))
    return [
        {
            "guid": f"urn:open-meteo:{LOC_SLUG}:current:{date_str}",
            "kind": "current",
            "title": title,
            "link": SITE_URL,
            "description": description,
            "date": _day_dt(date_str),
            "updated": datetime.now(pytz.UTC),
            "summary_hash": _hash(title, description),
        }
    ]


# ---------------------------------------------------------------------------
# Source: satellite radiation archive (one entry per measured past day)
# ---------------------------------------------------------------------------


def solar_entries() -> list[dict]:
    end = date.today()
    start = end - timedelta(days=6)
    data = fetch_json(SATELLITE_URL_TMPL.format(start=start.isoformat(), end=end.isoformat()))
    if not isinstance(data, dict):
        logger.warning("Satellite: no usable data")
        return []

    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    radiation = hourly.get("shortwave_radiation") or []
    sunshine = hourly.get("sunshine_duration") or []

    # Aggregate hourly values per calendar day: mean W/m2 over an hour
    # integrates to Wh/m2, converted to MJ/m2 (x 3600 / 1e6).
    per_day: dict[str, dict] = {}
    for i, stamp in enumerate(times):
        day = stamp[:10]
        rad = radiation[i] if i < len(radiation) else None
        if rad is None:
            continue
        agg = per_day.setdefault(day, {"rad_wh": 0.0, "sun_s": 0.0, "hours": 0})
        agg["rad_wh"] += float(rad)
        sun = sunshine[i] if i < len(sunshine) else None
        if sun is not None:
            agg["sun_s"] += float(sun)
        agg["hours"] += 1

    daily = data.get("daily") or {}
    astro = {d: i for i, d in enumerate(daily.get("time") or [])}

    entries = []
    today_str = end.isoformat()
    for date_str, agg in sorted(per_day.items()):
        try:
            # Only completed days with (near-)full coverage; today is partial.
            if date_str >= today_str or agg["hours"] < 20:
                continue
            rad_mj = agg["rad_wh"] * 3600 / 1e6
            day_dt = _day_dt(date_str)
            i = astro.get(date_str)
            title = sanitize_xml(
                f"{PLACE} — nasłonecznienie {day_dt.strftime('%d.%m')}: "
                f"{rad_mj:.2f} MJ/m², słońce {_hm(agg['sun_s'])}"
            )
            lines = [
                "<p>Pomiar satelitarny promieniowania słonecznego (Open-Meteo)</p><ul>",
                f"<li>Suma promieniowania krótkofalowego: {rad_mj:.2f} MJ/m²</li>",
                f"<li>Czas nasłonecznienia: {_hm(agg['sun_s'])}",
            ]
            if i is not None:
                lines[-1] += f" (dzień trwał {_hm(_col(daily, 'daylight_duration', i))})"
                lines.append(
                    f"</li><li>Wschód {(_col(daily, 'sunrise', i) or 'T')[-5:]} · "
                    f"zachód {(_col(daily, 'sunset', i) or 'T')[-5:]}</li></ul>"
                )
            else:
                lines.append("</li></ul>")
            description = sanitize_xml("".join(lines))
            entries.append(
                {
                    "guid": f"urn:open-meteo:{LOC_SLUG}:solar:{date_str}",
                    "kind": "solar",
                    "title": title,
                    "link": SITE_URL,
                    "description": description,
                    "date": day_dt,
                    "updated": datetime.now(pytz.UTC),
                    "summary_hash": _hash(title, description),
                }
            )
        except Exception as e:
            logger.warning(f"Satellite: skipping day {date_str}: {e}")
    return entries


# ---------------------------------------------------------------------------
# Merge / feed
# ---------------------------------------------------------------------------


def merge_in_place(new_entries: list[dict], cached: list[dict]) -> list[dict]:
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


def generate_atom_feed(entries: list[dict], feed_name: str = FEED_NAME) -> FeedGenerator:
    fg = FeedGenerator()
    fg.id(f"urn:open-meteo:{LOC_SLUG}")
    fg.title(f"Open-Meteo — prognoza i warunki ({PLACE})")
    fg.subtitle(
        "Prognoza dzienna, bieżące warunki z jakością powietrza oraz satelitarne "
        "pomiary nasłonecznienia z open-meteo.com"
    )
    setup_feed_links(fg, SITE_URL, feed_name)
    fg.language("pl")
    fg.author({"name": "Open-Meteo", "uri": SITE_URL})

    for entry in entries:
        fe = fg.add_entry()
        fe.id(entry["guid"])
        fe.title(entry["title"])
        fe.link(href=entry["link"])
        fe.content(entry["description"], type="html")
        fe.category(term=entry.get("kind", "weather"))
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
    forecast = fetch_json(FORECAST_URL)
    air = fetch_json(AIR_QUALITY_URL)

    new_entries: list[dict] = []
    if forecast:
        new_entries.extend(forecast_day_entries(forecast))
    else:
        logger.error("Forecast endpoint failed")
    new_entries.extend(current_conditions_entry(forecast, air))
    try:
        new_entries.extend(solar_entries())
    except Exception as e:
        logger.error(f"Satellite source failed: {e}")

    if not new_entries:
        logger.error("All Open-Meteo sources empty/failed — skipping write to preserve the last good feed")
        return False

    if full:
        logger.info("Full reset requested — ignoring existing cache")
        cached = []
    else:
        cached = _deserialize(load_cache(FEED_NAME).get("entries", []))

    merged = merge_in_place(new_entries, cached)
    if len(merged) > MAX_ENTRIES:
        merged = merged[-MAX_ENTRIES:]

    save_cache(FEED_NAME, merged)
    save_atom_feed(generate_atom_feed(merged))
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the Open-Meteo Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
