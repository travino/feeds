"""Runner isolation, timeout rollback, and bounded batch concurrency tests."""

import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "feed_generators"))

import run_all_feeds  # noqa: E402
from models import FeedConfig  # noqa: E402


class GeneratorTimeoutTests(unittest.TestCase):
    def config(self):
        return FeedConfig(script="reuters.py", blog_url="https://example.test/")

    def test_a_hung_generator_is_reported_as_failed_not_raised(self):
        expired = subprocess.TimeoutExpired(cmd=["python"], timeout=1)
        with mock.patch.object(run_all_feeds.subprocess, "run", side_effect=expired):
            self.assertFalse(run_all_feeds.run_feed("reuters", self.config()))

    def test_output_produced_before_the_kill_is_still_relayed(self):
        expired = subprocess.TimeoutExpired(cmd=["python"], timeout=1)
        expired.stdout = "got 3 entries"
        expired.stderr = "warning: slow source"
        with mock.patch.object(run_all_feeds.subprocess, "run", side_effect=expired):
            with self.assertLogs(run_all_feeds.logger, level="WARNING") as caught:
                run_all_feeds.run_feed("reuters", self.config())
        relayed = "\n".join(caught.output)
        self.assertIn("got 3 entries", relayed)
        self.assertIn("warning: slow source", relayed)

    def test_a_generator_that_returns_in_time_is_unaffected(self):
        done = subprocess.CompletedProcess(args=["python"], returncode=0, stdout="", stderr="")
        with (
            mock.patch.object(run_all_feeds.subprocess, "run", return_value=done) as run,
            mock.patch.object(run_all_feeds, "_feed_pair_is_valid", return_value=True),
        ):
            self.assertTrue(run_all_feeds.run_feed("reuters", self.config()))
        # The timeout must actually be passed, or the guard is decorative.
        self.assertEqual(run.call_args.kwargs["timeout"], run_all_feeds.GENERATOR_TIMEOUT)

    def test_timeout_restores_both_artifacts_after_partial_child_write(self):
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            xml = directory / "feed_reuters.xml"
            sidecar = directory / "feed_reuters.json"
            xml.write_text("old xml", encoding="utf-8")
            sidecar.write_text("old json", encoding="utf-8")

            def partial_then_timeout(*args, **kwargs):
                xml.write_text("new xml", encoding="utf-8")
                raise subprocess.TimeoutExpired(cmd=["python"], timeout=1)

            with (
                mock.patch.object(run_all_feeds, "FEEDS_DIR", directory),
                mock.patch.object(
                    run_all_feeds.subprocess, "run", side_effect=partial_then_timeout
                ),
            ):
                self.assertFalse(run_all_feeds.run_feed("reuters", self.config()))

            self.assertEqual(xml.read_text(encoding="utf-8"), "old xml")
            self.assertEqual(sidecar.read_text(encoding="utf-8"), "old json")

    def test_success_with_invalid_pair_is_rolled_back(self):
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            xml = directory / "feed_reuters.xml"
            sidecar = directory / "feed_reuters.json"
            xml.write_text("old xml", encoding="utf-8")
            sidecar.write_text("old json", encoding="utf-8")

            def invalid_success(*args, **kwargs):
                xml.write_text(
                    '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>x</id></entry></feed>',
                    encoding="utf-8",
                )
                sidecar.write_text("not json", encoding="utf-8")
                return subprocess.CompletedProcess(
                    args=["python"], returncode=0, stdout="", stderr=""
                )

            with (
                mock.patch.object(run_all_feeds, "FEEDS_DIR", directory),
                mock.patch.object(run_all_feeds.subprocess, "run", side_effect=invalid_success),
            ):
                self.assertFalse(run_all_feeds.run_feed("reuters", self.config()))

            self.assertEqual(xml.read_text(encoding="utf-8"), "old xml")
            self.assertEqual(sidecar.read_text(encoding="utf-8"), "old json")


class GeneratorBatchTests(unittest.TestCase):
    @staticmethod
    def config() -> FeedConfig:
        # FeedConfig validates that the referenced script exists; the actual
        # subprocess is mocked in these scheduler-only tests.
        return FeedConfig(script="reuters.py", blog_url="https://example.test/")

    def test_invalid_worker_configuration_falls_back_to_default(self):
        with (
            mock.patch.dict(os.environ, {"FEEDSEEK_GENERATOR_WORKERS": "potato"}),
            self.assertLogs(run_all_feeds.logger, level="WARNING"),
        ):
            workers = run_all_feeds._configured_generator_workers()

        self.assertEqual(workers, run_all_feeds.DEFAULT_GENERATOR_WORKERS)

    def test_enabled_generators_overlap_when_workers_are_available(self):
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        active = 0
        peak = 0

        def fake_run_feed(name, config, full=False):
            del name, config, full
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                barrier.wait(timeout=2)
            finally:
                with lock:
                    active -= 1
            return True

        registry = {
            "alpha": self.config(),
            "beta": self.config(),
        }
        with (
            mock.patch.object(run_all_feeds, "GENERATOR_WORKERS", 2),
            mock.patch.object(run_all_feeds, "run_feed", new=fake_run_feed),
            mock.patch.object(run_all_feeds, "normalize_generated_feeds", return_value=True),
        ):
            status = run_all_feeds._run_registry(registry, [], full=False)

        self.assertEqual(status, 0)
        self.assertEqual(peak, 2)

    def test_single_worker_preserves_serial_execution(self):
        order = []

        def fake_run_feed(name, config, full=False):
            del config, full
            order.append(name)
            return True

        registry = {
            "beta": self.config(),
            "alpha": self.config(),
        }
        with (
            mock.patch.object(run_all_feeds, "GENERATOR_WORKERS", 1),
            mock.patch.object(run_all_feeds, "run_feed", new=fake_run_feed),
            mock.patch.object(run_all_feeds, "normalize_generated_feeds", return_value=True),
        ):
            status = run_all_feeds._run_registry(registry, [], full=False)

        self.assertEqual(status, 0)
        self.assertEqual(order, ["alpha", "beta"])

    def test_enabled_feed_reports_wall_clock_duration(self):
        with (
            mock.patch.object(run_all_feeds, "run_feed", return_value=True),
            mock.patch.object(
                run_all_feeds.time, "perf_counter", side_effect=[10.0, 13.25]
            ),
        ):
            result = run_all_feeds._run_enabled_feed(
                ("alpha", self.config()), full=False
            )

        self.assertEqual(result, ("alpha", True, 3.25))

    def test_summary_ranks_slowest_generators(self):
        with self.assertLogs(run_all_feeds.logger, level="INFO") as caught:
            run_all_feeds._log_generation_summary(
                ["fast", "medium", "slow"],
                [],
                [],
                [],
                [("fast", 1.0), ("slow", 3.2), ("medium", 2.1)],
                normalization_ok=True,
            )

        output = "\n".join(caught.output)
        self.assertLess(output.index("slow: 3.2s"), output.index("medium: 2.1s"))
        self.assertLess(output.index("medium: 2.1s"), output.index("fast: 1.0s"))


if __name__ == "__main__":
    unittest.main()