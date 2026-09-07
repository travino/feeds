import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "feed_generators"))

import baidubaike  # noqa: E402


BAIKE_HTML = """
<html>
  <body>
    <p>今天是2026年09月07日星期一。今日共为您推荐5条热点资讯和4个热搜词条:</p>
    <section>
      <h2>热搜词条</h2>
      <div>2026.09.07</div>
      <ul>
        <li>习近平文化思想国际学术研讨会</li>
        <li>全民国防教育月</li>
        <li>白露</li>
        <li>国家反诈AI</li>
        <li>平陆运河</li>
        <li>特别国债</li>
      </ul>
    </section>
    <h2>V百科</h2>
    <div>不应进入 feed</div>
  </body>
</html>
"""


class BaiduBaikeTests(unittest.TestCase):
    def test_extracts_dated_hot_terms_in_rank_order(self):
        entries = baidubaike.extract_hot_terms(BAIKE_HTML)

        self.assertEqual(len(entries), 6)
        self.assertEqual(entries[0]["title"], "习近平文化思想国际学术研讨会")
        self.assertEqual(entries[-1]["title"], "特别国债")
        self.assertEqual(
            entries[0]["date"],
            datetime(2026, 9, 7, tzinfo=timezone(timedelta(hours=8))),
        )
        self.assertEqual(
            entries[0]["link"],
            "https://baike.baidu.com/item/%E4%B9%A0%E8%BF%91%E5%B9%B3%E6%96%87%E5%8C%96%E6%80%9D%E6%83%B3%E5%9B%BD%E9%99%85%E5%AD%A6%E6%9C%AF%E7%A0%94%E8%AE%A8%E4%BC%9A",
        )
        self.assertIn("排名 #1", entries[0]["description"])

    def test_scraper_filters_terms_already_in_cache(self):
        known = {"https://baike.baidu.com/item/%E7%99%BD%E9%9C%B2"}
        with patch.object(baidubaike, "get_html", return_value=BAIKE_HTML):
            entries = baidubaike.scrape_baidu_baike_hot_terms(known)

        self.assertEqual(len(entries), 5)
        self.assertNotIn("白露", {entry["title"] for entry in entries})

    def test_missing_hot_section_returns_no_entries(self):
        self.assertEqual(baidubaike.extract_hot_terms("<html><body>百度百科</body></html>"), [])


if __name__ == "__main__":
    unittest.main()
