import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "feed_generators"))

import saas


class CodeRabbitSaasTests(unittest.TestCase):
    def test_newsroom_scraper_parses_cards_and_skips_known_links(self):
        html = """
        <main>
          <a href="/newsroom/new-story">
            <time datetime="2026-08-12">August 12, 2026</time>
            <span>CodeRabbit</span>
            <h3>New CodeRabbit story</h3>
            <p>Useful newsroom summary.</p>
          </a>
          <a href="/newsroom/known-story">
            <time datetime="2026-08-11">August 11, 2026</time>
            <h3>Known story</h3>
          </a>
        </main>
        """
        known = {"https://www.coderabbit.ai/newsroom/known-story"}
        with patch.object(saas.multi_rss, "get_html", return_value=html):
            entries = saas.collect_coderabbit_newsroom(known)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["source"], "CodeRabbit Newsroom")
        self.assertEqual(
            entries[0]["link"], "https://www.coderabbit.ai/newsroom/new-story"
        )
        self.assertEqual(entries[0]["title"], "New CodeRabbit story")
        self.assertEqual(entries[0]["description"], "Useful newsroom summary.")
        self.assertEqual(entries[0]["date"], datetime(2026, 8, 12, tzinfo=UTC))

    def test_main_persists_retired_cache_cleanup_when_sources_are_empty(self):
        retired = [{"source": "Upstash Blog", "link": "https://upstash.com/blog/old"}]
        collectors = (
            "collect_hcp",
            "collect_bitly",
            "collect_commoninja",
            "collect_native_feeds",
            "collect_stripe",
            "collect_coderabbit_newsroom",
            "collect_postman_app_release_notes",
            "collect_postman_press",
            "collect_exa_blog",
            "collect_xweather_blog",
            "collect_xweather_changelogs",
            "collect_dated_anchor_sources",
        )
        patches = [patch.object(saas, name, return_value=[]) for name in collectors]
        for active_patch in patches:
            active_patch.start()
        self.addCleanup(lambda: [active_patch.stop() for active_patch in reversed(patches)])
        with (
            patch.object(saas, "load_cache", return_value={"entries": [{}]}),
            patch.object(saas, "deserialize_entries", return_value=retired),
            patch.object(saas, "enrich_entries"),
            patch.object(saas, "save_cache") as save_cache,
            patch.object(saas, "generate_atom_feed") as generate_atom_feed,
            patch.object(saas, "save_atom_feed") as save_atom_feed,
        ):
            self.assertTrue(saas.main())
        save_cache.assert_called_once_with(saas.FEED_NAME, [])
        generate_atom_feed.assert_not_called()
        save_atom_feed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
