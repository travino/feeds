import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "feed_generators"))

import saas  # noqa: E402


class StripeSaaSSourcesTests(unittest.TestCase):
    def test_requested_public_sources_are_documented(self):
        sources = dict(saas.doc_sources())
        self.assertEqual(sources["Stripe Newsroom"], "https://stripe.com/en-pl/newsroom")
        self.assertEqual(sources["Stripe Developer Blog"], "https://stripe.dev/")
        self.assertEqual(sources["Stripe Changelog"], "https://docs.stripe.com/changelog")

    def test_newsroom_parser_pairs_title_and_date_links(self):
        html = """
        <a href="/en-pl/newsroom/news/example-launch">Example Stripe launch for developers</a>
        <a href="/en-pl/newsroom/news/example-launch">21 July 2026</a>
        """
        entries = saas.parse_stripe_newsroom(html)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "Example Stripe launch for developers")
        self.assertEqual(entries[0]["date"].isoformat(), "2026-07-21T00:00:00+00:00")
        self.assertEqual(entries[0]["source"], "Stripe Newsroom")

    def test_dev_blog_parser_uses_visible_dot_date(self):
        html = """
        <article><a href="/blog/building-projects">2026.8.28 Building projects with Stripe</a></article>
        """
        entries = saas.parse_stripe_dev_blog(html)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "Building projects with Stripe")
        self.assertEqual(entries[0]["date"].isoformat(), "2026-08-28T00:00:00+00:00")
        self.assertEqual(entries[0]["source"], "Stripe Developer Blog")

    def test_changelog_parser_canonicalizes_markdown_links(self):
        html = """
        <a href="https://docs.stripe.com/changelog/dahlia/2026-07-29/example-change.md">Adds an example API field</a>
        """
        entries = saas.parse_stripe_changelog(html)
        self.assertEqual(len(entries), 1)
        self.assertEqual(
            entries[0]["link"],
            "https://docs.stripe.com/changelog/dahlia/2026-07-29/example-change",
        )
        self.assertEqual(entries[0]["date"].isoformat(), "2026-07-29T00:00:00+00:00")
        self.assertEqual(entries[0]["source"], "Stripe Changelog")

    def test_known_links_are_filtered(self):
        link = "https://docs.stripe.com/changelog/dahlia/2026-07-29/example-change"
        html = f'<a href="{link}.md">Example change</a>'
        self.assertEqual(saas.parse_stripe_changelog(html, {link}), [])


if __name__ == "__main__":
    unittest.main()
