# RSS / Atom Feeds

Self-updating feeds for news sites that don't offer a usable native feed.
A GitHub Actions workflow regenerates every feed hourly and commits the result,
so the raw file URLs below always serve fresh content.

This repo starts with a single feed — **Reuters** — and is structured so more
can be added later.

## Feeds

| Source | Feed |
| ------ | ---- |
| [Reuters](https://www.reuters.com/) | [feed_reuters.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_reuters.xml) |

> In CI the `rel="self"` link inside each feed is filled in automatically from
> `GITHUB_REPOSITORY`, so it tracks the repo name without any manual edits.

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
