# RSS / Atom Feed Generator (travino/feeds)

You add feeds to the **travino/feeds** project: a collection of Python generators that turn sites *without* a usable native feed into clean Atom (or RSS) files. A GitHub Actions workflow runs every generator hourly and commits the refreshed `feeds/feed_<name>.xml` and `cache/<name>_posts.json`, so the raw GitHub URLs always serve fresh content.

Your job is to add a new feed end-to-end: write the generator, register it, and verify it. The single most important thing to internalize before writing anything: **always read an existing generator first and copy its shape.** `feed_generators/reuters_news.py` is the canonical template; `feed_generators/beatport_top100.py` is the template for bot-protected / JavaScript-heavy sites. Consistency with these is more valuable than any individual cleverness, because the whole repo is built on shared `utils.py` helpers and a uniform `main(full)` contract.

## How the project fits together

```
.
├── .github/workflows/update-feeds.yml   # hourly: uv sync → run_all_feeds → validate → commit feeds+cache
├── feeds.yaml                           # the registry; pydantic-validated source of truth
├── Makefile                             # `make feeds`, `make feeds-full`, `make validate`, per-feed targets
├── pyproject.toml                       # deps (uv); Python >=3.11
├── feed_generators/
│   ├── reuters_news.py                  # TEMPLATE: Atom via Google News proxy + cache
│   ├── beatport_top100.py               # TEMPLATE: curl_cffi + __NEXT_DATA__ for a JS/Cloudflare site
│   ├── run_all_feeds.py                 # runs each generator (subprocess) per feeds.yaml
│   ├── models.py                        # pydantic FeedConfig / registry loader
│   ├── utils.py                         # shared HTTP, cache, feed-link, sort helpers
│   └── validate_feeds.py                # RSS + Atom validation (empty / stale checks)
├── feeds/feed_<name>.xml                # generated output (committed)
└── cache/<name>_posts.json              # incremental dedupe state (committed)
```

Key facts that shape everything below:

- **`run_all_feeds.py` reads `feeds.yaml` and runs each generator as a subprocess** (`uv run <script> [--full]`). So a generator must be runnable standalone and must exit non-zero on failure. New feeds are picked up automatically once they're in `feeds.yaml`.
- **There is no Selenium.** It isn't a dependency. `models.py` still defines a `selenium` enum value and `run_all_feeds.py` has `--skip-selenium` flags, but these are vestigial — every current feed is `type: requests`. JavaScript-heavy or bot-protected sites are handled *inside* a requests-type generator using the strategies in [Fetch strategies](#fetch-strategies), not by spinning up a browser.
- **Feeds are Atom by default** (via `feedgen`'s `fg.atom_file(...)`). `utils.save_rss_feed` exists for future RSS 2.0 feeds, but match the reference and emit Atom unless the user asks otherwise.
- **Never publish an empty feed.** If the fetch fails or yields zero entries, `main` returns `False` (→ exit 1) and writes nothing, so the last good committed feed is preserved. The hourly workflow treats an individual feed failure as non-fatal; only a malformed `feeds.yaml` fails the build.

## Workflow

### Step 0: Does a usable native feed already exist?

Scraping is a last resort — it's brittle and the repo only exists for sites *without* a usable feed. Before writing any code, rule out the easy wins.

**If the URL is a GitHub repo** (`https://github.com/{owner}/{repo}`): GitHub already serves Atom feeds. Don't write a generator. Just tell the user which native feed to point their reader at:
- Releases — `https://github.com/{owner}/{repo}/releases.atom`
- Tags — `https://github.com/{owner}/{repo}/tags.atom`
- Commits on a branch — `https://github.com/{owner}/{repo}/commits/{branch}.atom`

**Otherwise, probe for a native feed first.** Fetch the page and check `<head>` for `<link rel="alternate" type="application/rss+xml">` or `type="application/atom+xml"`, then try the common paths `/feed`, `/rss.xml`, `/atom.xml`, `/feed.xml`, `/rss`, `/blog/feed`. If one works, recommend that URL directly rather than building a generator. (See the snippet in [Troubleshooting](#troubleshooting).)

Only proceed to Step 1 when the site genuinely has no usable native feed.

### Step 1: Read the reference generators

Read these before writing anything — they define the shape you're copying:

```bash
cat feed_generators/reuters_news.py        # the canonical template
cat feed_generators/beatport_top100.py     # JS/Cloudflare template (curl_cffi + __NEXT_DATA__)
cat feed_generators/utils.py               # the helpers you must reuse
```

Study how they: structure imports and reuse `utils` helpers; define `FEED_NAME` / `BLOG_URL`; fetch with retries and degrade gracefully; parse dates; build the `feedgen` feed; merge with the JSON cache; and implement the `main(full)` + `--full` contract.

### Step 2: Pick a fetch strategy and inspect the source

Fetch the source and figure out where the content actually lives. Pick the lightest strategy that works (details in [Fetch strategies](#fetch-strategies)):

1. **Plain `requests`** (via `utils.fetch_page`) — the page HTML already contains the articles. Parse with BeautifulSoup. This is the default; reach for it first.
2. **Embedded JSON** — a Next.js / SPA page renders client-side but ships its data in a `<script id="__NEXT_DATA__">` blob (or similar). Fetch the HTML, pull the JSON out, walk it. No browser needed. (See `beatport_top100.py`.)
3. **A JSON / data API** — the site is backed by an API you can call directly (often cleaner than HTML). Check the network tab / known endpoints.
4. **`curl_cffi` (Chrome impersonation)** — the site sits behind Cloudflare or similar TLS fingerprinting and 403s plain `requests`. Use `curl_cffi.requests.get(url, impersonate="chrome")`. (See `beatport_top100.py`.)
5. **A news/aggregator proxy** — the site blocks automation outright and can't be fetched at all. Pull recent articles from the Google News RSS proxy and republish them. (See `reuters_news.py`.) Note the tradeoff: links point at the proxy's redirect URLs.

While inspecting, identify the per-item title, link (this is the dedupe key), date, and description, and what date formats appear.

### Step 3: Write the generator

Create `feed_generators/<name>.py`. Use a short, lowercase, underscore name matching the feed (e.g. `acme_blog.py`, `reuters_news.py`). The `script:` field in `feeds.yaml` is what actually binds the name, so just keep the filename, `FEED_NAME`, and output consistent. Follow [The generator contract](#the-generator-contract) exactly and lean on the reference file for your strategy.

Naming conventions:
- Script: `feed_generators/<name>.py`
- `FEED_NAME = "<name>"` at module level
- Output (handled by the helpers): `feeds/feed_<name>.xml`
- Cache (handled by the helpers): `cache/<name>_posts.json`

### Step 4: Register it in feeds.yaml

Add an entry under `feeds:`. `models.py` validates this with pydantic and **a `script_must_exist` check requires the file to already be on disk**, so write the generator (Step 3) before adding the entry.

```yaml
  acme:
    script: acme_blog.py
    type: requests          # always "requests" — there is no Selenium here
    blog_url: https://acme.com/blog
    enabled: true           # optional; defaults to true. Set false to park a feed.
```

`type` is `requests` for every feed regardless of which fetch strategy you used internally — curl_cffi, embedded JSON, and proxies are all still "requests" as far as the runner is concerned.

### Step 5: Add a Makefile target

Add a single per-feed convenience target to the root `Makefile`, matching the clean modern style (the `$(PY)` variable resolves to `uv run` or `python`). Don't reintroduce the older `$(call check_venv)` / `$(call print_info)` macros seen on a few legacy targets — those macros aren't defined in this Makefile and the targets that use them are broken.

```makefile
.PHONY: feeds_acme
feeds_acme: ## Generate only the Acme feed
	$(PY) feed_generators/acme_blog.py
```

You don't need to add a `_full` target — `make feeds-full` already runs every generator with `--full`. The per-feed target is just for quick local iteration on one feed.

### Step 6: Update the README

Add a row to the **Feeds** table (columns: Source | Feed), keeping it readable. The raw URL pattern is:

```markdown
| [Acme Blog](https://acme.com/blog) | [feed_acme.xml](https://raw.githubusercontent.com/travino/feeds/main/feeds/feed_acme.xml) |
```

The `rel="self"` link *inside* each feed is filled automatically from `GITHUB_REPOSITORY` in CI (or `RSS_REPO_SLUG` locally) via `utils.setup_feed_links`, so you never hardcode the slug in a generator — only in this README link. If you ruled the site out in Step 0 because it has a native feed, point the Feed column straight at that official URL instead.

### Step 7: Run and validate

```bash
# Run just this feed, standalone (incremental):
uv run feed_generators/acme_blog.py

# Full rebuild, ignoring the cache:
uv run feed_generators/acme_blog.py --full

# Via the runner, exactly as CI does it:
uv run feed_generators/run_all_feeds.py --feed=acme

# Validate every feed (empty-content + staleness checks):
uv run feed_generators/validate_feeds.py

# Or through make:
make feeds_acme
make validate
```

Inspect the output and confirm it looks right:

```bash
head -40 feeds/feed_acme.xml
ls -la cache/acme_posts.json
```

Before declaring done, walk this checklist:
- [ ] Generator runs standalone and exits 0; `--full` works too.
- [ ] On a fetch/parse failure it logs and returns `False` (writes nothing) rather than emitting an empty feed.
- [ ] Entries are deduped by `link` and sorted via `sort_posts_for_feed`.
- [ ] Per-item parsing is wrapped so one bad item is skipped, not fatal.
- [ ] `feeds.yaml` entry added with `type: requests` (and the script exists).
- [ ] `Makefile` target added in the clean `$(PY)` style.
- [ ] README row added with the correct `raw.githubusercontent.com/travino/feeds/main/...` URL.
- [ ] `validate_feeds.py` passes.

## The generator contract

Every generator is a standalone script that `run_all_feeds.py` invokes as a subprocess. Mirror this exact shape (condensed from `reuters_news.py`):

```python
import argparse
import sys

from utils import (
    deserialize_entries, load_cache, merge_entries, save_cache,
    setup_feed_links, setup_logging, sort_posts_for_feed,
)
from feedgen.feed import FeedGenerator

logger = setup_logging()

FEED_NAME = "acme"
BLOG_URL = "https://acme.com/blog"
MAX_ENTRIES = 100   # cap the committed XML at a sane size

def fetch_source(...):
    """Fetch with retries; return None on failure (never raise into main)."""

def parse_items(raw) -> list[dict]:
    """Return dicts with keys: title, link, date (tz-aware UTC or None), description.
    Wrap each item so one malformed item is skipped, not fatal."""

def generate_atom_feed(entries, feed_name=FEED_NAME):
    fg = FeedGenerator()
    fg.id(f"{BLOG_URL}#{feed_name}")
    fg.title("Acme Blog")
    fg.subtitle("...")
    setup_feed_links(fg, BLOG_URL, feed_name)   # sets rel=self (raw GitHub) + rel=alternate
    fg.language("en")
    fg.author({"name": "Acme"})
    for e in entries:
        fe = fg.add_entry()
        fe.id(e["link"]); fe.title(e["title"]); fe.link(href=e["link"])
        fe.description(e["description"])
        if e.get("date"):
            fe.published(e["date"]); fe.updated(e["date"])
    return fg

def save_atom_feed(fg, feed_name=FEED_NAME):
    from utils import get_feeds_dir
    out = get_feeds_dir() / f"feed_{feed_name}.xml"
    fg.atom_file(str(out), pretty=True)
    return out

def main(full=False) -> bool:
    raw = fetch_source()
    if raw is None:
        logger.error("Fetch failed — skipping write to preserve the last good feed")
        return False
    new_entries = parse_items(raw)
    if not new_entries:
        logger.warning("No entries parsed — skipping write to avoid an empty feed")
        return False

    cached = [] if full else deserialize_entries(load_cache(FEED_NAME).get("entries", []), date_field="date")
    merged = merge_entries(new_entries, cached, id_field="link", date_field="date")
    merged = sort_posts_for_feed(merged, date_field="date")
    if len(merged) > MAX_ENTRIES:
        merged = merged[-MAX_ENTRIES:]   # ascending order, so the tail is newest

    save_cache(FEED_NAME, merged)
    save_atom_feed(generate_atom_feed(merged))
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the Acme Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    args = parser.parse_args()
    sys.exit(0 if main(full=args.full) else 1)
```

Why this shape: returning `True`/`False` (not raising) lets the runner record a clean pass/fail per feed; the `--full` flag lets `make feeds-full` rebuild everything; the early `return False` on empty results is what protects the committed feed from being clobbered by a bad run.

## Shared helpers in utils.py

Reuse these rather than reinventing them — they encode the project's conventions:

- `setup_logging(name=None)` — call once at module top: `logger = setup_logging()`.
- `fetch_page(url, timeout=30, headers=None)` — plain GET with a browser User-Agent; raises on HTTP error.
- `sanitize_xml(text)` — strip control characters XML 1.0 forbids. Run titles/descriptions through this.
- `load_cache(feed_name)` → `{"last_updated", "entries": [...]}`; `save_cache(feed_name, entries)` writes `cache/<feed_name>_posts.json` (datetimes serialized to ISO).
- `deserialize_entries(entries, date_field="date")` — turn cached ISO strings back into datetimes after loading.
- `merge_entries(new, cached, id_field="link", date_field="date")` — append only unseen ids, then sort. This is the dedupe + accumulate step.
- `sort_posts_for_feed(posts, date_field="date")` — sorts **ascending (oldest first)** on purpose, because `feedgen` reverses on write so the published feed ends up newest-first. Keep the *tail* when capping to `MAX_ENTRIES`.
- `setup_feed_links(fg, blog_url, feed_name)` — sets `rel="self"` to the raw GitHub URL (built from the repo slug, so it's correct in CI automatically) and `rel="alternate"` to the source site. feedgen requires self before alternate.
- `stable_fallback_date(identifier)` — deterministic date for dateless items, so they don't churn every run.
- `save_rss_feed(fg, feed_name)` — RSS 2.0 writer, for when a feed should be RSS rather than Atom. There is no `save_atom_feed` in utils; define a tiny local one (as above) calling `fg.atom_file(...)`.

## Fetch strategies

| Situation | Strategy | Reference |
| --- | --- | --- |
| Articles in the served HTML | `utils.fetch_page` + BeautifulSoup | the `*_blog.py` generators (e.g. `trojka_blog.py`, `nexusmods_news_blog.py`) |
| Next.js / SPA, data in `__NEXT_DATA__` | fetch HTML, `json.loads` the `<script id="__NEXT_DATA__">`, walk the structure | `beatport_top100.py` |
| Clean backing JSON API | call the API directly with `requests` | `daily_digest.py`, `openweather.py`, `visualcrossing.py` |
| Cloudflare / TLS-fingerprint 403 | `curl_cffi.requests.get(url, impersonate="chrome")`, fall back to `fetch_page` if not installed | `beatport_top100.py` |
| Site blocks automation entirely | Google News RSS proxy, republish as Atom | `reuters_news.py` |

A couple of cross-cutting habits worth keeping: retry transient fetch failures with a small backoff and try alternate source URLs before giving up; and read secrets/locations from environment variables (the API-backed feeds use keys like `OPENWEATHER_API_KEY`, injected as Actions secrets in the workflow) rather than hardcoding them.

## Reference generators

- **`reuters_news.py`** — the canonical template. Fetches the Google News proxy with retries and multiple query variants, normalizes items, merges with cache, writes Atom, caps to `MAX_ENTRIES`. Start here for almost anything.
- **`beatport_top100.py`** — JS-heavy + Cloudflare. `curl_cffi` Chrome impersonation, `__NEXT_DATA__` JSON extraction, and a nice example of modeling a *ranking* as "items as they first appear" so a non-chronological source still maps onto a feed.
- **API-backed** (`daily_digest.py`, `openweather.py`, `visualcrossing.py`) — when the site has a usable JSON API and env-var config.
- **HTML scrapers** (`*_blog.py`: `trojka_blog.py`, `czworka_blog.py`, `nexusmods_news_blog.py`, `foobar2000_blog.py`, `jbzd_blog.py`) — straightforward `fetch_page` + BeautifulSoup parsing.

## Troubleshooting

**Native-feed probe (run in Step 0 before writing anything):**

```python
import requests
from bs4 import BeautifulSoup

def find_native_feed(url):
    soup = BeautifulSoup(requests.get(url, timeout=10).text, "html.parser")
    link = soup.find("link", rel="alternate",
                     type=lambda t: t and ("rss" in t or "atom" in t))
    if link and link.get("href"):
        return link["href"]
    for path in ("/feed", "/rss.xml", "/atom.xml", "/feed.xml", "/rss", "/blog/feed"):
        probe = requests.head(url.rstrip("/") + path, timeout=5, allow_redirects=True)
        if probe.status_code == 200:
            return url.rstrip("/") + path
    return None
```

**No items found** — the selectors don't match. Confirm the content is in the served HTML at all; if it's injected by JavaScript, switch to the `__NEXT_DATA__` / JSON-API strategy rather than trying harder with BeautifulSoup. Add debug logging of what your selectors actually match.

**HTTP 403 / blocked** — try a browser-like `User-Agent` first; if it's Cloudflare TLS fingerprinting, switch to `curl_cffi` with `impersonate="chrome"`; if the site blocks automation outright, fall back to the Google News proxy approach. On a block, return `False` and skip writing so the committed feed survives.

**Dates won't parse** — prefer `dateutil.parser.parse` (already a dependency), normalize to UTC with `pytz`, and fall back to `stable_fallback_date(link)` for genuinely dateless items so they don't reshuffle every hour.

**`feeds.yaml` entry rejected / feed skipped** — `models.py` validates each entry and the `script_must_exist` validator fails if the file isn't there yet. Make sure the generator file exists and the `script:` value matches its filename exactly.

**Empty or stale feed flagged by `validate_feeds.py`** — that's the guard working. An empty feed usually means a fetch failure slipped through and wrote anyway; make sure `main` returns `False` on zero entries. Stale (>60 days) usually means the source stopped publishing or the parser silently broke.
