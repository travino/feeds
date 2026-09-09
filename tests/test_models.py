import sys
import unittest
from pathlib import Path
from unittest.mock import mock_open, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "feed_generators"))

from models import load_feed_registry  # noqa: E402


class FeedRegistryTests(unittest.TestCase):
    def test_non_mapping_feed_configs_are_skipped(self):
        registry = """\
feeds:
  good:
    script: beatport_top100.py
    blog_url: https://example.com/
  null_config:
  list_config:
    - not
    - a
    - mapping
"""

        with patch("builtins.open", mock_open(read_data=registry)):
            feeds, skipped = load_feed_registry(return_skipped=True)

        self.assertEqual(set(feeds), {"good"})
        self.assertEqual(skipped, ["null_config", "list_config"])


if __name__ == "__main__":
    unittest.main()
