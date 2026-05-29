"""Run feed generators listed in feeds.yaml.

Each generator is a script in this directory exposing ``main(full: bool)``.
Runs them in isolated subprocesses so one failure never aborts the rest.
Currently the registry holds a single feed (reuters); add more entries to
feeds.yaml and they will be picked up automatically.
"""

import argparse
import logging
import subprocess
import sys
from pathlib import Path

import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
REGISTRY = HERE.parent / "feeds.yaml"


def load_registry() -> dict:
    with open(REGISTRY) as f:
        data = yaml.safe_load(f) or {}
    return data.get("feeds", {})


def run_feed(name: str, config: dict, full: bool = False) -> bool:
    script = HERE / config["script"]
    cmd = [sys.executable, str(script)] + (["--full"] if full else [])
    logger.info(f"Running {name}: {script.name}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        logger.info(f"Successfully ran: {name}")
        return True
    logger.error(f"Error running {name}:\n{result.stderr}")
    return False


def run_all(feed: str | None = None, full: bool = False) -> int:
    registry = load_registry()

    if feed:
        if feed not in registry:
            logger.error(f"Feed '{feed}' not in registry. Available: {', '.join(sorted(registry))}")
            return 1
        return 0 if run_feed(feed, registry[feed], full=full) else 1

    succeeded, failed = [], []
    for name, config in sorted(registry.items()):
        if config.get("enabled", True) is False:
            logger.info(f"Skipping disabled feed: {name}")
            continue
        (succeeded if run_feed(name, config, full=full) else failed).append(name)

    logger.info("=" * 60)
    logger.info(f"Done. Successful: {len(succeeded)}  Failed: {len(failed)}")
    if failed:
        logger.error("Failed feeds: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run RSS/Atom feed generators")
    parser.add_argument("--feed", help="Run a single feed by name (e.g., --feed=reuters)")
    parser.add_argument("--full", action="store_true", help="Full reset instead of incremental")
    args = parser.parse_args()
    sys.exit(run_all(feed=args.feed, full=args.full))
