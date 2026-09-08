"""Bounded llms.txt discovery helpers for Feedseek's manual source scout."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

MAX_LLMS_BYTES = 192_000
MAX_LLMS_LINKS = 160
DEFAULT_CANDIDATE_LIMIT = 8

_LINK_RE = re.compile(
    r'^\s*[-*+]\s+\[([^\]\n]{1,300})\]\(([^)\s]+)(?:\s+["\'][^"\']*["\'])?\)'
    r'(?:\s*:\s*(.*))?\s*$'
)


@dataclass(frozen=True, slots=True)
class LlmsCandidate:
    title: str
    url: str
    section: str | None
    description: str | None
    score: int


def llms_url_for(value: str) -> str:
    """Resolve a site/docs URL to the most-specific llms.txt candidate."""
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("invalid site URL")
    path = parsed.path or "/"
    if not path.lower().endswith("/llms.txt"):
        if not path.endswith("/"):
            path += "/"
        path += "llms.txt"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _llms_urls_for(value: str) -> list[str]:
    specific = llms_url_for(value)
    parsed = urlsplit(specific)
    origin = urlunsplit((parsed.scheme, parsed.netloc, "/llms.txt", "", ""))
    return [specific] if specific == origin else [specific, origin]


def _safe_web_url(value: str, base: str) -> str | None:
    try:
        parsed = urlsplit(urljoin(base, value))
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def _candidate_score(title: str, url: str, section: str | None, description: str | None) -> int:
    title_text = title.lower()
    section_text = (section or "").lower()
    description_text = (description or "").lower()
    parsed = urlsplit(url)
    path = parsed.path.lower()
    haystack = " ".join((title_text, section_text, description_text, path))

    score = 0
    if re.search(r"(?:^|[._/-])(rss|atom|feed)(?:[._/-]|$)", path):
        score += 130
    if path.endswith((".rss", ".atom", ".xml")):
        score += 130
    if any(token in haystack for token in ("rss", "atom", "json feed", "syndication")):
        score += 110
    if any(token in haystack for token in ("changelog", "release notes", "releases", "what's new", "whats new")):
        score += 85
    if any(token in haystack for token in ("blog", "newsroom", "news", "announcements", "updates")):
        score += 70
    if any(token in haystack for token in ("developer", "docs", "documentation", "api")):
        score += 20
    if section_text.strip() == "optional":
        score -= 15
    return max(score, 0)


def parse_llms_candidates(content: str, source_url: str, limit: int = DEFAULT_CANDIDATE_LIMIT) -> list[LlmsCandidate]:
    """Parse and rank feed-relevant links from an llms.txt document."""
    section: str | None = None
    candidates: list[LlmsCandidate] = []
    seen: set[str] = set()

    for line in content.lstrip("\ufeff").splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            section = heading.group(1).strip()
            continue
        match = _LINK_RE.match(line)
        if not match:
            continue
        target = _safe_web_url(match.group(2), source_url)
        if not target or target in seen:
            continue
        seen.add(target)
        title = match.group(1).strip()
        description = (match.group(3) or "").strip() or None
        score = _candidate_score(title, target, section, description)
        if score <= 0:
            continue
        candidates.append(LlmsCandidate(title, target, section, description, score))
        if len(seen) >= MAX_LLMS_LINKS:
            break

    candidates.sort(key=lambda item: (-item.score, item.title.lower(), item.url))
    return candidates[:limit]


def _bounded_text(response: requests.Response) -> str:
    declared = response.headers.get("content-length")
    if declared:
        try:
            declared_size = int(declared)
        except ValueError:
            declared_size = 0
        if declared_size > MAX_LLMS_BYTES:
            raise ValueError("llms.txt too large")

    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=16_384):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_LLMS_BYTES:
            raise ValueError("llms.txt too large")
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8-sig")


def discover_llms_candidates(
    site_url: str,
    *,
    limit: int = DEFAULT_CANDIDATE_LIMIT,
    session=requests,
) -> list[LlmsCandidate]:
    """Fetch specific and origin llms.txt indexes and rank feed/content candidates."""
    found: dict[str, LlmsCandidate] = {}
    for index_url in _llms_urls_for(site_url):
        response = session.get(
            index_url,
            timeout=12,
            headers={"Accept": "text/plain, text/markdown;q=0.9, */*;q=0.1"},
            stream=True,
        )
        if response.status_code == 404:
            continue
        response.raise_for_status()
        candidates = parse_llms_candidates(
            _bounded_text(response),
            response.url or index_url,
            limit=MAX_LLMS_LINKS,
        )
        for candidate in candidates:
            current = found.get(candidate.url)
            if current is None or candidate.score > current.score:
                found[candidate.url] = candidate

    candidates = sorted(found.values(), key=lambda item: (-item.score, item.title.lower(), item.url))
    return candidates[:limit]
