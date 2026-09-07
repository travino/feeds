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

            payload = MODULE.build_index(
                [feed_path],
                datetime(2026, 9, 7, 12, tzinfo=timezone.utc),
            )

        self.assertEqual(payload["feed_count"], 1)
        self.assertEqual(payload["item_count"], 1)
        self.assertEqual(payload["items"][0]["summary"], "hello world")
        self.assertEqual(payload["items"][0]["id"], "openai:dGFnOmV4YW1wbGU")


if __name__ == "__main__":
    unittest.main()
