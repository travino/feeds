"""Run feed generators listed in ``feeds.yaml``.

Generators run in isolated subprocesses so one failure never prevents the
remaining feeds from being attempted. Batch runs use bounded concurrency because
most generator time is spent waiting on independent network sources. The command
exits non-zero when any enabled generator fails or a registry entry is invalid;
the workflow publishes successful partial results before applying that final
failure gate.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

from models import FeedConfig, load_feed_registry
from normalize_feed_self_links import normalize_feed_self_links
from utils import write_atomically
from validate_feeds import validate_feed, validate_json_sidecar

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Per-generator wall clock. Each child is isolated, so a stalled DNS lookup or a
# native client ignoring its own socket timeout costs that feed rather than the
# whole batch. Eight minutes is intentionally generous for one source.
GENERATOR_TIMEOUT = float(os.environ.get("FEEDSEEK_GENERATOR_TIMEOUT", "480"))
DEFAULT_GENERATOR_WORKERS = 4
SLOWEST_GENERATORS_LIMIT = 10


def _configured_generator_workers() -> int:
    """Return a bounded worker count, falling back safely on invalid input."""
    raw = os.environ.get("FEEDSEEK_GENERATOR_WORKERS", str(DEFAULT_GENERATOR_WORKERS))
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning(
            "Invalid FEEDSEEK_GENERATOR_WORKERS=%r; using default of %d",
            raw,
            DEFAULT_GENERATOR_WORKERS,
        )
        return DEFAULT_GENERATOR_WORKERS


# Feed generation is overwhelmingly network-bound. Four workers keeps enough
# requests in flight to hide source latency without turning the scheduled job
# into a thundering herd; override locally/temporarily when profiling.
GENERATOR_WORKERS = _configured_generator_workers()
FEEDS_DIR = Path(__file__).resolve().parent.parent / "feeds"


def _pair_paths(feed_name: str) -> tuple[Path, Path]:
    xml_path = FEEDS_DIR / f"feed_{feed_name}.xml"
    return xml_path, xml_path.with_suffix(".json")


def _snapshot_feed_pair(feed_name: str) -> dict[Path, bytes | None]:
    """Keep the parent's last-known-good pair while a child generator runs."""
    return {
        path: path.read_bytes() if path.exists() else None
        for path in _pair_paths(feed_name)
    }


def _restore_feed_pair(snapshot: dict[Path, bytes | None]) -> None:
    """Restore both artifacts after a failed/timed-out child process."""
    for path, data in snapshot.items():
        if data is None:
            path.unlink(missing_ok=True)
            continue
        write_atomically(path, lambda target, payload=data: target.write_bytes(payload))


def _feed_pair_is_valid(feed_name: str) -> bool:
    """Check one generated pair before the parent accepts child success."""
    xml_path, json_path = _pair_paths(feed_name)
    if not xml_path.exists():
        logger.error("Generator %s returned success without an XML artifact", feed_name)
        return False
    xml_result = validate_feed(xml_path)
    if xml_result["status"] in {"ERROR", "EMPTY"}:
        logger.error("Generator %s produced invalid XML: %s", feed_name, xml_result["message"])
        return False
    json_result = validate_json_sidecar(
        json_path, expected_count=xml_result["item_count"]
    )
    if json_result["status"] != "OK":
        logger.error("Generator %s produced invalid JSON Feed: %s", feed_name, json_result["message"])
        return False
    return True


def _reject_feed_update(
    feed_name: str, snapshot: dict[Path, bytes | None], message: str, *args
) -> bool:
    logger.error(message, *args)
    _restore_feed_pair(snapshot)
    logger.info("Restored last-known-good XML + JSON pair for %s", feed_name)
    return False


def run_feed(feed_name: str, config: FeedConfig, full: bool = False) -> bool:
    """Run one generator in a subprocess and relay all captured diagnostics."""
    generators_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(generators_dir, config.script)
    invoker_path = os.path.join(generators_dir, "invoke_generator.py")
    cmd = [sys.executable, invoker_path, script_path]
    if full:
        cmd.append("--full")

    snapshot = _snapshot_feed_pair(feed_name)
    logger.info("Running %s: %s", feed_name, script_path)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=GENERATOR_TIMEOUT
        )
    except subprocess.TimeoutExpired as exc:
        # subprocess.run has already killed the child by this point.
        for stream, label in ((exc.stdout, "stdout"), (exc.stderr, "stderr")):
            if stream and stream.strip():
                logger.warning("[%s %s before timeout]\n%s", feed_name, label, stream.rstrip())
        return _reject_feed_update(
            feed_name,
            snapshot,
            "Generator %s exceeded %.0fs and was killed",
            feed_name,
            GENERATOR_TIMEOUT,
        )

    if result.stdout.strip():
        logger.info("[%s stdout]\n%s", feed_name, result.stdout.rstrip())
    if result.stderr.strip():
        log = logger.warning if result.returncode == 0 else logger.error
        log("[%s stderr]\n%s", feed_name, result.stderr.rstrip())

    if result.returncode != 0:
        return _reject_feed_update(
            feed_name,
            snapshot,
            "Generator %s exited with status %d",
            feed_name,
            result.returncode,
        )
    if not _feed_pair_is_valid(feed_name):
        return _reject_feed_update(
            feed_name, snapshot, "Generator %s failed the XML + JSON pair check", feed_name
        )

    logger.info("Successfully ran: %s", feed_name)
    return True


def normalize_generated_feeds() -> bool:
    """Normalize generated feed metadata after generators finish writing feeds."""
    try:
        changed = normalize_feed_self_links()
    except OSError as exc:
        logger.error("Could not normalize generated feed metadata: %s", exc)
        return False
    if changed:
        logger.info(
            "Normalized feed metadata in: %s",
            ", ".join(path.name for path in changed),
        )
    return True


def _run_named_feed(
    feed: str,
    registry: dict[str, FeedConfig],
    skipped_configs: list[str],
    *,
    full: bool,
) -> int:
    """Run one named feed after resolving registry state."""
    if feed not in registry:
        if feed in skipped_configs:
            logger.error("Feed '%s' has an invalid config in feeds.yaml", feed)
        else:
            logger.error(
                "Feed '%s' not found in registry. Available: %s",
                feed,
                ", ".join(sorted(registry)),
            )
        return 1

    config = registry[feed]
    if not config.enabled:
        logger.warning("Feed '%s' is disabled in feeds.yaml", feed)
        return 1

    run_ok = run_feed(feed, config, full=full)
    normalize_ok = normalize_generated_feeds()
    return 0 if run_ok and normalize_ok else 1


def _log_generation_summary(
    successful_scripts: list[str],
    failed_scripts: list[str],
    skipped_scripts: list[str],
    skipped_configs: list[str],
    generation_times: list[tuple[str, float]],
    *,
    normalization_ok: bool,
) -> None:
    """Log the batch outcome and the slowest generators."""
    logger.info("\n%s", "=" * 60)
    logger.info("Feed Generation Summary:")
    logger.info("  Successful: %d", len(successful_scripts))
    logger.info("  Failed: %d", len(failed_scripts))
    logger.info("  Skipped (disabled/filtered): %d", len(skipped_scripts))
    logger.info("  Invalid configs (skipped): %d", len(skipped_configs))
    logger.info("  Metadata normalization: %s", "ok" if normalization_ok else "failed")

    if generation_times:
        slowest = sorted(generation_times, key=lambda item: (-item[1], item[0]))[
            :SLOWEST_GENERATORS_LIMIT
        ]
        logger.info("\nSlowest generators:")
        for name, elapsed in slowest:
            logger.info("  %s: %.1fs", name, elapsed)

    for heading, names, level, marker in (
        ("Failed feeds", failed_scripts, logger.error, "✗"),
        ("Invalid feed configs in feeds.yaml", skipped_configs, logger.error, "⚠"),
        ("Skipped feeds", skipped_scripts, logger.info, "○"),
    ):
        if not names:
            continue
        level("\n%s:", heading)
        for name in names:
            level("  %s %s", marker, name)
    logger.info("%s\n", "=" * 60)


def _run_enabled_feed(
    item: tuple[str, FeedConfig], *, full: bool
) -> tuple[str, bool, float]:
    """Run one enabled registry entry and report its wall-clock duration."""
    name, config = item
    started = time.perf_counter()
    ok = run_feed(name, config, full=full)
    elapsed = time.perf_counter() - started
    logger.info("Completed %s in %.1fs", name, elapsed)
    return name, ok, elapsed


def _run_registry(
    registry: dict[str, FeedConfig],
    skipped_configs: list[str],
    *,
    full: bool,
) -> int:
    """Run every enabled registry entry and report the aggregate status."""
    failed_scripts: list[str] = []
    successful_scripts: list[str] = []
    skipped_scripts: list[str] = []
    generation_times: list[tuple[str, float]] = []
    enabled_feeds: list[tuple[str, FeedConfig]] = []

    for name, config in sorted(registry.items()):
        if not config.enabled:
            logger.info("Skipping disabled feed: %s", name)
            skipped_scripts.append(name)
            continue
        enabled_feeds.append((name, config))

    if enabled_feeds:
        worker_count = min(GENERATOR_WORKERS, len(enabled_feeds))
        logger.info(
            "Running %d enabled feeds with %d worker%s",
            len(enabled_feeds),
            worker_count,
            "" if worker_count == 1 else "s",
        )
        runner = partial(_run_enabled_feed, full=full)
        if worker_count == 1:
            outcomes = map(runner, enabled_feeds)
        else:
            with ThreadPoolExecutor(
                max_workers=worker_count, thread_name_prefix="feedseek"
            ) as pool:
                outcomes = list(pool.map(runner, enabled_feeds))

        for name, ok, elapsed in outcomes:
            target = successful_scripts if ok else failed_scripts
            target.append(name)
            generation_times.append((name, elapsed))

    normalization_ok = normalize_generated_feeds()
    _log_generation_summary(
        successful_scripts,
        failed_scripts,
        skipped_scripts,
        skipped_configs,
        generation_times,
        normalization_ok=normalization_ok,
    )
    return 1 if failed_scripts or skipped_configs or not normalization_ok else 0


def run_all_feeds(
    feed: str | None = None,
    full: bool = False,
) -> int:
    """Run generators from the registry and return a truthful process status."""
    registry, skipped_configs = load_feed_registry(return_skipped=True)
    if feed:
        return _run_named_feed(feed, registry, skipped_configs, full=full)
    return _run_registry(registry, skipped_configs, full=full)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run RSS feed generators")
    parser.add_argument("--feed", type=str, help="Run one feed by registry name")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Pass --full to generators",
    )
    args = parser.parse_args()

    sys.exit(run_all_feeds(feed=args.feed, full=args.full))
