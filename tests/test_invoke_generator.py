import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from feedgen.feed import FeedGenerator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "feed_generators"))

from invoke_generator import (  # noqa: E402
    ENTRY_ID_FIELD,
    PRESERVE_MISSING_DATE,
    freeze_missing_dates,
    freeze_saved_entry_dates,
    invoke,
    persist_entry_ids,
    preserve_atom_publication_dates,
    reuse_requests_connections,
)


class InvokeGeneratorTests(unittest.TestCase):
    def _script(self, source: str) -> Path:
        directory = Path(tempfile.mkdtemp())
        path = directory / "generator.py"
        path.write_text(source, encoding="utf-8")
        return path

    def _atom_entry(self, *, explicit_updated=None) -> str:
        fg = FeedGenerator()
        fg.id("https://example.com/")
        fg.title("Example")
        fg.author({"name": "Example"})
        fe = fg.add_entry()
        fe.id("https://example.com/post")
        fe.title("Post")
        fe.link(href="https://example.com/post")
        fe.published(datetime(2020, 1, 2, tzinfo=timezone.utc))
        if explicit_updated is not None:
            fe.updated(explicit_updated)
        return fg.atom_str(pretty=True).decode()

    def test_explicit_false_is_a_failed_generation(self):
        script = self._script("def main(full=False):\n    return False\n")
        self.assertFalse(invoke(script))

    def test_none_remains_backward_compatible_success(self):
        script = self._script("def main():\n    pass\n")
        self.assertTrue(invoke(script))

    def test_integer_exit_statuses_are_normalized(self):
        success = self._script("def main():\n    return 0\n")
        failure = self._script("def main():\n    return 1\n")
        self.assertTrue(invoke(success))
        self.assertFalse(invoke(failure))

    def test_full_reset_signature_is_supported(self):
        script = self._script(
            "def main(full_reset=False):\n"
            "    return full_reset\n"
        )
        self.assertTrue(invoke(script, full=True))
        self.assertFalse(invoke(script, full=False))

    def test_generator_receives_isolated_argv(self):
        script = self._script(
            "import argparse\n"
            "def main():\n"
            "    parser = argparse.ArgumentParser()\n"
            "    parser.add_argument('--full', action='store_true')\n"
            "    return 0 if parser.parse_args().full else 1\n"
        )
        self.assertTrue(invoke(script, full=True))
        self.assertFalse(invoke(script, full=False))

    def test_decorators_can_resolve_dynamic_module(self):
        script = self._script(
            "from dataclasses import dataclass\n"
            "@dataclass\n"
            "class Item:\n"
            "    value: int\n"
            "def main():\n"
            "    return Item(1).value == 1\n"
        )
        self.assertTrue(invoke(script))

    def test_requests_connections_are_reused_per_thread(self):
        import requests
        import requests.api

        sessions = []

        class FakeSession:
            """Small Requests session stand-in used to observe pooling."""

            def __init__(self):
                self.closed = False
                sessions.append(self)

            def request(self, **_kwargs):
                return self

            def close(self):
                self.closed = True

        original_api_request = requests.api.request
        original_package_request = requests.request
        with patch.object(requests, "Session", FakeSession):
            with reuse_requests_connections():
                first = requests.get("https://example.com/a", timeout=1)
                second = requests.request("GET", "https://example.com/b", timeout=1)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    worker = pool.submit(
                        requests.get,
                        "https://example.com/thread",
                        timeout=1,
                    ).result()

                self.assertIs(first, second)
                self.assertIsNot(first, worker)
                self.assertEqual(len(sessions), 2)

            self.assertTrue(all(session.closed for session in sessions))

        self.assertIs(requests.api.request, original_api_request)
        self.assertIs(requests.request, original_package_request)

    def test_implicit_atom_update_uses_publication_date(self):
        with preserve_atom_publication_dates():
            xml = self._atom_entry()

        self.assertIn("<published>2020-01-02T00:00:00+00:00</published>", xml)
        self.assertIn("<updated>2020-01-02T00:00:00+00:00</updated>", xml)

    def test_explicit_atom_update_is_preserved(self):
        updated = datetime(2026, 7, 30, 2, 0, tzinfo=timezone.utc)
        with preserve_atom_publication_dates():
            xml = self._atom_entry(explicit_updated=updated)

        self.assertIn("<published>2020-01-02T00:00:00+00:00</published>", xml)
        self.assertIn("<updated>2026-07-30T02:00:00+00:00</updated>", xml)

    def test_missing_dates_receive_one_shared_first_seen_value(self):
        first_seen = datetime(2026, 7, 30, 3, 0, tzinfo=timezone.utc)
        entries = [
            {"link": "https://example.com/a", "date": None},
            {"link": "https://example.com/b"},
        ]

        frozen = freeze_missing_dates(entries, fallback=first_seen)

        self.assertIs(frozen, entries)
        self.assertEqual([entry["date"] for entry in entries], [first_seen, first_seen])

    def test_existing_and_retryable_dates_are_not_replaced(self):
        published = datetime(2020, 1, 2, tzinfo=timezone.utc)
        entries = [
            {"link": "https://example.com/dated", "date": published},
            {
                "link": "https://example.com/retry",
                "date": None,
                PRESERVE_MISSING_DATE: True,
            },
        ]

        freeze_missing_dates(entries)

        self.assertEqual(entries[0]["date"], published)
        self.assertIsNone(entries[1]["date"])

    def test_persisted_entry_id_matches_current_published_id(self):
        import utils

        link = "https://example.com/article"
        expected = utils.make_entry_id("example", link)
        entries = [{"link": link}]

        persisted = persist_entry_ids("example", entries)

        self.assertIs(persisted, entries)
        self.assertEqual(entries[0][ENTRY_ID_FIELD], expected)

    def test_existing_persisted_entry_id_is_never_overwritten(self):
        import utils

        entry = {
            "link": "https://example.com/article",
            ENTRY_ID_FIELD: "tag:example.test,2026:permanent-id",
        }
        with patch.object(utils, "make_entry_id") as make_id:
            persist_entry_ids("example", [entry])

        self.assertEqual(entry[ENTRY_ID_FIELD], "tag:example.test,2026:permanent-id")
        make_id.assert_not_called()

    def test_save_wrapper_runs_after_real_date_wins_deduplication(self):
        import utils

        published = datetime(2020, 1, 2, tzinfo=timezone.utc)
        entries = utils.dedupe_entries(
            [
                {"link": "https://example.com/old", "title": "Same", "date": None},
                {
                    "link": "https://example.com/new",
                    "title": "Same",
                    "date": published,
                },
            ]
        )
        self.assertEqual(entries[0]["date"], published)

        with patch.object(utils, "save_cache") as original_save:
            with freeze_saved_entry_dates():
                utils.save_cache("example", entries)

        self.assertEqual(entries[0]["date"], published)
        self.assertNotIn(ENTRY_ID_FIELD, entries[0])
        original_save.assert_called_once_with("example", entries, entries_key="entries")

    def test_non_id_feed_is_not_seeded(self):
        import utils

        entries = [{"link": "https://example.com/plain", "date": None}]
        with patch.object(utils, "save_cache") as original_save:
            with freeze_saved_entry_dates():
                utils.save_cache("plain", entries)

        self.assertNotIn(ENTRY_ID_FIELD, entries[0])
        original_save.assert_called_once_with("plain", entries, entries_key="entries")

    def test_id_used_before_save_is_persisted_in_first_write(self):
        import utils

        link = "https://example.com/before"
        entries = [{"link": link, "date": None}]
        with patch.object(utils, "save_cache") as original_save:
            with freeze_saved_entry_dates():
                expected = utils.make_entry_id("example", link)
                utils.save_cache("example", entries)

        self.assertEqual(entries[0][ENTRY_ID_FIELD], expected)
        original_save.assert_called_once_with("example", entries, entries_key="entries")

    def test_id_used_after_save_triggers_compatibility_resave(self):
        import utils

        link = "https://example.com/after"
        entries = [{"link": link, "date": None}]
        with patch.object(utils, "save_cache") as original_save:
            with freeze_saved_entry_dates():
                utils.save_cache("example", entries)
                expected = utils.make_entry_id("example", link)

        self.assertEqual(entries[0][ENTRY_ID_FIELD], expected)
        self.assertEqual(original_save.call_count, 2)
        original_save.assert_called_with("example", entries, entries_key="entries")

    def test_save_wrapper_freezes_ordinary_cached_null(self):
        import utils

        entries = [{"link": "https://example.com/cached", "date": None}]
        with patch.object(utils, "save_cache"):
            with freeze_saved_entry_dates():
                utils.save_cache("example", entries)

        self.assertIsNotNone(entries[0]["date"])
        self.assertNotIn(ENTRY_ID_FIELD, entries[0])


if __name__ == "__main__":
    unittest.main()
