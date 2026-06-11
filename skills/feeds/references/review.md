# RSS Feed Review (travino/feeds)

Audit feed generators and their output for correctness, robustness, and project conventions.

## Instructions

1. **Scope** — all generators by default, or a named one.
2. **Read** the generator(s), their `feeds/feed_*.xml`, and `feed_generators/utils.py` (the shared helpers everything must reuse).
3. Resolve names via the `script:` field in `feeds.yaml` — filenames vary.
4. **Evaluate** against the checklists. Cite `file_path:line_number` for every finding.
5. If clean, say so briefly.

Context that drives the review: there is **no Selenium** here (don't flag its absence or expect driver handling); feeds are **Atom** by default (`fg.atom_file`); generators run as subprocesses via `run_all_feeds.py` and must expose `main(full=False) -> bool` + a `--full` flag.

## Generator review

### Parsing

- Selectors / JSON paths specific enough to survive minor redesigns, but not so brittle they pin to one generated class?
- Prefer semantic targets (`article`, `h2 a`, `__NEXT_DATA__` keys) over random hashed classnames where possible.
- Per-item parsing wrapped in `try/except` so one bad item is skipped, not fatal.

### Fetch & error handling

- `fetch_page` (or `curl_cffi`) called with a `timeout`; HTTP errors raised/checked.
- Transient failures retried with backoff; alternate source URLs tried before giving up (see `reuters_news.py`).
- Cloudflare/403 sites use `curl_cffi` with `impersonate="chrome"` and degrade if it's missing.
- **Empty guard**: `main` returns `False` (writing nothing) when fetch fails or zero entries parse — never overwrites the last good feed with an empty one.
- Returns `bool` and the `__main__` block does `sys.exit(0 if main(...) else 1)`.

### Feed links (convention)

Use `utils.setup_feed_links(fg, blog_url, feed_name)`. Flag any generator that sets links by hand. It must yield `rel="self"` **first** (the raw GitHub feed URL, built from the repo slug — never hardcoded) and `rel="alternate"` **last** (the source site). feedgen requires that order.

### Cache & dedupe

- Cache loaded before merge (or bypassed when `full=True`).
- New entries merged + deduped by `link` via `merge_entries`; ordered via `sort_posts_for_feed` (which sorts **ascending** on purpose — feedgen reverses on write, so output is newest-first; when capping to `MAX_ENTRIES`, keep the **tail**).
- Cache written to `cache/<feed_name>_posts.json` via `save_cache`; cached ISO dates restored with `deserialize_entries`.

### Strategy fit

Right fetch strategy for how the site serves content: plain `requests`+BeautifulSoup (HTML present), `__NEXT_DATA__`/JSON (SPA), direct JSON API, `curl_cffi` (bot-protected), or news proxy (blocks automation). Flag a heavy HTML scrape where a clean API or embedded JSON exists.

## XML output review

`validate_feeds.py` accepts both Atom (`<entry>`) and RSS (`<item>`); most feeds here are Atom.

### Structure

- **Atom**: `<feed>` has `<title>`, `<id>`, `<link rel="self">` (raw feed URL) and `<link rel="alternate">` (blog). Each `<entry>` has `<id>`, `<title>`, `<link>`, and `<updated>`/`<published>`.
- **RSS** (if `save_rss_feed` used): `<channel>` has `<title>`/`<link>`/`<description>`; each `<item>` has `<title>`/`<link>`/`<pubDate>`.

### Content

- 0 items → EMPTY (broken parser or a missing guard that let an empty write through).
- Newest item > 60 days → STALE (source dried up or parser silently broke).
- No duplicate `<link>`/`<id>` across entries.
- Dates parse (Atom ISO-8601 / RSS RFC-2822); titles non-empty.

### Encoding

- XML declares `encoding="utf-8"`; control chars stripped (`sanitize_xml`); entities escaped in titles/descriptions.

## Output

Per finding:

```
[SEVERITY] file_path:line_number — description
```

`ERROR` (broken/will fail) · `WARN` (fragile/convention) · `INFO` (suggestion).

End with:

| Feed | Generator | XML | Issues |
|------|-----------|-----|--------|
| name | OK/WARN/ERROR | OK/WARN/ERROR | brief note |
