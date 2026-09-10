#!/usr/bin/env python3
"""Build a compact recent-entry index for Feedseek's remote MCP search tool."""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "feed_generators"))

from models import load_feed_registry  # noqa: E402

FEEDS_DIR = ROOT / "feeds"
OUT_PATH = ROOT / "public" / "feedseek-search-index.json"
WINDOW_DAYS = 14
MAX_ITEMS = 5000
MIN_ITEMS_PER_FEED = 5
MAX_UNDATED_PER_FEED = 5
SUMMARY_CHARS = 800


class _HTMLTextExtractor(HTMLParser):
    """Small stdlib HTML-to-text converter for feed summaries."""

    BLOCK_TAGS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
    SKIP_TAGS = {"script", "style", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        name = tag.lower()
        if name in self.SKIP_TAGS:
            self.skip_depth += 1
            return
        if not self.skip_depth and name in self.BLOCK_TAGS:
            self.parts.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() in self.SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name in self.SKIP_TAGS:
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if not self.skip_depth and name in self.BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)


def parse_date(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compact_text(value: object, limit: int = SUMMARY_CHARS) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def html_to_text(value: object) -> str:
    if not isinstance(value, str) or not value:
        return ""
    parser = _HTMLTextExtractor()
    parser.feed(value)
    parser.close()
    return " ".join("".join(parser.parts).split())


def entry_text(item: dict) -> str:
    content_text = item.get("content_text")
    if isinstance(content_text, str) and content_text.strip():
        return " ".join(content_text.split())

    content_html = item.get("content_html")
    if isinstance(content_html, str) and content_html.strip():
        return html_to_text(content_html)

    summary = item.get("summary")
    return " ".join(summary.split()) if isinstance(summary, str) else ""


def entry_summary(item: dict) -> str:
    summary = item.get("summary")
    if isinstance(summary, str) and summary.strip():
        return compact_text(summary)
    return compact_text(entry_text(item))


def canonical_url(item: dict) -> str:
    """Return a truthful HTTP(S) citation target or an empty string."""
    for field in ("url", "external_url"):
        candidate = item.get(field)
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        parsed = urlparse(candidate)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return candidate
    return ""


def encode_id(feed_key: str, item_id: str, revision: str) -> str:
    token = (
        base64.urlsafe_b64encode(item_id.encode("utf-8")).decode("ascii").rstrip("=")
    )
    return f"{revision}.{feed_key}:{token}"


def item_date(item: dict) -> datetime | None:
    dates = [
        value
        for value in (
            parse_date(item.get("date_published")),
            parse_date(item.get("date_modified")),
        )
        if value is not None
    ]
    return max(dates) if dates else None


def load_feed(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read valid JSON Feed from {path}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError(f"Invalid JSON Feed structure in {path}")
    return data


def enabled_feed_paths() -> tuple[list[Path], list[str]]:
    registry = load_feed_registry()
    paths: list[Path] = []
    missing: list[str] = []
    for key, config in registry.items():
        if not config.enabled:
            continue
        path = FEEDS_DIR / f"feed_{key}.json"
        if path.is_file():
            paths.append(path)
        else:
            missing.append(key)
    return paths, missing


def resolve_revision() -> str:
    explicit = os.environ.get("FEEDSEEK_REVISION", "").strip()
    if explicit:
        revision = explicit
    else:
        git = shutil.which("git")
        if not git:
            revision = ""
        else:
            try:
                revision = subprocess.check_output(
                    [git, "rev-parse", "HEAD"],
                    cwd=ROOT,
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip()
            except (OSError, subprocess.CalledProcessError):
                revision = ""

    if len(revision) != 40 or any(
        char not in "0123456789abcdefABCDEF" for char in revision
    ):
        raise ValueError(
            "Feedseek MCP index requires an exact 40-character Git commit SHA"
        )
    return revision.lower()


def _select_entries(
    entries: list[tuple[datetime | None, str, dict]],
) -> tuple[list[tuple[datetime | None, str, dict]], bool, int | None]:
    """Cap the index while preserving a small slice of each active source."""
    if len(entries) <= MAX_ITEMS:
        return entries, False, None

    sources = {source for _, source, _ in entries}
    floor = MIN_ITEMS_PER_FEED if len(sources) * MIN_ITEMS_PER_FEED <= MAX_ITEMS else 1
    selected: set[int] = set()
    counts: dict[str, int] = {}

    if len(sources) <= MAX_ITEMS:
        for index, (_, source, _) in enumerate(entries):
            if counts.get(source, 0) >= floor:
                continue
            selected.add(index)
            counts[source] = counts.get(source, 0) + 1

    for index in range(len(entries)):
        if len(selected) >= MAX_ITEMS:
            break
        selected.add(index)

    retained = [entry for index, entry in enumerate(entries) if index in selected]
    first_omitted = next(
        (index for index in range(len(entries)) if index not in selected),
        None,
    )
    return retained, True, first_omitted


def _complete_coverage_boundary(
    entries: list[tuple[datetime | None, str, dict]],
    first_omitted: int | None,
    cutoff: datetime,
    now: datetime,
) -> datetime:
    """Return the oldest timestamp from which every dated candidate is retained."""
    if first_omitted is None:
        return cutoff
    omitted_date = entries[first_omitted][0]
    if omitted_date is None:
        return cutoff

    for index in range(first_omitted - 1, -1, -1):
        candidate = entries[index][0]
        if candidate is not None and candidate > omitted_date:
            return candidate
    return now


def build_index(
    feed_paths: list[Path],
    now: datetime | None = None,
    revision: str = "0" * 40,
    missing_feed_keys: list[str] | None = None,
) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = now - timedelta(days=WINDOW_DAYS)
    entries: list[tuple[datetime | None, str, dict]] = []
    skipped_feeds = [
        {"source_key": key, "reason": "missing_artifact"}
        for key in sorted(missing_feed_keys or [])
    ]
    feed_count = 0

    for path in sorted(feed_paths):
        key = path.stem.removeprefix("feed_")
        try:
            feed = load_feed(path)
        except ValueError:
            skipped_feeds.append({"source_key": key, "reason": "invalid_json_feed"})
            continue

        feed_count += 1
        feed_title = (
            compact_text(feed.get("title"), 160) or key.replace("_", " ").title()
        )
        undated = 0

        for item in feed["items"]:
            if not isinstance(item, dict):
                continue
            original_id = item.get("id")
            title = compact_text(item.get("title"), 300)
            url = canonical_url(item)
            if (
                not isinstance(original_id, str)
                or not original_id
                or not title
                or not url
            ):
                continue

            date = item_date(item)
            if date is None:
                if undated >= MAX_UNDATED_PER_FEED:
                    continue
                undated += 1
            elif date < cutoff or date > now + timedelta(days=1):
                continue

            raw_tags = item.get("tags")
            tags = [
                compact_text(tag, 80)
                for tag in (raw_tags if isinstance(raw_tags, list) else [])
                if isinstance(tag, str)
            ][:12]
            entries.append(
                (
                    date,
                    key,
                    {
                        "id": encode_id(key, original_id, revision),
                        "source_key": key,
                        "source": feed_title,
                        "title": title,
                        "url": url,
                        "summary": entry_summary(item),
                        "published_at": (
                            item.get("date_published")
                            if isinstance(item.get("date_published"), str)
                            else None
                        ),
                        "modified_at": (
                            item.get("date_modified")
                            if isinstance(item.get("date_modified"), str)
                            else None
                        ),
                        "tags": tags,
                    },
                )
            )

    floor = datetime.min.replace(tzinfo=timezone.utc)
    entries.sort(key=lambda row: row[0] or floor, reverse=True)
    retained, truncated, first_omitted = _select_entries(entries)
    boundary = _complete_coverage_boundary(entries, first_omitted, cutoff, now)
    items = [entry for _, _, entry in retained]

    return {
        "version": 3,
        "revision": revision,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "indexed_from": boundary.isoformat().replace("+00:00", "Z"),
        "truncated": truncated,
        "candidate_count": len(entries),
        "feed_count": feed_count,
        "skipped_feeds": skipped_feeds,
        "item_count": len(items),
        "items": items,
    }


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    feed_paths, missing = enabled_feed_paths()
    payload = build_index(
        feed_paths,
        revision=resolve_revision(),
        missing_feed_keys=missing,
    )
    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    for skipped in payload["skipped_feeds"]:
        print(f"  ! skipped {skipped['source_key']}: {skipped['reason']}")
    print(
        f"Built {OUT_PATH.relative_to(ROOT)} with {payload['item_count']} items "
        f"from {payload['feed_count']} enabled feeds at {payload['revision'][:12]}"
    )


if __name__ == "__main__":
    main()
