"""IMGW public data feed generator.

Turns IMGW-PIB's open API (https://danepubliczne.imgw.pl/) into a single Atom
feed combining five sources:

- **Synop** observations for one station (default ``12566`` — Kraków):
  one entry per calendar day, refreshed in place as new hourly readings arrive.
  Each entry accumulates the day's readings into a small table.
- **Hydro** water levels for nearby gauges (default Smolice/Wisła and
  Jeleń/Przemsza): one entry per station per day with the latest level, flow,
  and water temperature.
- **Meteo** telemetry for nearby stations (default ``250190790`` — Chrzanów):
  one entry per station per day with the latest non-null readings.
- **Meteo warnings** (``warningsmeteo``) filtered by TERYT powiat prefixes
  (default ``1203`` — powiat chrzanowski): one entry per warning id.
- **Hydro warnings** (``warningshydro``) filtered by voivodeship (default
  małopolskie + śląskie): one entry per warning.

No API key is needed. Each source is fetched and parsed in isolation — one
failing endpoint never blocks the others — and the run only fails (exit 1)
when *every* source comes back empty, so the last good feed is preserved.
An entry's ``updated`` timestamp only changes when its content actually
changes, so unchanged days don't churn the feed.

Configuration (env, all optional):
``IMGW_SYNOP_ID``, ``IMGW_HYDRO_IDS``, ``IMGW_METEO_IDS`` (comma-separated),
``IMGW_TERYT_PREFIXES`` (comma-separated powiat codes for meteo warnings),
``IMGW_WOJEWODZTWA`` (comma-separated, for hydro warnings).

Writes an **Atom** feed to ``feeds/feed_imgw.xml``; caches to
``cache/imgw_posts.json``.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime

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

FEED_NAME = "imgw"
BASE_URL = "https://danepubliczne.imgw.pl"
SITE_URL = "https://danepubliczne.imgw.pl/"

SYNOP_ID = os.getenv("IMGW_SYNOP_ID", "12566").strip()
HYDRO_IDS = [s.strip() for s in os.getenv("IMGW_HYDRO_IDS", "150190260,150190180").split(",") if s.strip()]
METEO_IDS = [s.strip() for s in os.getenv("IMGW_METEO_IDS", "250190790").split(",") if s.strip()]
TERYT_PREFIXES = tuple(
    s.strip() for s in os.getenv("IMGW_TERYT_PREFIXES", "1203").split(",") if s.strip()
)
WOJEWODZTWA = [
    s.strip().lower() for s in os.getenv("IMGW_WOJEWODZTWA", "małopolskie,śląskie").split(",") if s.strip()
]

PL_TZ = pytz.timezone("Europe/Warsaw")

# Roughly: ~5 observation entries/day + occasional warnings -> a few weeks.
MAX_ENTRIES = 150


def fetch_json(path: str, retries: int = 3, backoff: float = 2.0):
    """Fetch ``BASE_URL + path`` and parse JSON; return None on failure."""
    url = f"{BASE_URL}{path}"
    for attempt in range(1, retries + 1):
        try:
            return json.loads(fetch_page(url))
        except Exception as e:
            logger.warning(f"IMGW fetch failed for {url} (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(backoff * attempt)
    return None


def parse_pl_datetime(value: str | None) -> datetime | None:
    """Parse 'YYYY-MM-DD HH:MM:SS' (IMGW local time) into an aware datetime."""
    if not value:
        return None
    try:
        return PL_TZ.localize(datetime.strptime(value, "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return None


def _hash(*parts: str) -> str:
    return hashlib.sha1("\u0000".join(parts).encode("utf-8")).hexdigest()


def _fmt(value, unit: str = "") -> str:
    return "b.d." if value in (None, "") else f"{value}{unit}"


# ---------------------------------------------------------------------------
# Source: synop (one station, day entry accumulating hourly readings)
# ---------------------------------------------------------------------------


def synop_entries() -> list[dict]:
    data = fetch_json(f"/api/data/synop/id/{SYNOP_ID}")
    if not isinstance(data, dict) or not data.get("data_pomiaru"):
        logger.warning("Synop: no usable data")
        return []

    station = data.get("stacja", SYNOP_ID)
    date_str = data["data_pomiaru"]
    hour = str(data.get("godzina_pomiaru", "?")).zfill(2)

    reading = {
        "temperatura": data.get("temperatura"),
        "predkosc_wiatru": data.get("predkosc_wiatru"),
        "kierunek_wiatru": data.get("kierunek_wiatru"),
        "wilgotnosc_wzgledna": data.get("wilgotnosc_wzgledna"),
        "suma_opadu": data.get("suma_opadu"),
        "cisnienie": data.get("cisnienie"),
    }

    day_dt = PL_TZ.localize(datetime.strptime(date_str, "%Y-%m-%d"))
    entry = {
        "guid": f"urn:imgw:synop:{SYNOP_ID}:{date_str}",
        "kind": "synop",
        "station": station,
        "link": f"{BASE_URL}/api/data/synop/id/{SYNOP_ID}",
        "date": day_dt,
        "updated": datetime.now(pytz.UTC),
        "readings": {hour: reading},
    }
    render_synop(entry)
    return [entry]


def render_synop(entry: dict) -> None:
    """(Re)build title/description/hash from the accumulated readings."""
    station = entry["station"]
    readings = entry["readings"]
    hours = sorted(readings)
    latest = readings[hours[-1]]

    title = (
        f"{station} — obserwacje {entry['date'].strftime('%d.%m')}: "
        f"{_fmt(latest['temperatura'], '°C')}, "
        f"opad {_fmt(latest['suma_opadu'], ' mm')} (godz. {hours[-1]})"
    )

    rows = [
        f"<tr><td>{h}:00</td><td>{_fmt(r['temperatura'], '°C')}</td>"
        f"<td>{_fmt(r['predkosc_wiatru'], ' m/s')} / {_fmt(r['kierunek_wiatru'], '°')}</td>"
        f"<td>{_fmt(r['wilgotnosc_wzgledna'], '%')}</td>"
        f"<td>{_fmt(r['suma_opadu'], ' mm')}</td>"
        f"<td>{_fmt(r['cisnienie'], ' hPa')}</td></tr>"
        for h, r in sorted(readings.items())
    ]
    description = (
        f"<p>Obserwacje synoptyczne IMGW — stacja <strong>{station}</strong> ({SYNOP_ID})</p>"
        "<table><tr><th>Godz.</th><th>Temp.</th><th>Wiatr</th>"
        "<th>Wilg.</th><th>Opad</th><th>Ciśn.</th></tr>"
        + "".join(rows)
        + "</table>"
    )

    entry["title"] = sanitize_xml(title)
    entry["description"] = sanitize_xml(description)
    entry["summary_hash"] = _hash(entry["title"], entry["description"])


# ---------------------------------------------------------------------------
# Source: hydro (water gauges, one entry per station per day)
# ---------------------------------------------------------------------------


def hydro_entries() -> list[dict]:
    data = fetch_json("/api/data/hydro")
    if not isinstance(data, list):
        logger.warning("Hydro: no usable data")
        return []

    wanted = {s.get("id_stacji"): s for s in data if s.get("id_stacji") in HYDRO_IDS}
    entries = []
    for station_id in HYDRO_IDS:
        s = wanted.get(station_id)
        if not s:
            logger.warning(f"Hydro: station {station_id} not found in API response")
            continue
        try:
            measured = parse_pl_datetime(s.get("stan_wody_data_pomiaru"))
            if not measured:
                continue
            name = s.get("stacja", station_id)
            river = s.get("rzeka", "")
            date_str = measured.strftime("%Y-%m-%d")

            title = (
                f"{name} ({river}) — stan wody {_fmt(s.get('stan_wody'), ' cm')} "
                f"({measured.strftime('%d.%m %H:%M')})"
            )
            lines = [
                f"<p>Wodowskaz <strong>{name}</strong>, rzeka {river or 'b.d.'}, "
                f"woj. {s.get('wojewodztwo', 'b.d.')}</p>",
                "<ul>",
                f"<li>Stan wody: {_fmt(s.get('stan_wody'), ' cm')} ({measured.strftime('%d.%m %H:%M')})</li>",
            ]
            if s.get("przeplyw") not in (None, ""):
                przeplyw_dt = parse_pl_datetime(s.get("przeplyw_data"))
                kiedy = f" ({przeplyw_dt.strftime('%d.%m %H:%M')})" if przeplyw_dt else ""
                lines.append(f"<li>Przepływ: {s['przeplyw']} m³/s{kiedy}</li>")
            if s.get("temperatura_wody") not in (None, ""):
                lines.append(f"<li>Temperatura wody: {s['temperatura_wody']}°C</li>")
            lines.append("</ul>")

            title = sanitize_xml(title)
            description = sanitize_xml("".join(lines))
            entries.append(
                {
                    "guid": f"urn:imgw:hydro:{station_id}:{date_str}",
                    "kind": "hydro",
                    "title": title,
                    "link": f"{BASE_URL}/api/data/hydro",
                    "description": description,
                    "date": PL_TZ.localize(datetime.strptime(date_str, "%Y-%m-%d")),
                    "updated": datetime.now(pytz.UTC),
                    "summary_hash": _hash(title, description),
                }
            )
        except Exception as e:
            logger.warning(f"Hydro: skipping station {station_id}: {e}")
    return entries


# ---------------------------------------------------------------------------
# Source: meteo telemetry (one entry per station per day, latest readings)
# ---------------------------------------------------------------------------

METEO_FIELDS = [
    ("temperatura_powietrza", "Temperatura powietrza", "°C"),
    ("temperatura_gruntu", "Temperatura gruntu", "°C"),
    ("wilgotnosc_wzgledna", "Wilgotność względna", "%"),
    ("wiatr_srednia_predkosc", "Wiatr — średnia prędkość", " m/s"),
    ("wiatr_predkosc_maksymalna", "Wiatr — prędkość maksymalna", " m/s"),
    ("wiatr_poryw_10min", "Wiatr — poryw (10 min)", " m/s"),
    ("wiatr_kierunek", "Wiatr — kierunek", "°"),
    ("opad_10min", "Opad (10 min)", " mm"),
]


def meteo_entries() -> list[dict]:
    data = fetch_json("/api/data/meteo")
    if not isinstance(data, list):
        logger.warning("Meteo: no usable data")
        return []

    by_id = {s.get("kod_stacji"): s for s in data}
    entries = []
    for station_id in METEO_IDS:
        s = by_id.get(station_id)
        if not s:
            logger.warning(f"Meteo: station {station_id} not found in API response")
            continue
        try:
            # Newest measurement timestamp across the station's fields.
            stamps = [parse_pl_datetime(s.get(f"{key}_data")) for key, _, _ in METEO_FIELDS]
            stamps = [t for t in stamps if t]
            if not stamps:
                continue
            measured = max(stamps)
            name = (s.get("nazwa_stacji") or station_id).title()
            date_str = measured.strftime("%Y-%m-%d")

            lines = [
                f"<p>Telemetria IMGW — stacja <strong>{name}</strong> ({station_id})</p>",
                "<ul>",
            ]
            headline = []
            for key, label, unit in METEO_FIELDS:
                if s.get(key) in (None, ""):
                    continue
                stamp = parse_pl_datetime(s.get(f"{key}_data"))
                kiedy = f" ({stamp.strftime('%H:%M')})" if stamp else ""
                lines.append(f"<li>{label}: {s[key]}{unit}{kiedy}</li>")
                if key in ("temperatura_powietrza", "opad_10min"):
                    headline.append(f"{label.split(' — ')[0].lower()} {s[key]}{unit}")
            lines.append("</ul>")
            if len(lines) <= 3:
                continue  # nothing measured

            title = (
                f"{name} — telemetria {measured.strftime('%d.%m')}: "
                + (", ".join(headline) or "najnowsze odczyty")
                + f" ({measured.strftime('%H:%M')})"
            )
            title = sanitize_xml(title)
            description = sanitize_xml("".join(lines))
            entries.append(
                {
                    "guid": f"urn:imgw:meteo:{station_id}:{date_str}",
                    "kind": "meteo",
                    "title": title,
                    "link": f"{BASE_URL}/api/data/meteo",
                    "description": description,
                    "date": PL_TZ.localize(datetime.strptime(date_str, "%Y-%m-%d")),
                    "updated": datetime.now(pytz.UTC),
                    "summary_hash": _hash(title, description),
                }
            )
        except Exception as e:
            logger.warning(f"Meteo: skipping station {station_id}: {e}")
    return entries


# ---------------------------------------------------------------------------
# Sources: warnings (meteo by TERYT, hydro by voivodeship)
# ---------------------------------------------------------------------------

LEVEL_LABEL = {"1": "1. stopnia", "2": "2. stopnia", "3": "3. stopnia"}


def warning_meteo_entries() -> list[dict]:
    data = fetch_json("/api/data/warningsmeteo")
    if not isinstance(data, list):
        logger.warning("WarningsMeteo: no usable data")
        return []

    entries = []
    for w in data:
        try:
            teryt = w.get("teryt") or []
            if not any(code.startswith(TERYT_PREFIXES) for code in teryt):
                continue
            published = parse_pl_datetime(w.get("opublikowano")) or datetime.now(pytz.UTC)
            level = LEVEL_LABEL.get(str(w.get("stopien")), f"stopień {w.get('stopien')}")
            title = sanitize_xml(f"⚠️ Ostrzeżenie meteo {level}: {w.get('nazwa_zdarzenia', 'b.d.')}")
            lines = [
                f"<p><strong>{w.get('nazwa_zdarzenia', 'b.d.')}</strong> — ostrzeżenie {level}, "
                f"prawdopodobieństwo {_fmt(w.get('prawdopodobienstwo'), '%')}</p>",
                f"<p>Obowiązuje od {w.get('obowiazuje_od', 'b.d.')} do {w.get('obowiazuje_do', 'b.d.')}</p>",
                f"<p>{w.get('tresc', '')}</p>",
            ]
            if w.get("komentarz"):
                lines.append(f"<p><em>{w['komentarz']}</em></p>")
            if w.get("biuro"):
                lines.append(f"<p>{w['biuro']}</p>")
            description = sanitize_xml("".join(lines))
            entries.append(
                {
                    "guid": f"urn:imgw:warnmeteo:{w.get('id') or _hash(title, str(published))}",
                    "kind": "warning",
                    "title": title,
                    "link": f"{BASE_URL}/api/data/warningsmeteo",
                    "description": description,
                    "date": published,
                    "updated": datetime.now(pytz.UTC),
                    "summary_hash": _hash(title, description),
                }
            )
        except Exception as e:
            logger.warning(f"WarningsMeteo: skipping one warning: {e}")
    return entries


def warning_hydro_entries() -> list[dict]:
    data = fetch_json("/api/data/warningshydro")
    if not isinstance(data, list):
        logger.warning("WarningsHydro: no usable data")
        return []

    entries = []
    for w in data:
        try:
            obszary = w.get("obszary") or []
            wojs = {(o.get("wojewodztwo") or "").lower() for o in obszary}
            if not wojs.intersection(WOJEWODZTWA):
                continue
            published = parse_pl_datetime(w.get("opublikowano")) or datetime.now(pytz.UTC)
            zdarzenie = w.get("zdarzenie", "b.d.")
            opis = "; ".join(o.get("opis", "") for o in obszary if o.get("opis"))
            title = sanitize_xml(f"💧 Ostrzeżenie hydro: {zdarzenie} ({', '.join(sorted(wojs))})")
            lines = [
                f"<p><strong>{zdarzenie}</strong> — nr {w.get('numer', 'b.d.')}, "
                f"prawdopodobieństwo {_fmt(w.get('prawdopodobienstwo'), '%')}</p>",
                f"<p>Od {w.get('data_od', 'b.d.')} do {w.get('data_do', 'b.d.')}</p>",
                f"<p>{w.get('przebieg', '')}</p>",
            ]
            if opis:
                lines.append(f"<p>Obszar: {opis}</p>")
            if w.get("biuro"):
                lines.append(f"<p>{w['biuro']}</p>")
            description = sanitize_xml("".join(lines))
            guid_seed = f"{w.get('numer', '')}|{w.get('opublikowano', '')}|{zdarzenie}"
            entries.append(
                {
                    "guid": f"urn:imgw:warnhydro:{_hash(guid_seed)}",
                    "kind": "warning",
                    "title": title,
                    "link": f"{BASE_URL}/api/data/warningshydro",
                    "description": description,
                    "date": published,
                    "updated": datetime.now(pytz.UTC),
                    "summary_hash": _hash(title, description),
                }
            )
        except Exception as e:
            logger.warning(f"WarningsHydro: skipping one warning: {e}")
    return entries


# ---------------------------------------------------------------------------
# Merge / feed
# ---------------------------------------------------------------------------


def merge_in_place(new_entries: list[dict], cached: list[dict]) -> list[dict]:
    """Refresh entries by guid; preserve ``updated`` when content is unchanged.

    Synop day-entries additionally merge their accumulated hourly readings so a
    day's table grows across runs instead of holding only the latest reading.
    """
    by_guid = {e["guid"]: e for e in cached}
    for entry in new_entries:
        old = by_guid.get(entry["guid"])
        if old and entry.get("kind") == "synop" and isinstance(old.get("readings"), dict):
            merged_readings = dict(old["readings"])
            merged_readings.update(entry["readings"])
            entry["readings"] = merged_readings
            render_synop(entry)
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
    fg.id("urn:imgw:danepubliczne")
    fg.title("IMGW — pogoda, hydrologia i ostrzeżenia")
    fg.subtitle(
        "Obserwacje synoptyczne, stany wód, telemetria oraz ostrzeżenia meteo i hydro "
        "z danepubliczne.imgw.pl"
    )
    setup_feed_links(fg, SITE_URL, feed_name)
    fg.language("pl")
    fg.author({"name": "IMGW-PIB", "uri": SITE_URL})

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
    new_entries: list[dict] = []
    for source in (synop_entries, hydro_entries, meteo_entries, warning_meteo_entries, warning_hydro_entries):
        try:
            got = source()
            logger.info(f"{source.__name__}: {len(got)} entries")
            new_entries.extend(got)
        except Exception as e:
            logger.error(f"{source.__name__} failed: {e}")

    if not new_entries:
        logger.error("All IMGW sources empty/failed — skipping write to preserve the last good feed")
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
    parser = argparse.ArgumentParser(description="Generate the IMGW Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
