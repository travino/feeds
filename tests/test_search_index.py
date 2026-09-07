import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "site" / "build_search_index.py"
SPEC = importlib.util.spec_from_file_location("feedseek_search_index", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

REVISION = "a" * 40
NOW = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)


class SearchIndexTests(unittest.TestCase):
    def test_build_index_keeps_recent_items_and_stable_opaque_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            feed_path = Path(tmp) / "feed_openai.json"
            feed_path.write_text(
                json.dumps(
                    {
                        "title": "OpenAI",
                        "items": [
                            {
                                "id": "tag:example",
                                "title": "Fresh",
                                "content_text": "  hello   world ",
                                "date_published": "2026-09-07T10:00:00Z",
                                "tags": ["AI"],
                            },
                            {
                                "id": "old",
                                "title": "Old",
                                "content_text": "old",
                                "date_published": "2026-08-01T00:00:00Z",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = MODULE.build_index([feed_path], NOW, REVISION)

        self.assertEqual(payload["feed_count"], 1)
        self.assertEqual(payload["item_count"], 1)
        self.assertEqual(payload["items"][0]["summary"], "hello world")
        self.assertEqual(
            payload["items"][0]["id"],
            f"{REVISION}.openai:dGFnOmV4YW1wbGU",
        )

    def test_recent_modification_keeps_old_publication_in_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            feed_path = Path(tmp) / "feed_openai.json"
            feed_path.write_text(
                json.dumps(
                    {
                        "title": "OpenAI",
                        "items": [
                            {
                                "id": "updated",
                                "title": "Updated",
                                "content_text": "changed",
                                "date_published": "2026-01-01T00:00:00Z",
                                "date_modified": "2026-09-07T11:00:00Z",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = MODULE.build_index([feed_path], NOW, REVISION)

        self.assertEqual(payload["item_count"], 1)
        self.assertEqual(
            payload["items"][0]["modified_at"],
            "2026-09-07T11:00:00Z",
        )

    def test_html_only_content_is_plain_text_in_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            feed_path = Path(tmp) / "feed_html.json"
            feed_path.write_text(
                json.dumps(
                    {
                        "title": "HTML",
                        "items": [
                            {
                                "id": "html",
                                "title": "HTML entry",
                                "content_html": (
                                    "<p>Hello &amp; <strong>world</strong>.</p>"
                                    "<script>ignored()</script>"
                                    "<style>.ignored{}</style>"
                                    "<p>Second&nbsp;line &#33;</p>"
                                ),
                                "date_published": "2026-09-07T10:00:00Z",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = MODULE.build_index([feed_path], NOW, REVISION)

        self.assertEqual(payload["item_count"], 1)
        self.assertEqual(
            payload["items"][0]["summary"],
            "Hello & world. Second line !",
        )

    def test_content_text_preserves_literal_angle_brackets(self):
        item = {"content_text": "Use <T> & keep it"}
        self.assertEqual(MODULE.entry_text(item), "Use <T> & keep it")

    def test_malformed_json_feed_fails_instead_of_disappearing_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            feed_path = Path(tmp) / "feed_bad.json"
            feed_path.write_text("{not-json", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Could not read valid JSON Feed"):
                MODULE.build_index([feed_path], NOW, REVISION)


if __name__ == "__main__":
    unittest.main()
