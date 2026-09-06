"""Invoke one feed generator and translate its ``main`` result to an exit code.

This adapter keeps generator execution isolated while enforcing the project
contract centrally. Older scripts use either ``main(full=False)`` or
``main(full_reset=False)`` and a few forgot to propagate returned failures from
their ``__main__`` blocks. Running through this module makes those failures
visible without requiring every historical generator to be edited at once.
"""

from __future__ import annotations

import argparse
import importlib.util
import inspect
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from entry_identity import ENTRY_ID_FIELD, persist_entry_ids
from feedgen.entry import FeedEntry

PRESERVE_MISSING_DATE = "_feedseek_preserve_missing_date"


@contextmanager
def reuse_requests_connections() -> Iterator[None]:
    """Reuse Requests connections without adding state to top-level helpers.

    Top-level ``requests.get``/``post`` helpers normally create and close a new
    ``Session`` for every call. Generators often make several requests to the
    same origin, so keeping one session per thread lets urllib3 reuse pooled
    TCP/TLS connections while preserving isolation for internally threaded
    generators. Session cookies are cleared around every request so ordinary
    top-level helpers remain stateless; explicit user-created Sessions are
    untouched. The subprocess boundary still gives every feed its own pool.
    """
    import requests
    import requests.api

    original_api_request = requests.api.request
    original_package_request = requests.request
    thread_state = threading.local()
    sessions = []
    sessions_lock = threading.Lock()

    def pooled_request(method, url, **kwargs):
        session = getattr(thread_state, "session", None)
        if session is None:
            session = requests.Session()
            thread_state.session = session
            with sessions_lock:
                sessions.append(session)
        session.cookies.clear()
        try:
            return session.request(method=method, url=url, **kwargs)
        finally:
            session.cookies.clear()

    requests.api.request = pooled_request
    requests.request = pooled_request
    try:
        yield
    finally:
        requests.api.request = original_api_request
        requests.request = original_package_request
        for session in sessions:
            session.close()


def freeze_missing_dates(entries, *, date_field="date", fallback=None):
    """Mutate cache-bound entries so ordinary missing dates become first-seen dates."""
    first_seen = fallback or datetime.now(timezone.utc)
    for entry in entries:
        if entry.get(date_field) is not None or entry.get(PRESERVE_MISSING_DATE):
            continue
        entry[date_field] = first_seen
    return entries


@contextmanager
def freeze_saved_entry_dates() -> Iterator[None]:
    """Prepare cache-bound entries after source merging and deduplication.

    Missing dates are frozen before every save. Entry IDs are different: only a
    generator that actually calls ``utils.make_entry_id`` may seed them, because
    other feeds can publish source GUIDs or raw links instead. Calls are tracked
    for the run; if rendering happens after the cache write, the cache is written
    once more on context exit with the now-proven current IDs.
    """
    import utils

    original_save_cache = utils.save_cache
    original_make_entry_id = utils.make_entry_id
    first_seen = datetime.now(timezone.utc)
    id_feeds: set[str] = set()
    saved_calls: list[tuple[str, list, str, dict]] = []

    def tracked_make_entry_id(feed_name, link):
        entry_id = original_make_entry_id(feed_name, link)
        id_feeds.add(feed_name)
        return entry_id

    def save_cache_with_dates(feed_name, entries, entries_key="entries", **kwargs):
        # **kwargs, not a fixed list: this wrapper replaces utils.save_cache for
        # the whole run, so any argument it does not forward becomes a TypeError
        # at generation time rather than a signature mismatch at import.
        freeze_missing_dates(entries, fallback=first_seen)
        if feed_name in id_feeds:
            persist_entry_ids(
                feed_name,
                entries,
                make_entry_id=original_make_entry_id,
            )
        result = original_save_cache(feed_name, entries, entries_key=entries_key, **kwargs)
        saved_calls.append((feed_name, entries, entries_key, dict(kwargs)))
        return result

    utils.make_entry_id = tracked_make_entry_id
    setattr(utils, "save_cache", save_cache_with_dates)
    try:
        yield
    finally:
        try:
            for feed_name, entries, entries_key, kwargs in saved_calls:
                if feed_name not in id_feeds:
                    continue
                missing = any(
                    entry.get("link") and not entry.get(ENTRY_ID_FIELD)
                    for entry in entries
                )
                if not missing:
                    continue
                persist_entry_ids(
                    feed_name,
                    entries,
                    make_entry_id=original_make_entry_id,
                )
                original_save_cache(
                    feed_name,
                    entries,
                    entries_key=entries_key,
                    **kwargs,
                )
        finally:
            utils.make_entry_id = original_make_entry_id
            utils.save_cache = original_save_cache


@contextmanager
def preserve_atom_publication_dates() -> Iterator[None]:
    """Use ``published`` when Feedgen would invent an entry ``updated`` value.

    Feedgen initializes every new Atom entry with the current time because
    ``updated`` is required by the Atom specification. Track calls to its public
    ``updated(...)`` setter while a generator runs. Immediately before
    serialization, replace only the untouched constructor default with the
    entry's publication date. Explicit update timestamps, including changing
    weather forecasts, remain intact.
    """
    original_updated = FeedEntry.updated
    original_atom_entry = FeedEntry.atom_entry

    def tracked_updated(self, updated=None):
        if updated is not None:
            self._feedseek_explicit_updated = True
        return original_updated(self, updated)

    def atom_entry_with_stable_default(self, extensions=True):
        if not getattr(self, "_feedseek_explicit_updated", False):
            published = self.published()
            if published is not None:
                original_updated(self, published)
        return original_atom_entry(self, extensions=extensions)

    FeedEntry.updated = tracked_updated
    FeedEntry.atom_entry = atom_entry_with_stable_default
    try:
        yield
    finally:
        FeedEntry.updated = original_updated
        FeedEntry.atom_entry = original_atom_entry


@contextmanager
def isolated_argv(script: Path, *, full: bool = False) -> Iterator[None]:
    """Expose only generator arguments while importing and running its module."""
    previous = sys.argv
    sys.argv = [str(script), *(["--full"] if full else [])]
    try:
        yield
    finally:
        sys.argv = previous


def load_module(script: Path):
    module_name = f"feedseek_generator_{script.stem}"
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load generator: {script}")
    module = importlib.util.module_from_spec(spec)
    # Some decorators and runtime type helpers resolve their module through
    # sys.modules while the file is executing, so register it before exec.
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def result_succeeded(result: object) -> bool:
    """Normalize historical generator result conventions."""
    if result is None:
        return True
    if isinstance(result, bool):
        return result
    if isinstance(result, int):
        return result == 0
    return True


def invoke(script: Path, *, full: bool = False) -> bool:
    with (
        reuse_requests_connections(),
        freeze_saved_entry_dates(),
        preserve_atom_publication_dates(),
        isolated_argv(script, full=full),
    ):
        module = load_module(script)
        main = getattr(module, "main", None)
        if not callable(main):
            raise RuntimeError(f"Generator does not expose main(): {script}")
        main_func = cast(Callable[..., object], main)

        parameters = inspect.signature(main_func).parameters
        if not parameters:
            result = main_func()
        elif "full" in parameters:
            result = main_func(full=full)
        elif "full_reset" in parameters:
            result = main_func(full_reset=full)
        else:
            result = main_func(full)

    return result_succeeded(result)


def cli() -> int:
    parser = argparse.ArgumentParser(description="Invoke one feed generator")
    parser.add_argument("script", type=Path)
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    return 0 if invoke(args.script.resolve(), full=args.full) else 1


if __name__ == "__main__":
    try:
        sys.exit(cli())
    except Exception as exc:
        print(f"Generator invocation failed: {exc}", file=sys.stderr)
        raise
