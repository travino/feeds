# RSS / Atom Feeds

Self-updating feeds for news sites that don't offer a usable native feed.
A GitHub Actions workflow regenerates every feed hourly and commits the result,
so the raw file URLs below always serve fresh content.

## Feeds

| Source | Feed |
| ------ | ---- |
| [Beatport Top 100](https://www.beatport.com/top-100) | [feed_beatport_top100.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_beatport_top100.xml) |
| [Daily Digest](https://api.viewbits.com/) | [feed_daily_digest.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_daily_digest.xml) |
| [Reuters](https://www.reuters.com/) | [feed_reuters.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_reuters.xml) |
| [OpenWeather — Chrzanów](https://openweathermap.org/city/3093133) | [feed_openweather.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_openweather.xml) |

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
4. Add a row to the table above.

`run_all_feeds.py` reads `feeds.yaml`, so the hourly workflow picks up new
feeds automatically.

## Layout

```
.
├── .github/workflows/update-feeds.yml   # hourly generate + validate + commit
├── feeds.yaml                           # feed registry
├── feed_generators/
│   ├── reuters_news.py                  # Reuters -> Atom (via Google News proxy)
│   ├── run_all_feeds.py                 # runs every generator in feeds.yaml
│   ├── utils.py                         # shared helpers (HTTP, cache, feedgen)
│   └── validate_feeds.py                # RSS + Atom validation
├── feeds/                               # generated output
└── cache/                               # incremental dedupe state (committed)
```2. Add an entry to `feeds.yaml`.
3. Optionally add a `feeds_<name>` Make target.
4. Add a row to the table above.

`run_all_feeds.py` reads `feeds.yaml`, so the hourly workflow picks up new
feeds automatically.
