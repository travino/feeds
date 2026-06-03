# RSS / Atom Feeds

Self-updating feeds for news sites that don't offer a usable native feed.
A GitHub Actions workflow regenerates every feed hourly and commits the result,
so the raw file URLs below always serve fresh content.

Inspired by [Olshansk/rss-feeds](https://github.com/Olshansk/rss-feeds)

## Feeds

| Source | Feed |
| ------ | ---- |
| <img src="https://www.google.com/s2/favicons?domain=jbzd.com.pl&sz=32" width="16" height="16" align="absmiddle" alt=""> [Jbzd.com.pl](https://jbzd.com.pl/) | [feed_jbzd.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_jbzd.xml) |
| <img src="https://www.google.com/s2/favicons?domain=beatport.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Beatport Top 100](https://www.beatport.com/top-100) | [feed_beatport_top100.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_beatport_top100.xml) |
| <img src="https://icons.duckduckgo.com/ip3/ra.co.ico" width="16" height="16" align="absmiddle" alt=""> [RA (Resident Advisor)](https://ra.co/magazine) | [feed_ra.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_ra.xml) |
| <img src="https://icons.duckduckgo.com/ip3/viewbits.com.ico" width="16" height="16" align="absmiddle" alt=""> [Daily Digest](https://api.viewbits.com/) | [feed_daily_digest.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_daily_digest.xml) |
| <img src="https://www.google.com/s2/favicons?domain=foobar2000.org&sz=32" width="16" height="16" align="absmiddle" alt=""> [foobar2000](https://www.foobar2000.org/news) | [feed_foobar2000.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_foobar2000.xml) |
| <img src="https://www.google.com/s2/favicons?domain=gov.pl&sz=32" width="16" height="16" align="absmiddle" alt=""> [Gov.pl](https://www.gov.pl/) | [feed_govpl_news.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_govpl_news.xml) |
| <img src="https://www.google.com/s2/favicons?domain=nexusmods.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Nexus Mods News](https://www.nexusmods.com/news) | [feed_nexusmods_news.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_nexusmods_news.xml) |
| <img src="https://www.google.com/s2/favicons?domain=openweathermap.org&sz=32" width="16" height="16" align="absmiddle" alt=""> [OpenWeather](https://openweathermap.org/city/3093133) | [feed_openweather.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_openweather.xml) |
| <img src="https://www.google.com/s2/favicons?domain=visualcrossing.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Visual Crossing](https://www.visualcrossing.com/) | [feed_visualcrossing.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_visualcrossing.xml) |
| <img src="https://www.google.com/s2/favicons?domain=reuters.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Reuters](https://www.reuters.com/) | [feed_reuters.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_reuters.xml) |
| <img src="https://icons.duckduckgo.com/ip3/trojka.polskieradio.pl.ico" width="16" height="16" align="absmiddle" alt=""> [Polskie Radio – Trójka](https://trojka.polskieradio.pl/) | [feed_trojka.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_trojka.xml) |
| <img src="https://www.google.com/s2/favicons?domain=polskieradio.pl&sz=32" width="16" height="16" align="absmiddle" alt=""> [Polskie Radio – Czwórka](https://www.polskieradio.pl/10,czworka) | [feed_czworka.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_czworka.xml) |
|<img src="https://www.google.com/s2/favicons?domain=anthropic.com&sz=32" width="16" height="16" align="absmiddle" alt="">  [Anthropic](https://www.anthropic.com/) | [feed_anthropic.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_anthropic.xml) |
|<img src="https://www.google.com/s2/favicons?domain=claude.ai&sz=32" width="16" height="16" align="absmiddle" alt="">  [Claude](https://claude.com/blog) | [feed_claude.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_claude.xml) |
| <img src="https://www.google.com/s2/favicons?domain=microsoft.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Windows 11 Release notes](https://aka.ms/Windows11/25H2/UpdateHistory) | [feed_windows11_release_notes.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_windows11_release_notes.xml) |
| <img src="https://www.google.com/s2/favicons?domain=lexus.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Lexus Newsroom](https://pressroom.lexus.com/) | [feed_lexus_newsroom.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_lexus_newsroom.xml) |
| <img src="https://www.google.com/s2/favicons?domain=toyota.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Toyota Global](https://pressroom.toyota.com/) | [feed_toyota_global.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_toyota_global.xml) |
| <img src="https://www.google.com/s2/favicons?domain=meta.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Meta Newsroom](https://about.fb.com/news/) | [feed_meta_newsroom.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_meta_newsroom.xml) |

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

### About the RA feed

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
`cache/ra_posts.json` across hourly runs. If no section can be fetched the run
skips writing so the last good feed is preserved.

### About the Nexus Mods News feed

Nexus Mods has no native feed for its [news section](https://www.nexusmods.com/news)
and, like Beatport, sits behind Cloudflare (HTTP 403 to plain `requests`). The
listing is server-rendered, though, so no browser automation is needed: the
generator uses `curl_cffi` (Chrome impersonation) to clear the bot check and
parses the `div.tile-content` article cards for title, link, date, author,
category, and summary.

A JSON cache (`cache/nexusmods_news_posts.json`) accumulates history across
hourly runs and dedupes by article URL. Incremental runs fetch only page 1 and
merge; `make feeds_nexusmods_news_full` (or `--full`) walks several `?page=N`
pages to backfill the archive. If a run returns no articles it skips writing so
the last good feed is preserved.

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
