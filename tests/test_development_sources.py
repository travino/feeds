import json
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "feed_generators"))

import development
from utils import merge_entries


class DevelopmentSourceTests(unittest.TestCase):
    def test_latest_packages_is_capped_at_three(self):
        source = next(item for item in development.SOURCES if item[0] == "Django Packages latest")
        self.assertEqual(source[2], 3)

    def test_requested_development_sources_are_present(self):
        urls = {label: url for label, url, _ in development.SOURCES}
        self.assertEqual(urls["Changelog News"], "https://changelog.com/news/feed")
        self.assertEqual(urls["Scripting News"], "http://scripting.com/rss.xml")
        self.assertEqual(urls["Development Seed"], "https://developmentseed.org/rss.xml")
        self.assertEqual(urls["Coding Horror"], "https://blog.codinghorror.com/rss/")
        self.assertEqual(urls["RubyGems Blog"], "https://blog.rubygems.org/atom.xml")
        self.assertEqual(urls["RubyInstaller"], "https://rubyinstaller.org/feed.xml")
        self.assertEqual(urls["JetBrains Blog"], "https://blog.jetbrains.com/feed/")
        self.assertEqual(urls["web.dev Blog"], "https://web.dev/blog/feed.xml")
        self.assertEqual(development.DEV_TOP_MONTH_URL, "https://dev.to/top/month")
        self.assertEqual(
            development.DEV_TOP_MONTH_API_URL,
            "https://dev.to/api/articles?top=30&per_page=30",
        )

    def test_direct_django_sources_precede_community_aggregator(self):
        labels = [label for label, _, _ in development.SOURCES]
        community = labels.index("Django Community")
        self.assertLess(labels.index("TestDriven.io"), community)
        self.assertLess(labels.index("Django News"), community)
        self.assertLess(labels.index("Django Weblog"), community)

        direct = {
            "link": "https://example.com/post",
            "date": datetime(2026, 8, 10, tzinfo=UTC),
            "source": "TestDriven.io",
        }
        republished = {
            "link": direct["link"],
            "date": datetime(2026, 8, 11, tzinfo=UTC),
            "source": "Django Community",
        }
        merged = merge_entries([direct, republished], [])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["source"], "TestDriven.io")

    def test_rust_releases_parse_dates_and_skip_known_links(self):
        html = """
        <table>
          <tr><td class="bn"><a href="https://blog.rust-lang.org/2026/07/16/Rust-1.97.1/">Announcing Rust 1.97.1</a></td></tr>
          <tr><td class="bn"><a href="https://blog.rust-lang.org/2026/07/09/Rust-1.97.0/">Announcing Rust 1.97.0</a></td></tr>
        </table>
        """
        known = {"https://blog.rust-lang.org/2026/07/16/Rust-1.97.1/"}

        with patch.object(development, "get_html", return_value=html):
            entries = development.scrape_rust_releases(known)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "Announcing Rust 1.97.0")
        self.assertEqual(entries[0]["source"], "Rust Releases")
        self.assertEqual(entries[0]["date"].isoformat(), "2026-07-09T00:00:00+00:00")

    def test_rust_releases_warn_when_layout_has_no_matches(self):
        html = '<a href="https://blog.rust-lang.org/2026/07/09/Rust-1.97.0/">Rust 1.97.0</a>'
        with (
            patch.object(development, "get_html", return_value=html),
            patch.object(development.logger, "warning") as warning,
        ):
            entries = development.scrape_rust_releases(set())

        self.assertEqual(entries, [])
        warning.assert_called_once_with("  [Rust Releases] no release links matched the index layout")

    def test_django_packages_changelog_targets_date_node(self):
        html = """
        <div class="flex-shrink-0 md:w-1/3">
          <div class="text-muted-foreground mb-1 text-sm">March 7, 2026</div>
          <span>Featured</span>
          <h2 class="text-foreground text-xl font-bold">
            <a href="/changelog/postgresql-fts/">🔎 PostgreSQL full-text search for djangopackages</a>
          </h2>
        </div>
        """

        with patch.object(development, "get_html", return_value=html):
            entries = development.scrape_django_packages_changelog(set())

        self.assertEqual(len(entries), 1)
        self.assertEqual(
            entries[0]["link"],
            "https://djangopackages.org/changelog/postgresql-fts/",
        )
        self.assertEqual(entries[0]["date"].isoformat(), "2026-03-07T00:00:00+00:00")
        self.assertEqual(entries[0]["source"], "Django Packages changelog")

    def test_dev_top_month_uses_api_data_and_skips_known_links(self):
        payload = json.dumps(
            [
                {
                    "title": "Already cached",
                    "url": "https://dev.to/example/already-cached",
                    "description": "old",
                    "published_at": "2026-08-01T12:00:00Z",
                    "cover_image": None,
                    "social_image": "https://example.com/old.png",
                },
                {
                    "title": "Useful developer post",
                    "url": "https://dev.to/example/useful-developer-post",
                    "description": "A useful summary.",
                    "published_at": "2026-08-20T12:34:56Z",
                    "cover_image": "https://example.com/cover.png",
                    "social_image": "https://example.com/social.png",
                },
            ]
        )

        with patch.object(development, "get_html", return_value=payload):
            entries = development.scrape_dev_top_month(
                {"https://dev.to/example/already-cached"}
            )

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "Useful developer post")
        self.assertEqual(entries[0]["source"], "DEV Top Month")
        self.assertEqual(entries[0]["date"].isoformat(), "2026-08-20T12:34:56+00:00")
        self.assertEqual(entries[0]["image"], "https://example.com/cover.png")


if __name__ == "__main__":
    unittest.main()
