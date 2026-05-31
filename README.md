# RSS / Atom Feeds

Self-updating feeds for news sites that don't offer a usable native feed.
A GitHub Actions workflow regenerates every feed hourly and commits the result,
so the raw file URLs below always serve fresh content.

## Feeds

| Source | Feed |
| ------ | ---- |
| <img src="https://www.google.com/s2/favicons?domain=beatport.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Beatport Top 100](https://www.beatport.com/top-100) | [feed_beatport_top100.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_beatport_top100.xml) |
| <img src="https://www.google.com/s2/favicons?domain=viewbits.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Daily Digest](https://api.viewbits.com/) | [feed_daily_digest.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_daily_digest.xml) |
| <img src="https://www.google.com/s2/favicons?domain=openweathermap.org&sz=32" width="16" height="16" align="absmiddle" alt=""> [OpenWeather — Chrzanów](https://openweathermap.org/city/3093133) | [feed_openweather.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_openweather.xml) |
| <img src="https://www.google.com/s2/favicons?domain=reuters.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Reuters](https://www.reuters.com/) | [feed_reuters.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_reuters.xml) |
| <img src="https://www.google.com/s2/favicons?domain=visualcrossing.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Visual Crossing — Chrzanów](https://www.visualcrossing.com/) | [feed_visualcrossing.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_visualcrossing.xml) |
| [Trójka – Polskie Radio](https://trojka.polskieradio.pl/) | [feed_trojka.xml](https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_trojka.xml) |
| [Czwórka – Polskie Radio](https://www.polskieradio.pl/10,czworka) | [feed_czworka.xml](https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_czworka.xml) |

> Favicons are pulled live from Google's favicon service
> (`https://www.google.com/s2/favicons?domain=<host>`); no images are committed
> to the repo.

> In CI the `rel="self"` link inside each feed is filled in automatically from
> `GITHUB_REPOSITORY`, so it tracks the repo name without any manual edits.

### About the Beatport feed

Beatport's [Top 100](https://www.beatport.com/top-100) page is a Next.js app
with no native feed, but the full chart is embedded in the page's
`__NEXT_DATA__` JSON, so it can be read with a plain request (no browser
automation). Because the chart is a *ranking* rather than a stream, this feed
is framed as **tracks as they enter the Top 100**: each track is an entry keyed
by its Beatport URL and dated when first seen, with its debut rank kept in the
summary. A JSON cache (`cache/beatport_top100_posts.json`) accumulates history
across hourly runs and dedupes by track URL.

Beatport is behind Cloudflare, which fingerprints the TLS handshake and returns
HTTP 403 to plain `requests`. The generator uses `curl_cffi` (Chrome
impersonation) to fetch the page; if a run is blocked it skips writing so the
last good feed is preserved.

### About the Daily Digest feed

A single Atom feed that combines five small JSON APIs into one stream: the
ZenQuotes [quote of the day](https://zenquotes.io/api/today), and ViewBits'
[useless fact](https://api.viewbits.com/v1/uselessfacts?mode=today),
[life hack](https://api.viewbits.com/v1/lifehacks?mode=today),
[fortune cookie](https://api.viewbits.com/v1/fortunecookie?mode=today), and
[news headlines](https://api.viewbits.com/v1/headlines). Each source is fetched
independently, so one being down never sinks the run.

A JSON cache (`cache/daily_digest_posts.json`) accumulates history across hourly
runs and dedupes entries by `guid`. Headlines are keyed by article URL. The four
"today" endpoints expose only a single URL each (no per-day permalink), so they
are keyed by a synthetic `{kind}:{date}` guid dated to that day, while their
clickable link still points at the original source — re-runs within a day don't
churn the feed, but each new day's quote/fact/hack/fortune is added as a fresh
entry. The merged feed is capped at the newest 100 entries; if every source
fails, the run skips writing so the last good feed is preserved.

### About the OpenWeather feed

A daily forecast feed for Chrzanów built from OpenWeather's free
[5 day / 3 hour forecast](https://openweathermap.org/forecast5) endpoint (works
with a standard API key — no One Call subscription needed). The 3-hour slots are
aggregated into one entry per calendar day in the city's own timezone: daytime
headline condition, high/low, chance of precipitation, wind, humidity, and
rain/snow totals.

A JSON cache (`cache/openweather_posts.json`) accumulates history across hourly
runs: past days are preserved as a record, while upcoming days are refreshed in
place as the forecast is revised. An entry's `updated` timestamp only changes
when its summary actually changes, so unchanged days don't churn the feed. The
API key is read from the `OPENWEATHER_API_KEY` environment variable (a GitHub
Actions secret in CI) and is never committed; `OPENWEATHER_LOCATION` and
`OPENWEATHER_UNITS` override the default location and units.

### About the Visual Crossing feed

A daily forecast feed for Chrzanów built from the
[Visual Crossing Timeline API](https://www.visualcrossing.com/resources/documentation/weather-api/timeline-weather-api/).
Unlike raw 3-hourly sources, this endpoint returns ready-made **daily**
aggregates (high/low, precip probability, wind, humidity, UV, sunrise/sunset),
and with `lang=pl` the `conditions` and `description` text comes back already
localized to Polish — so each entry reads naturally with no rollup on our side.
Weather **alerts** returned by the API are emitted as their own entries.

A JSON cache (`cache/visualcrossing_posts.json`) accumulates history across
hourly runs: past days are preserved, upcoming days are refreshed in place, and
an entry's `updated` timestamp only changes when its summary changes, so
unchanged days don't churn the feed. The API key is read from the
`VISUALCROSSING_API_KEY` environment variable (a GitHub Actions secret in CI)
and is never committed; `VISUALCROSSING_LOCATION`, `VISUALCROSSING_UNITS`, and
`VISUALCROSSING_LANG` (default `pl`) override the defaults.

Note: Visual Crossing's free tier allows 1000 records/day. A forecast call here
costs ~1 record, so an hourly run (~24/day) stays well within budget — but
adding `include=hours` raises the per-call cost.

### About the Reuters feed

Reuters discontinued its public RSS feeds in 2020, and `reuters.com` blocks
automated requests, so it can't be scraped directly. This feed instead pulls
recent Reuters articles from the Google News RSS proxy and republishes them as
a clean **Atom 1.0** feed. A small JSON cache (`cache/reuters_posts.json`) is
committed alongside the feed so article history accumulates across hourly runs
rather than being limited to the latest fetch window.

Note: article links point to `news.google.com` redirect URLs (which resolve to
the original Reuters article) — an inherent trade-off of using the proxy.

## Local usage

Requires [uv](https://docs.astral.sh/uv/) (or plain Python + the deps in
`pyproject.toml`).

```bash
make install        # install dependencies
make feeds          # generate all feeds (incremental)
make feeds-full     # rebuild from scratch, ignoring the cache
make validate       # check every feed for content and freshness
```

Generated feeds are written to `feeds/feed_<name>.xml`.

## Adding another feed

1. Create `feed_generators/<name>.py` exposing `main(full: bool)` and writing
   to `feeds/feed_<name>.xml` (use `reuters_news.py` as a template).
2. Add an entry to `feeds.yaml`.
3. Optionally add a `feeds_<name>` Make target.
4. Add a row to the table above (with a favicon, as shown).

`run_all_feeds.py` reads `feeds.yaml`, so the hourly workflow picks up new
feeds automatically.

## Layout

```
.
├── .github/workflows/update-feeds.yml   # hourly generate + validate + commit
├── feeds.yaml                           # feed registry
├── feed_generators/
│   ├── reuters_news.py                  # Reuters -> Atom (via Google News proxy)
│   ├── openweather.py                   # OpenWeather -> Atom (daily forecast)
│   ├── visualcrossing.py                # Visual Crossing -> Atom (daily forecast, PL)
│   ├── run_all_feeds.py                 # runs every generator in feeds.yaml
│   ├── utils.py                         # shared helpers (HTTP, cache, feedgen)
│   └── validate_feeds.py                # RSS + Atom validation
├── feeds/                               # generated output
└── cache/                               # incremental dedupe state (committed)
```
