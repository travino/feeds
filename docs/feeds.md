# Feed notes

Per-feed background: why each non-trivial feed exists, where the data comes
from, and the trade-offs involved.

## About the Beatport feed

Beatport's [Top 100](https://www.beatport.com/top-100) page is a Next.js app
with no native feed, but the full chart is embedded in the page's
`__NEXT_DATA__` JSON, so it can be read with a plain request (no browser
automation). Because the chart is a *ranking* rather than a stream, this feed
is framed as **tracks as they enter the Top 100**: each track is an entry keyed
by its Beatport URL and dated when first seen, with its debut rank kept in the
summary. A JSON cache (`cache/beatport_top100_posts.json`) accumulates history
across scheduled runs and dedupes by track URL.

Beatport is behind Cloudflare, which fingerprints the TLS handshake and returns
HTTP 403 to plain `requests`. The generator uses `curl_cffi` (Chrome
impersonation) to fetch the page; if a run is blocked it skips writing so the
last good feed is preserved.

## About the Daily Digest feed

A single Atom feed that combines five small JSON APIs into one stream: the
ZenQuotes [quote of the day](https://zenquotes.io/api/today), and ViewBits'
[useless fact](https://api.viewbits.com/v1/uselessfacts?mode=today),
[life hack](https://api.viewbits.com/v1/lifehacks?mode=today),
[fortune cookie](https://api.viewbits.com/v1/fortunecookie?mode=today), and
[news headlines](https://api.viewbits.com/v1/headlines). Each source is fetched
independently, so one being down never sinks the run.

A JSON cache (`cache/daily_digest_posts.json`) accumulates history across scheduled
runs and dedupes entries by `guid`. Headlines are keyed by article URL. The four
"today" endpoints expose only a single URL each (no per-day permalink), so they
are keyed by a synthetic `{kind}:{date}` guid dated to that day, while their
clickable link still points at the original source — re-runs within a day don't
churn the feed, but each new day's quote/fact/hack/fortune is added as a fresh
entry. The merged feed is capped at the newest 100 entries; if every source
fails, the run skips writing so the last good feed is preserved.

## About the Lenovo feed

**One combined feed** from four native Lenovo sources: the global
[StoryHub newsroom](https://news.lenovo.com/), the Polish partner news site
[lenovo24.pl](https://lenovo24.pl/news) (which hides a native RSS at
`/rss.xml`), [lenovogaming.pl](https://lenovogaming.pl/), and the
[CDRT Think Deploy blog](https://blog.lenovocdrt.com/). Entries carry a
per-source `<category>` label and are deduplicated across sources by
normalized URL and title. lenovo24.pl items ship no dates, so they surface as
dateless entries. The Legion Gaming Community forum (gaming.lenovo.com) was
evaluated and skipped: it is reCAPTCHA-gated and returns empty bodies to
automated clients.

## About the RA feed

[RA (Resident Advisor)](https://ra.co/magazine) has no native feed and is a
Next.js + Apollo app behind DataDome bot protection. The article listings load
client-side, but the server still ships the Apollo cache in the page's
`__NEXT_DATA__` blob (`props.apolloState`), so one `curl_cffi` (Chrome
impersonation) fetch per section is enough — no browser, no GraphQL calls.

This is **one combined feed** from three sections: `/magazine` (news + featured
pieces), `/features` (long-form articles), and `/music` (reviews, podcasts,
music news). The sections overlap, so entries are **deduplicated by their
content URL** across all three; when the same piece appears both dated (e.g. on
`/magazine`) and dateless (the slimmer `/music` projection), the dated copy
wins regardless of fetch order. News and Features carry real publish dates;
Reviews, Podcasts, and music-only News have none in the listing, so — like the
Beatport feed — they're dated when first seen, with that timestamp preserved in
`cache/ra_posts.json` across scheduled runs. If no section can be fetched the run
skips writing so the last good feed is preserved.

## About the Nexus Mods News feed

Nexus Mods has no native feed for its [news section](https://www.nexusmods.com/news)
and, like Beatport, sits behind Cloudflare (HTTP 403 to plain `requests`). The
listing is server-rendered, though, so no browser automation is needed: the
generator uses `curl_cffi` (Chrome impersonation) to clear the bot check and
parses the `div.tile-content` article cards for title, link, date, author,
category, and summary.

A JSON cache (`cache/nexusmods_news_posts.json`) accumulates history across
scheduled runs and dedupes by article URL. Incremental runs fetch only page 1 and
merge; `make feeds_nexusmods_news_full` (or `--full`) walks several `?page=N`
pages to backfill the archive. If a run returns no articles it skips writing so
the last good feed is preserved.

## About the OpenWeather feed

A daily forecast feed for Chrzanów built from OpenWeather's free
[5 day / 3 hour forecast](https://openweathermap.org/forecast5) endpoint (works
with a standard API key — no One Call subscription needed). The 3-hour slots are
aggregated into one entry per calendar day in the city's own timezone: daytime
headline condition, high/low, chance of precipitation, wind, humidity, and
rain/snow totals.

A JSON cache (`cache/openweather_posts.json`) accumulates history across scheduled
runs: past days are preserved as a record, while upcoming days are refreshed in
place as the forecast is revised. An entry's `updated` timestamp only changes
when its summary actually changes, so unchanged days don't churn the feed. The
API key is read from the `OPENWEATHER_API_KEY` environment variable (a GitHub
Actions secret in CI) and is never committed; `OPENWEATHER_LOCATION` and
`OPENWEATHER_UNITS` override the default location and units.

## About the Visual Crossing feed

A daily forecast feed for Chrzanów built from the
[Visual Crossing Timeline API](https://www.visualcrossing.com/resources/documentation/weather-api/timeline-weather-api/).
Unlike raw 3-hourly sources, this endpoint returns ready-made **daily**
aggregates (high/low, precip probability, wind, humidity, UV, sunrise/sunset),
and with `lang=pl` the `conditions` and `description` text comes back already
localized to Polish — so each entry reads naturally with no rollup on our side.
Weather **alerts** returned by the API are emitted as their own entries.

A JSON cache (`cache/visualcrossing_posts.json`) accumulates history across
scheduled runs: past days are preserved, upcoming days are refreshed in place, and
an entry's `updated` timestamp only changes when its summary changes, so
unchanged days don't churn the feed. The API key is read from the
`VISUALCROSSING_API_KEY` environment variable (a GitHub Actions secret in CI)
and is never committed; `VISUALCROSSING_LOCATION`, `VISUALCROSSING_UNITS`, and
`VISUALCROSSING_LANG` (default `pl`) override the defaults.

Note: Visual Crossing's free tier allows 1000 records/day. A forecast call here
costs ~1 record, so a run every 2 hours (~12/day) stays well within budget — but
adding `include=hours` raises the per-call cost.

## About the IMGW feed

A combined observations-and-warnings feed built from IMGW-PIB's open API
([danepubliczne.imgw.pl](https://danepubliczne.imgw.pl/)) — no API key needed.
Five sources go into one Atom feed: **synop** observations for one station
(default Kraków, `12566`) as one entry per day that accumulates the day's
hourly readings into a table; **hydro** water levels for nearby gauges
(default Smolice/Wisła and Jeleń/Przemsza); **meteo** telemetry for nearby
stations (default Chrzanów); and **meteo/hydro warnings** filtered to the
relevant area (meteo by TERYT powiat prefix, default `1203` — chrzanowski;
hydro by voivodeship, default małopolskie + śląskie).

Each source is fetched in isolation — one failing endpoint never blocks the
others — and the run only skips writing when *every* source comes back empty,
preserving the last good feed. A JSON cache (`cache/imgw_posts.json`)
accumulates history; an entry's `updated` timestamp only changes when its
content actually changes, so unchanged days don't churn the feed. Defaults are
overridable via `IMGW_SYNOP_ID`, `IMGW_HYDRO_IDS`, `IMGW_METEO_IDS`,
`IMGW_TERYT_PREFIXES`, and `IMGW_WOJEWODZTWA`.

## About the Open-Meteo feed

A keyless weather feed for one location (default Trzebinia) built from three
free [Open-Meteo](https://open-meteo.com/) APIs: the **forecast API** yields
one Polish-language entry per day (WMO condition, real and apparent
temperatures, precipitation, wind, UV, sunshine/daylight, sunrise/sunset,
CAPE), refreshed in place as the forecast is revised; the forecast `current`
block plus the **air-quality API** form one per-day "current conditions" entry
(European AQI, PM2.5/PM10, gases, pollen) refreshed with the latest reading;
and the **satellite radiation archive** adds one entry per completed past day
with the measured shortwave radiation sum and sunshine duration (the archive's
daily aggregates come back null for the satellite models, so hourly values are
aggregated per day in the generator; data lags ~1–2 days).

Each endpoint is fetched in isolation and the run only skips writing when
everything fails, preserving the last good feed. A JSON cache
(`cache/open_meteo_posts.json`) accumulates history; `updated` timestamps are
hash-gated so unchanged days don't churn. Location is overridable via
`OPEN_METEO_LAT`, `OPEN_METEO_LON`, `OPEN_METEO_PLACE`, and `OPEN_METEO_DAYS`.

## About the YouTube feed

`blog.youtube` ships a native RSS feed at `/rss/`, but it omits whole sections — Inside YouTube posts (the CEO's annual letter) and some News & Events articles never appear in it, and the Culture & Trends site (`youtube.com/trends`) has no feed at all. `youtube.py` merges three sources into one Atom feed: the native RSS, the blog's "Latest" page ItemList (each genuinely new URL is fetched once for its article metadata, gated by the cache so steady-state runs cost zero extra requests), and the Culture & Trends Discover cards (dateless articles get a stable fallback date so they never churn). Entries are deduplicated across sources by canonical URL or normalized title and tagged with their section via an Atom `<category>`.

## About the Sony feed

**One combined feed** from seven Sony sources: Sony Group press releases (the sony.co.jp news page is JS-rendered, but its data source is a hidden RSS at `assets_revamp2025/xml/en/rss_new.xml` — relative links are resolved and the `[Company]` title prefixes are lifted into descriptions), Sony Electronics US (native mediaroom RSS), SIE press releases (WordPress with feeds and the REST API disabled, so the listing cards are scraped), the PlayStation Blog (FeedBurner RSS), Sony Music PL and its Prowly newsroom (native RSS), and Sony PL community wallpapers (board RSS). Entries carry per-source `<category>` labels and are deduplicated across sources. Not sources, deliberately: www.sony.com, sony.pl/presscentre, sonymusic.com, and sonypictures.com all sit behind Akamai and return 403 to non-residential clients (including Chrome-impersonated requests); the sony.co.jp hidden RSS covers the same Sony Group press content as the blocked www.sony.com XML.

## About the Apple feed

**One combined feed** from Apple's news and developer-documentation surfaces: Apple Newsroom PL (native Atom), Apple Developer News and Developer Releases (native RSS, the latter carrying OS/Xcode/TestFlight build announcements), and the developer documentation site. The docs site is JS-rendered, but every page has a JSON twin under `/tutorials/data/documentation/<path>.json`; the topic indexes for Technotes and the iOS/iPadOS, macOS, and Safari release notes are read from there — newest 12 per topic, dated when first seen (doc pages carry no dates), with that timestamp preserved in the cache so newly published release notes surface at the top. Developer Account release notes are scraped from their dated `h5.rn-date` entries and keyed by a date fragment on the page URL. The Apple News Format release notes are a single prose page with no per-version subpages, so they are not an item source.

## About the Electronic Arts feed

**One combined feed** from four EA.com pages, none of which offer native RSS. EA News PL, EA Research & Technology, and EA Sports News PL are server-rendered `<ea-tile>` card listings — article tiles carry their date in `eyebrow-secondary-text` and their link in the embedded `<ea-cta>` (undated tiles are site navigation and are skipped; the Technology page's relative links are resolved against the page URL). The EA Sports FC 26 News PL page is a Next.js app, so items are read from the `__NEXT_DATA__` JSON blob (`props.pageProps.newsDataFallback.items` — title, summary, slug, publishingDate), with entry URLs built from the page URL plus the item slug. Entries carry per-source `<category>` labels and are deduplicated across sources.

## About the Reuters feed

Reuters discontinued its public RSS feeds in 2020, and `reuters.com` blocks
automated requests, so it can't be scraped directly. This feed instead pulls
recent Reuters articles from the Google News RSS proxy and republishes them as
a clean **Atom 1.0** feed. A small JSON cache (`cache/reuters_posts.json`) is
committed alongside the feed so article history accumulates across scheduled runs
rather than being limited to the latest fetch window.

Note: article links point to `news.google.com` redirect URLs (which resolve to
the original Reuters article) — an inherent trade-off of using the proxy.
