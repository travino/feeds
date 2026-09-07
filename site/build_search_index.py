#!/usr/bin/env python3
"""Build a compact recent-entry index for Feedseek's remote MCP search tool."""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
FEEDS_DIR = ROOT / "feeds"
REGISTRY_PATH = ROOT / "feeds.yaml"
OUT_PATH = ROOT / "public" / "feedseek-search-index.json"
WINDOW_DAYS = 14
MAX_ITEMS = 5000
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
    registry = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8")) or {}
    feeds = registry.get("feeds", {})
    if not isinstance(feeds, dict):
        raise ValueError("feeds.yaml must contain a mapping under 'feeds'")

    paths: list[Path] = []
    missing: list[str] = []
    for key, config in feeds.items():
        if not isinstance(key, str):
            continue
        if isinstance(config, dict) and config.get("enabled") is False:
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
            except OSError, subprocess.CalledProcessError:
                revision = ""

    if len(revision) != 40 or any(
        char not in "0123456789abcdefABCDEF" for char in revision
    ):
        raise ValueError(
            "Feedseek MCP index requires an exact 40-character Git commit SHA"
        )
    return revision.lower()


def build_index(
    feed_paths: list[Path],
    now: datetime | None = None,
    revision: str = "0" * 40,
) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = now - timedelta(days=WINDOW_DAYS)
    entries: list[tuple[datetime | None, dict]] = []
    feed_count = 0

    for path in sorted(feed_paths):
        feed = load_feed(path)
        feed_count += 1
        key = path.stem.removeprefix("feed_")
        feed_title = (
            compact_text(feed.get("title"), 160) or key.replace("_", " ").title()
        )
        undated = 0

        for item in feed["items"]:
            if not isinstance(item, dict):
                continue
            original_id = item.get("id")
            title = compact_text(item.get("title"), 300)
            if not isinstance(original_id, str) or not original_id or not title:
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
                    {
                        "id": encode_id(key, original_id, revision),
                        "source_key": key,
                        "source": feed_title,
                        "title": title,
                        "url": (
                            item.get("url") if isinstance(item.get("url"), str) else ""
                        ),
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
    entries.sort(key=lambda pair: pair[0] or floor, reverse=True)
    items = [entry for _, entry in entries[:MAX_ITEMS]]
    return {
        "version": 2,
        "revision": revision,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "indexed_from": cutoff.isoformat().replace("+00:00", "Z"),
        "feed_count": feed_count,
        "item_count": len(items),
        "items": items,
    }


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    feed_paths, missing = enabled_feed_paths()
    if missing:
        print(
            f"  ! no JSON artifact yet for enabled feeds: {', '.join(sorted(missing))}"
        )

    payload = build_index(feed_paths, revision=resolve_revision())
    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        f"Built {OUT_PATH.relative_to(ROOT)} with {payload['item_count']} items "
        f"from {payload['feed_count']} enabled feeds at {payload['revision'][:12]}"
    )


if __name__ == "__main__":
    main()
