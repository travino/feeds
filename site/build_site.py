#!/usr/bin/env python3
"""Build a static GitHub Pages site from the generated feeds.

Scans ``feeds/feed_*.xml``, reads each Atom feed's metadata, and writes a
self-contained ``public/`` directory containing:

  * ``index.html``   - human landing page + feed autodiscovery <link> tags
  * the feed XML files (copied, so they serve as application/xml on Pages)
  * ``sitemap.xml``  - for search engines
  * ``robots.txt``   - allows crawling, points at the sitemap
  * ``.nojekyll``    - stop GitHub Pages running the files through Jekyll

Pure standard library: no extra dependencies, so the deploy job can run it
with plain ``python3`` without ``uv sync``.

The site base URL is taken from ``$SITE_URL`` (set by actions/configure-pages),
falling back to ``$GITHUB_REPOSITORY`` (``owner/repo`` -> Pages URL), and
finally to the travino/feeds default for local runs.
"""

from __future__ import annotations

import html
import os
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ATOM = "{http://www.w3.org/2005/Atom}"

# Repo root (this script lives in site/).
ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = Path(__file__).resolve().parent
FEEDS_DIR = ROOT / "feeds"
OUT_DIR = ROOT / "public"
SELECTION_FILE = SITE_DIR / "published_feeds.txt"


def site_base_url() -> str:
    """Resolve the published base URL, always with a single trailing slash."""
    explicit = os.environ.get("SITE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/") + "/"

    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner}.github.io/{name}/"

    return "https://travino.github.io/feeds/"


def _text(elem: ET.Element | None) -> str:
    return (elem.text or "").strip() if elem is not None else ""


def parse_feed(path: Path) -> dict:
    """Extract display metadata from an Atom or RSS 2.0 feed file."""
    info = {
        "filename": path.name,
        "title": path.stem.replace("feed_", "").replace("_", " ").title(),
        "subtitle": "",
        "source": "",
        "author": "",
        "updated": None,
        "entries": 0,
        "format": "atom",
    }
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return info

    if root.tag == "rss":
        info["format"] = "rss"
        ch = root.find("channel")
        if ch is None:
            return info
        if _text(ch.find("title")):
            info["title"] = _text(ch.find("title"))
        info["subtitle"] = _text(ch.find("description"))
        info["source"] = _text(ch.find("link"))
        items = ch.findall("item")
        info["entries"] = len(items)
        dates = []
        for el in [ch.find("lastBuildDate"), ch.find("pubDate")] + [
            it.find("pubDate") for it in items
        ]:
            if el is not None and _text(el):
                try:
                    dates.append(parsedate_to_datetime(_text(el)))
                except (TypeError, ValueError):
                    pass
        if dates:
            dt = max(dates)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            info["updated"] = dt.astimezone(timezone.utc)
        return info

    if _text(root.find(f"{ATOM}title")):
        info["title"] = _text(root.find(f"{ATOM}title"))
    info["subtitle"] = _text(root.find(f"{ATOM}subtitle"))
    info["author"] = _text(root.find(f"{ATOM}author/{ATOM}name"))

    for link in root.findall(f"{ATOM}link"):
        if link.get("rel") == "alternate" and link.get("href"):
            info["source"] = link.get("href")
            break

    updated = _text(root.find(f"{ATOM}updated"))
    if updated:
        try:
            dt = datetime.fromisoformat(updated)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            info["updated"] = dt.astimezone(timezone.utc)
        except ValueError:
            pass

    info["entries"] = len(root.findall(f"{ATOM}entry"))
    return info


def domain_of(url: str) -> str:
    if not url:
        return ""
    host = url.split("//", 1)[-1].split("/", 1)[0]
    return host[4:] if host.startswith("www.") else host


def relative_time(dt: datetime | None) -> str:
    if dt is None:
        return "unknown"
    delta = datetime.now(timezone.utc) - dt
    secs = int(delta.total_seconds())
    if secs < 0:
        return "just now"
    if secs < 3600:
        m = secs // 60
        return "just now" if m < 1 else f"{m} min ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    days = secs // 86400
    return "1 day ago" if days == 1 else f"{days} days ago"


def short_name(path: Path) -> str:
    """feeds/feed_reuters.xml -> 'reuters' (the editable key in the allowlist)."""
    stem = path.stem
    return stem[len("feed_"):] if stem.startswith("feed_") else stem


def load_selection() -> list[tuple[str, str]] | None:
    """Read published_feeds.txt -> ordered [(name, title_override)].

    Returns None when the file is absent, meaning "publish every feed".
    Each line is a feed short name, optionally with a custom title after a '|':

        reuters
        beatport_top100 | Beatport — Top 100

    Blank lines and lines starting with '#' are ignored.
    """
    if not SELECTION_FILE.exists():
        return None
    selection: list[tuple[str, str]] = []
    for raw in SELECTION_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, _, override = line.partition("|")
        selection.append((name.strip(), override.strip()))
    return selection


def collect_feeds() -> list[dict]:
    available = {short_name(p): p for p in FEEDS_DIR.glob("feed_*.xml")}
    selection = load_selection()

    if selection is None:
        feeds = [parse_feed(p) for p in available.values()]
        feeds.sort(key=lambda f: f["title"].lower())
        return feeds

    feeds = []
    for name, override in selection:
        path = available.get(name)
        if path is None:
            print(f"  ! published_feeds.txt lists '{name}' but feeds/feed_{name}.xml is missing — skipping")
            continue
        info = parse_feed(path)
        if override:
            info["title"] = override
        feeds.append(info)
    return feeds


def render_card(feed: dict, base: str) -> str:
    url = base + feed["filename"]
    dom = domain_of(feed["source"])
    title = html.escape(feed["title"])
    subtitle = html.escape(feed["subtitle"]) or "&nbsp;"
    source_attr = html.escape(feed["source"], quote=True)
    favicon = (
        f"https://www.google.com/s2/favicons?domain={html.escape(dom, quote=True)}&sz=64"
        if dom
        else ""
    )
    icon = (
        f'<img class="fav" src="{favicon}" alt="" loading="lazy" width="20" height="20">'
        if favicon
        else '<span class="fav fav--blank"></span>'
    )
    meta = f'{feed["entries"]} entries · updated {html.escape(relative_time(feed["updated"]))}'
    source_link = (
        f'<a class="src" href="{source_attr}" target="_blank" rel="noopener">{html.escape(dom)} ↗</a>'
        if feed["source"]
        else ""
    )

    return f"""      <article class="card" data-search="{html.escape((feed['title'] + ' ' + dom).lower(), quote=True)}">
        <header class="card__head">
          {icon}
          <div class="card__titles">
            <h2 class="card__title">{title}</h2>
            {source_link}
          </div>
        </header>
        <p class="card__sub">{subtitle}</p>
        <footer class="card__foot">
          <span class="card__meta">{meta}</span>
          <span class="card__actions">
            <a class="btn" href="{html.escape(url, quote=True)}">Subscribe</a>
            <button class="btn btn--ghost" type="button" data-copy="{html.escape(url, quote=True)}">Copy URL</button>
          </span>
        </footer>
      </article>"""


def render_autodiscovery(feeds: list[dict], base: str) -> str:
    lines = []
    for f in feeds:
        href = html.escape(base + f["filename"], quote=True)
        title = html.escape(f["title"], quote=True)
        mime = "application/rss+xml" if f.get("format") == "rss" else "application/atom+xml"
        lines.append(
            f'  <link rel="alternate" type="{mime}" '
            f'title="{title}" href="{href}">'
        )
    return "\n".join(lines)


def build_index(feeds: list[dict], base: str) -> str:
    count = len(feeds)
    cards = "\n".join(render_card(f, base) for f in feeds)
    autodiscovery = render_autodiscovery(feeds, base)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    desc = (
        f"{count} self-updating Atom feeds for sites that don't offer a usable "
        "native feed — news, music, automotive, gaming and more, regenerated every 2 hours."
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Feeds — self-updating Atom feeds</title>
  <meta name="description" content="{html.escape(desc, quote=True)}">
  <link rel="canonical" href="{html.escape(base, quote=True)}">
  <meta property="og:type" content="website">
  <meta property="og:title" content="Feeds — self-updating Atom feeds">
  <meta property="og:description" content="{html.escape(desc, quote=True)}">
  <meta property="og:url" content="{html.escape(base, quote=True)}">
  <meta name="twitter:card" content="summary">
{autodiscovery}
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,600;0,9..144,900;1,9..144,500&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {{
      --paper: #f3efe6;
      --paper-2: #ece6d8;
      --ink: #1d1916;
      --ink-soft: #5b524a;
      --accent: #d8412f;
      --accent-deep: #a52c1f;
      --line: #d8d0bf;
      --card: #fbf8f1;
      --radius: 4px;
    }}
    * {{ box-sizing: border-box; }}
    html {{ -webkit-text-size-adjust: 100%; }}
    body {{
      margin: 0;
      background: var(--paper);
      background-image:
        radial-gradient(circle at 12% 18%, rgba(216,65,47,.06), transparent 40%),
        radial-gradient(circle at 88% 8%, rgba(29,25,22,.05), transparent 38%);
      color: var(--ink);
      font-family: "Fraunces", Georgia, serif;
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }}
    .wrap {{ max-width: 1080px; margin: 0 auto; padding: clamp(28px, 6vw, 72px) clamp(20px, 5vw, 56px) 80px; }}

    .kicker {{
      font-family: "IBM Plex Mono", monospace;
      font-size: 12px; letter-spacing: .18em; text-transform: uppercase;
      color: var(--accent-deep); margin: 0 0 18px;
      display: flex; align-items: center; gap: 10px;
    }}
    .kicker::before {{ content: ""; width: 34px; height: 2px; background: var(--accent); display: inline-block; }}

    h1 {{
      font-family: "Fraunces", serif; font-weight: 900;
      font-size: clamp(48px, 11vw, 116px); line-height: .92;
      letter-spacing: -.02em; margin: 0; font-optical-sizing: auto;
    }}
    h1 em {{ font-style: italic; color: var(--accent); font-weight: 500; }}
    .lede {{
      max-width: 56ch; margin: 22px 0 0; font-size: clamp(16px, 2.2vw, 20px);
      color: var(--ink-soft);
    }}

    .toolbar {{
      display: flex; flex-wrap: wrap; align-items: baseline; gap: 14px 22px;
      margin: 40px 0 26px; padding-bottom: 18px; border-bottom: 2px solid var(--ink);
    }}
    .count {{ font-family: "IBM Plex Mono", monospace; font-size: 13px; letter-spacing: .04em; color: var(--ink-soft); }}
    .count b {{ color: var(--ink); }}
    .search {{
      margin-left: auto; flex: 1 1 240px; max-width: 340px;
      font-family: "IBM Plex Mono", monospace; font-size: 14px;
      padding: 9px 14px; border: 1.5px solid var(--line); border-radius: var(--radius);
      background: var(--card); color: var(--ink); outline: none; transition: border-color .15s;
    }}
    .search:focus {{ border-color: var(--accent); }}
    .search::placeholder {{ color: #a59a8c; }}

    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }}

    .card {{
      background: var(--card); border: 1px solid var(--line); border-radius: var(--radius);
      padding: 20px 20px 16px; display: flex; flex-direction: column; gap: 12px;
      position: relative; transition: transform .14s ease, box-shadow .14s ease, border-color .14s;
    }}
    .card:hover {{ transform: translateY(-2px); box-shadow: 6px 6px 0 rgba(29,25,22,.08); border-color: var(--ink); }}
    .card__head {{ display: flex; gap: 12px; align-items: flex-start; }}
    .fav {{ border-radius: 4px; flex: none; margin-top: 4px; background: var(--paper-2); }}
    .fav--blank {{ width: 20px; height: 20px; display: inline-block; }}
    .card__titles {{ min-width: 0; }}
    .card__title {{ font-size: 21px; font-weight: 600; line-height: 1.12; margin: 0; letter-spacing: -.01em; }}
    .src {{
      font-family: "IBM Plex Mono", monospace; font-size: 11.5px; letter-spacing: .02em;
      color: var(--ink-soft); text-decoration: none; word-break: break-all;
    }}
    .src:hover {{ color: var(--accent); }}
    .card__sub {{ margin: 0; font-size: 15px; color: var(--ink-soft); flex: 1; }}
    .card__foot {{
      display: flex; flex-wrap: wrap; align-items: center; gap: 10px;
      margin-top: 2px; padding-top: 13px; border-top: 1px dashed var(--line);
    }}
    .card__meta {{ font-family: "IBM Plex Mono", monospace; font-size: 11px; color: var(--ink-soft); letter-spacing: .02em; }}
    .card__actions {{ margin-left: auto; display: flex; gap: 8px; }}
    .btn {{
      font-family: "IBM Plex Mono", monospace; font-size: 12px; font-weight: 500;
      padding: 6px 12px; border-radius: var(--radius); text-decoration: none; cursor: pointer;
      border: 1.5px solid var(--accent); background: var(--accent); color: #fff; transition: .14s;
    }}
    .btn:hover {{ background: var(--accent-deep); border-color: var(--accent-deep); }}
    .btn--ghost {{ background: transparent; color: var(--accent-deep); }}
    .btn--ghost:hover {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
    .btn--ghost.copied {{ background: var(--ink); border-color: var(--ink); color: #fff; }}

    .empty {{ font-family: "IBM Plex Mono", monospace; color: var(--ink-soft); padding: 40px 0; }}

    footer.site {{
      margin-top: 56px; padding-top: 22px; border-top: 2px solid var(--ink);
      font-family: "IBM Plex Mono", monospace; font-size: 12.5px; color: var(--ink-soft);
      display: flex; flex-wrap: wrap; gap: 8px 18px; justify-content: space-between;
    }}
    footer.site a {{ color: var(--accent-deep); text-decoration: none; }}
    footer.site a:hover {{ text-decoration: underline; }}

    @media (max-width: 520px) {{
      .toolbar {{ flex-direction: column; align-items: stretch; }}
      .search {{ margin-left: 0; max-width: none; }}
      .card__actions {{ margin-left: 0; }}
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <p class="kicker">Auto-generated · rebuilt every 2 hours</p>
    <h1>Feeds<em>.</em></h1>
    <p class="lede">{html.escape(desc)}</p>

    <div class="toolbar">
      <span class="count"><b id="shown">{count}</b> / {count} feeds</span>
      <input id="search" class="search" type="search" placeholder="filter feeds…" autocomplete="off" aria-label="Filter feeds">
    </div>

    <section class="grid" id="grid">
{cards}
    </section>
    <p class="empty" id="empty" hidden>No feeds match that filter.</p>

    <footer class="site">
      <span>Last build: {now}</span>
      <span>Source &amp; how it works · <a href="https://github.com/travino/feeds">github.com/travino/feeds</a></span>
    </footer>
  </main>

  <script>
    const search = document.getElementById('search');
    const cards = Array.from(document.querySelectorAll('.card'));
    const shown = document.getElementById('shown');
    const empty = document.getElementById('empty');
    search.addEventListener('input', () => {{
      const q = search.value.trim().toLowerCase();
      let n = 0;
      cards.forEach(c => {{
        const hit = !q || c.dataset.search.includes(q);
        c.hidden = !hit;
        if (hit) n++;
      }});
      shown.textContent = n;
      empty.hidden = n !== 0;
    }});
    document.addEventListener('click', async (e) => {{
      const btn = e.target.closest('[data-copy]');
      if (!btn) return;
      try {{
        await navigator.clipboard.writeText(btn.dataset.copy);
        const old = btn.textContent;
        btn.textContent = 'Copied ✓';
        btn.classList.add('copied');
        setTimeout(() => {{ btn.textContent = old; btn.classList.remove('copied'); }}, 1400);
      }} catch (_) {{ window.prompt('Copy this feed URL:', btn.dataset.copy); }}
    }});
  </script>
</body>
</html>
"""


def build_sitemap(feeds: list[dict], base: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    urls = [f"  <url><loc>{html.escape(base)}</loc><lastmod>{today}</lastmod></url>"]
    for f in feeds:
        lastmod = (f["updated"] or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
        urls.append(
            f"  <url><loc>{html.escape(base + f['filename'])}</loc>"
            f"<lastmod>{lastmod}</lastmod></url>"
        )
    body = "\n".join(urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n"
        "</urlset>\n"
    )


def build_robots(base: str) -> str:
    return f"User-agent: *\nAllow: /\nSitemap: {base}sitemap.xml\n"


def main() -> None:
    base = site_base_url()
    feeds = collect_feeds()
    if not feeds:
        raise SystemExit("No feeds found in feeds/ — nothing to publish.")

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)

    for f in feeds:
        shutil.copy2(FEEDS_DIR / f["filename"], OUT_DIR / f["filename"])

    (OUT_DIR / "index.html").write_text(build_index(feeds, base), encoding="utf-8")
    (OUT_DIR / "sitemap.xml").write_text(build_sitemap(feeds, base), encoding="utf-8")
    (OUT_DIR / "robots.txt").write_text(build_robots(base), encoding="utf-8")
    (OUT_DIR / ".nojekyll").write_text("", encoding="utf-8")

    print(f"Built {len(feeds)} feeds into {OUT_DIR}/ (base: {base})")


if __name__ == "__main__":
    main()
