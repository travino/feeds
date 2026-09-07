import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "feed_generators"))

import widocznosc  # noqa: E402


class WidocznoscNewsTests(unittest.TestCase):
    def test_scraper_parses_polish_news_cards_and_dedupes(self):
        html = """
        <main>
          <a href="/news/seattle-times-i-newsday-pozywaja-openai/">
            <span>6 września 2026</span>
            <div class="news-card-title">Seattle Times i Newsday pozywają OpenAI oraz Microsoft</div>
            <p>Do grona wydawców walczących z twórcami modeli dołączyły kolejne redakcje.</p>
          </a>
          <a href="https://widocznosc.ai/news/already-seen/">
            <span>5 września 2026</span><div class="news-card-title">Already seen</div>
          </a>
          <a href="/news/">News</a>
        </main>
        """
        known = {"https://widocznosc.ai/news/already-seen"}

        with patch.object(widocznosc, "get_html", return_value=html):
            entries = widocznosc.scrape_widocznosc_news(known)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["source"], "widocznosc.ai")
        self.assertEqual(
            entries[0]["link"],
            "https://widocznosc.ai/news/seattle-times-i-newsday-pozywaja-openai/",
        )
        self.assertEqual(
            entries[0]["date"], datetime(2026, 9, 6, tzinfo=timezone.utc)
        )
        self.assertEqual(
            entries[0]["title"],
            "Seattle Times i Newsday pozywają OpenAI oraz Microsoft",
        )
        self.assertEqual(
            entries[0]["description"],
            "Do grona wydawców walczących z twórcami modeli dołączyły kolejne redakcje.",
        )

    def test_polish_month_parser_handles_diacritics(self):
        self.assertEqual(
            widocznosc._parse_polish_date("14 października 2026"),
            datetime(2026, 10, 14, tzinfo=timezone.utc),
        )
        self.assertEqual(
            widocznosc._parse_polish_date("1 sierpnia 2026"),
            datetime(2026, 8, 1, tzinfo=timezone.utc),
        )


if __name__ == "__main__":
    unittest.main()
