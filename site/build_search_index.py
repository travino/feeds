#!/usr/bin/env python3
"""Build a compact recent-entry index for Feedseek's remote MCP search tool."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEEDS_DIR = ROOT / "feeds"
OUT_PATH = ROOT / "public" / "feedseek-search-index.json"
WINDOW_DAYS = 14
MAX_ITEMS = 5000
MAX_UNDATED_PER_FEED = 5
SUMMARY_CHARS = 800


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


def encode_id(feed_key: str, item_id: str) -> str:
    token = base64.urlsafe_b64encode(item_id.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{feed_key}:{token}"


def item_date(item: dict) -> datetime | None:
    return parse_date(item.get("date_published")) or parse_date(item.get("date_modified"))


def build_index(feed_paths: list[Path], now: datetime | None = None) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = now - timedelta(days=WINDOW_DAYS)
    entries: list[tuple[datetime | None, dict]] = []
    feed_count = 0

    for path in sorted(feed_paths):
        try:
            feed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(feed, dict) or not isinstance(feed.get("items"), list):
            continue
        feed_count += 1
        key = path.stem.removeprefix("feed_")
        feed_title = compact_text(feed.get("title"), 160) or key.replace("_", " ").title()
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

            content = item.get("summary") or item.get("content_text") or item.get("content_html") or ""
            tags = [
                compact_text(tag, 80)
                for tag in item.get("tags", [])
                if isinstance(tag, str)
            ][:12]
            entries.append(
                (
                    date,
                    {
                        "id": encode_id(key, original_id),
                        "source_key": key,
                        "source": feed_title,
                        "title": title,
                        "url": item.get("url") if isinstance(item.get("url"), str) else "",
                        "summary": compact_text(content),
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
        "version": 1,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "indexed_from": cutoff.isoformat().replace("+00:00", "Z"),
        "feed_count": feed_count,
        "item_count": len(items),
        "items": items,
    }


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = build_index(list(FEEDS_DIR.glob("feed_*.json")))
    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        f"Built {OUT_PATH.relative_to(ROOT)} with {payload['item_count']} items "
        f"from {payload['feed_count']} feeds"
    )


if __name__ == "__main__":
    main()
