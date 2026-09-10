#!/usr/bin/env python3
"""Generate ``docs/sources.md`` — the per-feed list of concrete source links.

This used to carry a hand-written ``REGISTRY`` of every feed's sources, ~540
lines of it, kept in step with the generators by a drift warning. It drifted
anyway: it covered 69 of 92 feeds, and 14 of those entries listed one source for
a generator that had many. ``euronews`` was the worst — a single entry holding
the unformatted template ``...&level={level}&name={name}``, a URL that resolves
to nothing, while the generator actually pulls 14 real ones.

So the registry is gone and the generators are the source of truth. The old
docstring argued a registry was unavoidable because many generators build their
URLs procedurally (query strings, formatted templates, endpoints assembled in
code) and "a naive parse-the-SOURCES-list pass would silently drop those". That
is true of *AST parsing*, which is what the drift check did — and it is exactly
why the euronews template showed up verbatim. It is not true of *importing* the
module: import runs the construction, so ``.format()`` templates arrive fully
resolved. Every generator was checked to import cleanly with no side effects
(they define constants and functions; ``main()`` only runs under ``__main__``).
AST parsing stays as a fallback for a module that fails to import.

Display names come from each feed's own ``<title>``, so there is no third copy
of the naming to drift either — and they are consistently at or below the length
used in README.md ("AI-bridge" rather than "AI-bridge (combined AI sources)").

A new feed therefore needs no entry here at all: it appears with its full source
list as soon as it is in ``feeds.yaml``.

Run from the repository root:  ``uv run --locked feed_generators/docs_sources.py``
Add ``--check`` to report coverage without writing the file.
"""

import argparse
import ast
import contextlib
import importlib
import io
import sys
from pathlib import Path
from types import ModuleType
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from models import load_feed_registry
from utils import write_atomically

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # feedseek/
FEEDS_DIR = ROOT / "feeds"
OUT = ROOT / "docs" / "sources.md"
ATOM = "{http://www.w3.org/2005/Atom}"

# Generator module-level names that hold a list of (label, url[, cap]) tuples.
LIST_NAMES = ("SOURCES", "RSS_SOURCES", "NATIVE_FEEDS", "FEED_SOURCES")

# fmt: off
# grouping: feed_key order within each themed section
GROUPS = [
    ("🇵🇱 Polska — rząd i informacje", ["govpl_news", "pap", "tvp", "spidersweb"]),
    ("🌍 Świat — newsy", ["reuters", "euronews", "europa", "geopolitics"]),
    ("🤖 AI / LLM", ["anthropic", "claude", "openai", "xai", "aibridge", "skillsllm"]),
    ("💻 Tech / vendorzy oprogramowania", ["microsoft", "microsoft_updates", "redhat", "cloudflare", "docker", "gitlab", "github", "mozilla", "google", "apple", "sony", "lenovo", "canva", "youtube", "meta_newsroom", "saas", "hackerone", "creativecommons"]),
    ("🌦️ Pogoda", ["openweather", "visualcrossing", "open_meteo", "accuweather", "imgw"]),
    ("🎮 Gaming", ["steam", "ea", "bethesda", "nexusmods_news", "lichess"]),
    ("🚗 Motoryzacja", ["lexus_newsroom", "toyota_global"]),
    ("🏦 Bank", ["pekao"]),
    ("🚀 Kosmos / nauka / rząd USA", ["nasa", "esa", "usgov", "wikipedia_pl"]),
    ("🎵 Radio / muzyka", ["trojka", "czworka", "foobar2000_news", "ra", "beatport_top100", "audio", "audacity", "radios"]),
    ("😂 Rozrywka / memy", ["cheezburger", "memedroid", "9gag", "jbzd", "4chan"]),
    ("🛒 Ogłoszenia", ["olx"]),
    ("🧩 Userscripts", ["userscripts"]),
    ("📅 Codzienne", ["daily_digest", "daily_quote", "wotd", "datime"]),
]
# fmt: on


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------


def load_yaml_feeds() -> dict:
    """Enabled feed_key -> metadata from the canonical feeds.yaml loader.

    ``models.load_feed_registry`` owns registry parsing and validation. Keeping
    this consumer on the same path as the runner prevents malformed entries from
    being accepted here after the generator runner already rejected them.
    Disabled entries have no published artifact and therefore stay omitted.
    """
    registry = load_feed_registry()
    return {
        name: {"blog_url": config.blog_url, "script": config.script}
        for name, config in registry.items()
        if config.enabled
    }


def feed_title(feed_key: str) -> str:
    """The feed's own <title>, which is the shortest accurate name available."""
    path = FEEDS_DIR / f"feed_{feed_key}.xml"
    if not path.exists():
        return feed_key
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return feed_key
    # Atom puts <title> on the root; RSS nests it under <channel>.
    title = root.findtext(f"{ATOM}title") or root.findtext("channel/title") or ""
    return title.strip() or feed_key


# ---------------------------------------------------------------------------
# source extraction
# ---------------------------------------------------------------------------


def _label_for(url: str) -> str:
    """Readable label for a bare URL: host, plus a hint of what it selects.

    Google-News-backed generators differ only in the query string, so the host
    alone would render several identical-looking lines.
    """
    parts = urlparse(url)
    host = parts.netloc or url
    if parts.query:
        for field in ("q", "name", "domain"):
            marker = f"{field}="
            for chunk in parts.query.split("&"):
                if chunk.startswith(marker):
                    value = chunk[len(marker) :].replace("+", " ")
                    return f"{host} ({value})" if value else host
    tail = parts.path.strip("/").split("/")[-1]
    return f"{host} ({tail})" if tail and "." not in tail else host


def _pairs_from_value(value) -> list:
    """(label, url) pairs from a source list.

    Handles the shapes generators actually use: a plain list of URL strings
    (reuters, google, xai), and tuples where the URL is not always second -
    olx_group declares ``(label, category, url)`` and anthropic
    ``(label, url, base, prefix)``. Reading position 1 blindly meant olx's five
    feeds were silently dropped and the whole feed fell back to its blog_url.
    So the URL is whichever element first looks like one.
    """
    if not isinstance(value, (list, tuple)):
        return []
    pairs = []
    for item in value:
        if isinstance(item, str) and item.startswith("http"):
            pairs.append((_label_for(item), item))
            continue
        if not isinstance(item, (list, tuple)):
            # google and friends declare sources as dataclass instances rather
            # than tuples; a tuple-only reading reported google as one source.
            url = getattr(item, "url", None)
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                label = next(
                    (
                        value.strip()
                        for value in (getattr(item, field, None) for field in ("label", "name", "title", "key"))
                        if isinstance(value, str) and value.strip()
                    ),
                    "",
                )
                pairs.append((label or urlparse(url).netloc, url))
            continue
        strings = [element for element in item if isinstance(element, str)]
        url = next((s for s in strings if s.startswith(("http://", "https://"))), None)
        if not url:
            continue
        label = next(
            (s.strip() for s in strings if s.strip() and not s.startswith("http")), ""
        )
        pairs.append((label or urlparse(url).netloc, url))
    return pairs


# A SOURCES list is only half of how generators declare where they read from.
# The other half is a bare constant per scraper - geopolitics reaches ISW, CSIS
# and Carnegie through ISW_URL / CSIS_URL / CARNEGIE_API, and google reads five
# sites that appear nowhere in a list. Reading lists alone reported geopolitics
# as two sources and google as one, which is what made this document unreliable.
_NOT_A_SOURCE = (
    "ICON",
    "FAVICON",
    "LOGO",
    "AVATAR",
    "IMAGE",
    "AGENT",
    "HEADER",
    "REPO",
    "SCHEMA",
)
# Our own plumbing, which is never a source of entries. Scoped to this repo on
# purpose: raw.githubusercontent.com also hosts a third-party RSS mirror that
# meta_newsroom genuinely reads from.
_INFRA_HOSTS = (
    "raw.githubusercontent.com/trvny/feeds",
    "www.google.com/s2",
    "icons.duckduckgo.com",
)
# Stripped off the end of a constant name before it becomes a label.
_NAME_SUFFIXES = {"URL", "URLS", "API", "FEED", "FEEDS", "RSS", "ENDPOINT", "LINK", "PAGE"}


# Short tokens are usually acronyms worth keeping shouted (ISW, CSIS, GSA), but
# these are ordinary words that would look like screaming if left alone.
_NOT_ACRONYMS = {"BLOG", "NEWS", "HOME", "MAIN", "BASE", "SITE", "DOCS", "WIKI", "HOT", "TOP", "ALL"}


def _label_from_constant(name: str) -> str:
    """``ISW_URL`` -> ``ISW``; ``MESSAGE_CENTER_URL`` -> ``Message center``."""
    tokens = [token for token in name.split("_") if token]
    while len(tokens) > 1 and tokens[-1] in _NAME_SUFFIXES:
        tokens.pop()
    head = tokens[0]
    if len(head) > 4 or head in _NOT_ACRONYMS:
        head = head.capitalize()
    return " ".join([head] + [token.lower() for token in tokens[1:]])


def _url_constant_pairs(module) -> list:
    """(label, url) for module-level URL constants a scraper reads from.

    A templated constant is reduced to its origin, so Carnegie's
    ``/api/{collection}?limit=20`` is listed as ``carnegieendowment.org`` rather
    than as a literal ``{collection}`` - the exact mistake this document used to
    make with euronews. The origin rather than the path up to the placeholder,
    because half a URL usually 404s, and a line in this document should be
    something a reader can click and tools/check_sources.py can probe.
    """
    pairs = []
    for name in sorted(vars(module)):
        if name.startswith("_") or not name.isupper():
            continue
        if any(marker in name for marker in _NOT_A_SOURCE):
            continue
        value = getattr(module, name)
        if not isinstance(value, str) or not value.startswith(("http://", "https://")):
            continue
        url = value
        if "{" in url:
            parts = urlparse(url)
            url = f"{parts.scheme}://{parts.netloc}"
        if any(host in url for host in _INFRA_HOSTS):
            continue
        pairs.append((_label_from_constant(name), url))
    return pairs


def _hook_pairs(module) -> list:
    """Sources a generator builds in code and reports through ``doc_sources()``.

    Some generators cannot declare their sources as data: youtubs turns channel
    IDs into two feed URLs each, 4chan builds one endpoint per board. Guessing
    those from constants would be wrong, and hand-listing them here is what the
    deleted REGISTRY did - it drifted. So a generator with procedural sources
    exposes a ``doc_sources()`` that runs its own URL-building code; the answer
    cannot drift because it comes from the same function the generator uses.

    Must not touch the network, and is merged with whatever else is found
    rather than replacing it, so it only has to cover what data cannot.
    """
    hook = getattr(module, "doc_sources", None)
    if not callable(hook):
        return []
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            return _pairs_from_value(list(hook()))
    except Exception as exc:
        print(f"[warn] doc_sources() failed in {module.__name__}: {exc}", file=sys.stderr)
        return []


def _generator_modules(module) -> list:
    """Sibling generator modules this one composes on.

    anthropic is the shape that matters: it composes _anthropic_base and adds
    alignment/interpretability scrapers, so reading only its own globals would
    miss the base sources. FEED_NAME is what marks a module as a generator
    rather than shared plumbing like utils or multi_rss.
    """
    found, seen = [], set()
    for value in vars(module).values():
        candidate = value
        if not isinstance(candidate, ModuleType) and callable(candidate):
            # aibridge reuses groq's and perplexity's scrapers by importing the
            # functions, not the modules, so the module object is never bound
            # here - and its seven Groq/Perplexity sources went unlisted.
            candidate = sys.modules.get(getattr(candidate, "__module__", ""))
        if not isinstance(candidate, ModuleType) or candidate is module:
            continue
        path = getattr(candidate, "__file__", None)
        if not path or Path(path).parent != HERE or not hasattr(candidate, "FEED_NAME"):
            continue
        if candidate.__name__ not in seen:
            seen.add(candidate.__name__)
            found.append(candidate)
    return found


def sources_by_import(script: str) -> list:
    """Import the generator and read every source it resolves at module level.

    Import rather than AST-parse so procedurally built URLs (``.format()``
    templates, query strings assembled in code) arrive as the real thing.
    Generator output during import is swallowed: several call setup_logging()
    at module level and would otherwise scribble over this script's stdout.
    """
    module_name = script.removesuffix(".py")
    if not module_name:
        return []
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            module = importlib.import_module(module_name)
    except Exception as exc:  # a broken generator must not sink the whole doc
        print(f"[warn] could not import {script}: {exc}", file=sys.stderr)
        return []

    declared, loose = [], []
    for source in [module, *_generator_modules(module)]:
        declared += _hook_pairs(source)
        # Sorted attribute order keeps the rendered doc stable between runs.
        for attr in sorted(vars(source)):
            if attr.startswith("_") or not attr.isupper():
                continue
            declared += _pairs_from_value(getattr(source, attr))
        loose += _url_constant_pairs(source)

    # A constant that is merely the root another URL is built from (BASE, API_BASE,
    # MINIMAX_BASE_URL) is not a separate source; drop it when something longer
    # already covers it. Declared list entries are never dropped this way - a
    # generator that names a source means it.
    known = [url for _, url in declared + loose]
    loose = [
        (label, url)
        for label, url in loose
        if not any(other != url and other.startswith(url) for other in known)
    ]

    pairs, seen = [], set()
    for label, url in declared + loose:
        if url not in seen:
            seen.add(url)
            pairs.append((label, url))
    return pairs


def sources_by_ast(script: str) -> list:
    """Fallback for a module that will not import: static list literals only."""
    path = HERE / script
    if not path.exists():
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    urls, seen = [], set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id in LIST_NAMES for t in node.targets):
            continue
        for sub in ast.walk(node.value):
            if (
                isinstance(sub, ast.Constant)
                and isinstance(sub.value, str)
                and sub.value.startswith("http")
                and sub.value not in seen
            ):
                seen.add(sub.value)
                urls.append((urlparse(sub.value).netloc or sub.value, sub.value))
    return urls


def collect_sources(feed_key: str, cfg: dict) -> tuple:
    """Return (pairs, origin). Falls back to the feed's own site.

    A single-source scraper (czworka, jbzd, openweather, …) legitimately has
    nothing to list but the site it scrapes, so blog_url is the right answer
    rather than a gap.
    """
    script = cfg.get("script", "")
    pairs = sources_by_import(script)
    if pairs:
        return pairs, "generator"
    pairs = sources_by_ast(script)
    if pairs:
        return pairs, "ast"
    blog = cfg.get("blog_url", "")
    if blog:
        return [("Strona źródłowa", blog)], "blog_url"
    return [], "none"


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def fav(url: str) -> str:
    host = urlparse(url).netloc or url
    return f"![](https://www.google.com/s2/favicons?domain={host}&sz=16) "


def render_plan(yaml_feeds: dict) -> list:
    """[(group title, [feed_key, ...])] — grouped first, leftovers under Inne."""
    grouped = {k for _, keys in GROUPS for k in keys}
    plan = [(title, [k for k in keys if k in yaml_feeds]) for title, keys in GROUPS]
    extras = sorted(k for k in yaml_feeds if k not in grouped)
    if extras:
        plan.append(("🗂️ Inne", extras))
    return [(title, keys) for title, keys in plan if keys]


def build_markdown(yaml_feeds: dict, collected: dict) -> str:
    plan = render_plan(yaml_feeds)
    n_feeds = sum(len(keys) for _, keys in plan)
    n_sources = sum(len(collected[k][0]) for _, keys in plan for k in keys)

    out = ["# Źródła feedów\n"]
    out.append(
        "Konkretne linki źródłowe wchodzące w skład każdego generowanego feeda. "
        "Listy są czytane wprost z generatorów, a nazwy z `<title>` samych feedów, "
        "więc nic tu nie trzeba dopisywać ręcznie przy nowym feedzie. Feedy zbiorcze "
        "(`aibridge`, `saas`, `skillsllm`, `pap`, `esa`, `google` itd.) łączą wiele "
        "źródeł w jeden strumień Atom.\n"
    )
    out.append(
        "> Plik generowany: `uv run --locked feed_generators/docs_sources.py`. "
        "Nie edytuj ręcznie — zmień źródła w generatorze.\n"
    )
    if n_sources == 1:
        source_word = "źródło"
    elif n_sources % 10 in (2, 3, 4) and n_sources % 100 not in (12, 13, 14):
        source_word = "źródła"
    else:
        source_word = "źródeł"
    out.append(f"{n_feeds} feedów · {n_sources} {source_word}\n")

    out.append("## Spis grup\n")
    out.extend(f"- {title}" for title, _ in plan)
    out.append("")

    for title, keys in plan:
        out.append(f"## {title}\n")
        for key in keys:
            pairs, _ = collected[key]
            primary = pairs[0][1] if pairs else yaml_feeds[key].get("blog_url", "")
            out.append(f"### {fav(primary)}{feed_title(key)}")
            out.append(f"`{key}` · [feed_{key}.xml](../feeds/feed_{key}.xml)\n")
            for label, url in pairs:
                out.append(f"- {fav(url)}{label} — <{url}>")
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def coverage_report(yaml_feeds: dict, collected: dict) -> int:
    """Report feeds with nothing better than their blog_url. Not a failure:
    single-source scrapers are supposed to look like that."""
    fallbacks = sorted(k for k, (_, origin) in collected.items() if origin != "generator")
    empty = sorted(k for k, (pairs, _) in collected.items() if not pairs)
    print(f"{len(yaml_feeds)} feedów w feeds.yaml", file=sys.stderr)
    print(
        f"{len(yaml_feeds) - len(fallbacks)} z listą źródeł z generatora, "
        f"{len(fallbacks)} tylko z blog_url",
        file=sys.stderr,
    )
    if fallbacks:
        print(f"  blog_url: {', '.join(fallbacks)}", file=sys.stderr)
    if empty:
        print(f"[error] bez jakiegokolwiek źródła: {', '.join(empty)}", file=sys.stderr)
    return len(empty)


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate docs/sources.md")
    parser.add_argument(
        "--check", action="store_true", help="report coverage only, write nothing"
    )
    args = parser.parse_args()

    sys.path.insert(0, str(HERE))
    yaml_feeds = load_yaml_feeds()
    collected = {key: collect_sources(key, cfg) for key, cfg in yaml_feeds.items()}

    problems = coverage_report(yaml_feeds, collected)
    if args.check:
        return 1 if problems else 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" explicitly: the default translates to CRLF on Windows, so a
    # local run and a CI run would rewrite every line of a file that is
    # committed, burying the real change in whitespace churn.
    markdown = build_markdown(yaml_feeds, collected)
    write_atomically(
        OUT, lambda target: target.write_text(markdown, encoding="utf-8", newline="\n")
    )
    print(f"wrote {OUT}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
