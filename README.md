# travino/feeds

Generated syndication feeds for sites that don't publish their own.

## Feeds

| Source | Format | Feed |
| --- | --- | --- |
| [Jbzd.com.pl](https://jbzd.com.pl/) | Atom 1.0 | [feeds/feed_jbzd.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_jbzd.xml) |

## How it works

Jbzd.com.pl exposes no native RSS/Atom feed, so `feed_generators/jbzd_blog.py`
scrapes the homepage (a static, `requests` + BeautifulSoup site) and emits a
valid Atom 1.0 feed. Each entry carries the post title, permalink, publish time
(from each item's `data-date` attribute), categories, and an embedded preview
image.

The homepage only shows ~8 posts at a time. To retain more than one page of
history, each run merges newly scraped posts into a rolling JSON cache
(`feeds/.cache/jbzd.json`), deduped by post id, sorted newest-first, and capped
at 300 entries. The Atom feed is rebuilt from the full cache, so it accumulates
history across runs instead of being overwritten.

## Setup

```bash
pip install -r requirements.txt
```

## Regenerate

```bash
make feeds_jbzd            # incremental: merge new posts into the archive
make feeds_jbzd_full       # full reset: rebuild from the current page only
```

Equivalent direct calls:

```bash
python3 feed_generators/jbzd_blog.py          # incremental
python3 feed_generators/jbzd_blog.py --full   # reset cache
python3 feed_generators/jbzd_blog.py page.html  # build from a saved HTML file
```

Output is written to `feeds/feed_jbzd.xml`; history lives in
`feeds/.cache/jbzd.json`.

## Project layout

```
travino/
├── feed_generators/
│   └── jbzd_blog.py        # scraper + Atom builder + cache merge
├── feeds/
│   ├── feed_jbzd.xml       # generated Atom feed (rolling archive)
│   └── .cache/
│       └── jbzd.json       # entry cache — source of truth for history
├── feeds.yaml              # feed registry
├── Makefile                # make feeds_jbzd / feeds_jbzd_full
└── requirements.txt
```

## Scheduling

Run on a schedule to keep the archive growing — e.g. an hourly cron job or a
GitHub Actions workflow that runs `make feeds_jbzd` and commits the results.

> **Important for CI:** commit `feeds/.cache/jbzd.json` along with the feed.
> The cache is what carries history between runs; if it isn't persisted, each
> run starts from only the current homepage and the archive can't grow.

## Notes

- Entries are deduplicated by post id and sorted newest-first.
- A failure parsing any single post is logged and skipped — it never aborts the
  whole run.
- Re-running on an unchanged homepage is a no-op (0 new entries).
- Adjust `MAX_ENTRIES` in `jbzd_blog.py` (and `max_entries` in `feeds.yaml`) to
  change how much history is retained.
