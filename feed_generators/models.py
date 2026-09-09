"""Pydantic models for feed configuration and settings."""

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError, field_validator

logger = logging.getLogger(__name__)


class FeedConfig(BaseModel):
    """Configuration for a single feed generator."""

    script: str
    blog_url: str
    enabled: bool = True

    @field_validator("script")
    @classmethod
    def script_must_exist(cls, v: str) -> str:
        script_path = Path(__file__).parent / v
        if not script_path.exists():
            msg = f"Script not found: {v}"
            raise ValueError(msg)
        return v


def load_feed_registry(return_skipped: bool = False):
    """Load and validate feeds.yaml.

    Invalid entries are logged and skipped rather than aborting the whole
    load, so one malformed config can never take down every other feed.

    Args:
        return_skipped: If True, return ``(feeds, skipped_names)`` instead of
            just ``feeds``. Defaults to False for backward compatibility.

    Returns:
        Dict mapping feed name to validated FeedConfig (valid entries only),
        or ``(dict, list[str])`` when ``return_skipped`` is True.

    Raises:
        FileNotFoundError: If feeds.yaml is missing.
    """
    registry_path = Path(__file__).parent.parent / "feeds.yaml"
    if not registry_path.exists():
        msg = f"Feed registry not found: {registry_path}"
        raise FileNotFoundError(msg)

    with open(registry_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    feeds: dict[str, FeedConfig] = {}
    skipped: list[str] = []
    for name, config in data.get("feeds", {}).items():
        if not isinstance(config, dict):
            skipped.append(name)
            logger.error(
                "Skipping invalid feed config '%s' in feeds.yaml (expected mapping, got %s)",
                name,
                type(config).__name__,
            )
            continue

        try:
            feeds[name] = FeedConfig(**config)
        except ValidationError as e:
            skipped.append(name)
            errors = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors())
            logger.error(
                "Skipping invalid feed config '%s' in feeds.yaml (%s)", name, errors
            )

    if skipped:
        logger.warning(
            "Loaded %d feed(s); skipped %d invalid: %s",
            len(feeds),
            len(skipped),
            ", ".join(skipped),
        )

    if return_skipped:
        return feeds, skipped
    return feeds
