import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "feed_generators"))

import discover  # noqa: E402
from llms_discovery import (  # noqa: E402
    LlmsCandidate,
    discover_llms_candidates,
    llms_url_for,
    parse_llms_candidates,
)


LLMS = """# Example Docs

> Product documentation.

## Feeds
- [Release RSS](/releases.xml): Native RSS for releases

## Updates
- [Changelog](/changelog/): Product releases and updates
- [Engineering blog](/blog/): Technical news

## Optional
- [API reference](/reference/): Complete API documentation
"""


class FakeResponse:
    def __init__(self, body: str, url: str, status_code: int = 200):
        self._body = body.encode()
        self.url = url
        self.status_code = status_code
        self.headers = {"content-length": str(len(self._body))}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=16_384):
        del chunk_size
        yield self._body


class FakeSession:
    def __init__(self, responses: FakeResponse | dict[str, FakeResponse]):
        self.responses = responses
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self.responses, dict):
            return self.responses[url]
        return self.responses


class LlmsDiscoveryTests(unittest.TestCase):
    def test_llms_url_preserves_docs_subpath_and_accepts_direct_index(self):
        self.assertEqual(
            llms_url_for("https://example.com/docs"),
            "https://example.com/docs/llms.txt",
        )
        self.assertEqual(
            llms_url_for("https://example.com/docs/llms.txt?old=1#x"),
            "https://example.com/docs/llms.txt",
        )

    def test_parser_ranks_native_feeds_before_content_scouting_pages(self):
        candidates = parse_llms_candidates(
            LLMS,
            "https://example.com/docs/llms.txt",
            limit=8,
        )
        self.assertEqual(candidates[0].title, "Release RSS")
        self.assertEqual(candidates[0].url, "https://example.com/releases.xml")
        self.assertGreater(candidates[0].score, candidates[1].score)
        self.assertEqual({candidate.title for candidate in candidates[:3]}, {
            "Release RSS",
            "Changelog",
            "Engineering blog",
        })
        self.assertEqual(candidates[-1].title, "API reference")

    def test_remote_discovery_is_bounded_and_uses_resolved_response_url(self):
        specific = "https://docs.example.com/sdk/llms.txt"
        origin = "https://docs.example.com/llms.txt"
        session = FakeSession({
            specific: FakeResponse(LLMS, specific),
            origin: FakeResponse("# Root docs\n", origin),
        })
        candidates = discover_llms_candidates(
            "https://docs.example.com/sdk",
            limit=2,
            session=session,
        )
        self.assertEqual(len(candidates), 2)
        self.assertEqual([call[0] for call in session.calls], [specific, origin])
        self.assertTrue(session.calls[0][1]["stream"])
        self.assertTrue(candidates[0].url.startswith("https://docs.example.com/"))

    def test_page_specific_404_falls_back_to_origin_llms_index(self):
        specific = "https://example.com/blog/post/llms.txt"
        origin = "https://example.com/llms.txt"
        session = FakeSession({
            specific: FakeResponse("missing", specific, status_code=404),
            origin: FakeResponse(LLMS, origin),
        })
        candidates = discover_llms_candidates(
            "https://example.com/blog/post",
            limit=3,
            session=session,
        )
        self.assertEqual([call[0] for call in session.calls], [specific, origin])
        self.assertEqual(candidates[0].title, "Release RSS")
        self.assertEqual(candidates[0].url, "https://example.com/releases.xml")

    def test_discover_main_merges_root_and_llms_candidate_feeds(self):
        candidate = LlmsCandidate(
            title="Changelog",
            url="https://example.com/changelog/",
            section="Updates",
            description="Product releases",
            score=85,
        )
        root_feed = {
            "url": "https://example.com/feed.xml",
            "version": "rss20",
            "score": 10,
            "title": "Main feed",
        }
        changelog_feed = {
            "url": "https://example.com/changelog/feed.xml",
            "version": "atom10",
            "score": 9,
            "title": "Changelog",
        }

        def target(url):
            if url == "https://example.com/":
                return [root_feed], "local"
            if url == candidate.url:
                return [root_feed, changelog_feed], "hosted"
            self.fail(f"unexpected probe: {url}")

        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.object(discover, "discover_target", side_effect=target),
            patch.object(discover, "llms_candidates", return_value=[candidate]),
            patch.object(sys, "argv", ["discover.py", "https://example.com/"]),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            discover.main()

        lines = stdout.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("https://example.com/feed.xml", lines[0])
        self.assertIn("https://example.com/changelog/feed.xml", lines[1])
        self.assertIn("# sources: local, llms-hosted", stderr.getvalue())
        self.assertIn("llms.txt candidate", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
