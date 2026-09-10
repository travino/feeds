import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "site" / "build_search_index.py"
SPEC = importlib.util.spec_from_file_location("feedseek_search_index", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load module spec from {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

REVISION = "a" * 40
NOW = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)


class SearchIndexTests(unittest.TestCase):
    """Regression coverage for the compact ChatGPT search index."""

    def write_feed(self, root: str, key: str, items: list[dict]) -> Path:
        path = Path(root) / f"feed_{key}.json"
        path.write_text(
            json.dumps({"title": key.title(), "items": items}), encoding="utf-8"
        )
        return path

    def test_enabled_feed_paths_uses_validated_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            feed_dir = Path(tmp)
            present = self.write_feed(tmp, "present", [])
            registry = {
                "present": SimpleNamespace(enabled=True),
                "missing": SimpleNamespace(enabled=True),
                "disabled": SimpleNamespace(enabled=False),
            }
            with (
                patch.object(MODULE, "FEEDS_DIR", feed_dir),
                patch.object(MODULE, "load_feed_registry", return_value=registry),
            ):
                paths, missing = MODULE.enabled_feed_paths()

        self.assertEqual(paths, [present])
        self.assertEqual(missing, ["missing"])

    def test_build_index_keeps_recent_items_and_stable_opaque_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            feed = self.write_feed(
                tmp,
                "openai",
                [
                    {
                        "id": "tag:example",
                        "title": "Fresh",
                        "url": "https://example.com/fresh",
                        "content_text": "  hello   world ",
                        "date_published": "2026-09-07T10:00:00Z",
                        "tags": None,
                    },
                    {
                        "id": "old",
                        "title": "Old",
                        "url": "https://example.com/old",
                        "date_published": "2026-08-01T00:00:00Z",
                    },
                ],
            )
            payload = MODULE.build_index([feed], NOW, REVISION)

        self.assertEqual(payload["item_count"], 1)
        self.assertEqual(payload["items"][0]["summary"], "hello world")
        self.assertEqual(
            payload["items"][0]["id"], f"{REVISION}.openai:dGFnOmV4YW1wbGU"
        )
        self.assertFalse(payload["truncated"])

    def test_recent_modification_keeps_old_publication_in_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            feed = self.write_feed(
                tmp,
                "openai",
                [
                    {
                        "id": "updated",
                        "title": "Updated",
                        "url": "https://example.com/updated",
                        "date_published": "2026-01-01T00:00:00Z",
                        "date_modified": "2026-09-07T11:00:00Z",
                    }
                ],
            )
            payload = MODULE.build_index([feed], NOW, REVISION)
        self.assertEqual(payload["item_count"], 1)
        self.assertEqual(
            payload["items"][0]["modified_at"], "2026-09-07T11:00:00Z"
        )

    def test_html_only_content_is_plain_text_in_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            feed = self.write_feed(
                tmp,
                "html",
                [
                    {
                        "id": "html",
                        "title": "HTML entry",
                        "url": "https://example.com/html",
                        "content_html": (
                            "<p>Hello &amp; <strong>world</strong>.</p>"
                            "<script>ignored()</script><style>.ignored{}</style>"
                            "<p>Second&nbsp;line &#33;</p>"
                        ),
                        "date_published": "2026-09-07T10:00:00Z",
                    }
                ],
            )
            payload = MODULE.build_index([feed], NOW, REVISION)
        self.assertEqual(
            payload["items"][0]["summary"], "Hello & world. Second line !"
        )

    def test_malformed_feed_is_reported_and_healthy_feed_survives(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = self.write_feed(
                tmp,
                "good",
                [
                    {
                        "id": "good",
                        "title": "Good",
                        "url": "https://example.com/good",
                        "date_published": "2026-09-07T10:00:00Z",
                    }
                ],
            )
            bad = Path(tmp) / "feed_bad.json"
            bad.write_text("{not-json", encoding="utf-8")
            payload = MODULE.build_index([bad, good], NOW, REVISION)
        self.assertEqual(payload["item_count"], 1)
        self.assertEqual(payload["feed_count"], 1)
        self.assertEqual(
            payload["skipped_feeds"],
            [{"source_key": "bad", "reason": "invalid_json_feed"}],
        )

    def test_citation_url_uses_external_url_and_drops_uncitable_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            feed = self.write_feed(
                tmp,
                "links",
                [
                    {
                        "id": "fallback",
                        "title": "Fallback",
                        "external_url": "https://example.com/fallback",
                        "date_published": "2026-09-07T10:00:00Z",
                    },
                    {
                        "id": "none",
                        "title": "No URL",
                        "date_published": "2026-09-07T11:00:00Z",
                    },
                ],
            )
            payload = MODULE.build_index([feed], NOW, REVISION)
        self.assertEqual(payload["item_count"], 1)
        self.assertEqual(
            payload["items"][0]["url"], "https://example.com/fallback"
        )

    def test_global_cap_reserves_active_sources_and_reports_true_boundary(self):
        original_max = MODULE.MAX_ITEMS
        original_floor = MODULE.MIN_ITEMS_PER_FEED
        MODULE.MAX_ITEMS = 5
        MODULE.MIN_ITEMS_PER_FEED = 2
        try:
            with tempfile.TemporaryDirectory() as tmp:
                noisy_items = [
                    {
                        "id": f"a-{hour}",
                        "title": f"A {hour}",
                        "url": f"https://example.com/a/{hour}",
                        "date_published": f"2026-09-07T{hour:02d}:00:00Z",
                    }
                    for hour in range(11, 1, -1)
                ]
                quiet_items = [
                    {
                        "id": f"b-{hour}",
                        "title": f"B {hour}",
                        "url": f"https://example.com/b/{hour}",
                        "date_published": f"2026-09-06T{hour:02d}:00:00Z",
                    }
                    for hour in (11, 10)
                ]
                noisy = self.write_feed(tmp, "noisy", noisy_items)
                quiet = self.write_feed(tmp, "quiet", quiet_items)
                payload = MODULE.build_index([noisy, quiet], NOW, REVISION)
        finally:
            MODULE.MAX_ITEMS = original_max
            MODULE.MIN_ITEMS_PER_FEED = original_floor

        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["item_count"], 5)
        self.assertEqual(
            sum(item["source_key"] == "quiet" for item in payload["items"]), 2
        )
        self.assertEqual(payload["indexed_from"], "2026-09-07T09:00:00Z")


if __name__ == "__main__":
    unittest.main()
