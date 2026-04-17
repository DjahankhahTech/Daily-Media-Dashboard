"""Feed + article parsing.

``parse_feed`` turns a raw feed payload into a list of ``FeedItem`` records
(title, url, summary, published_at, author). ``extract_full_text`` calls
trafilatura to pull the article body from the source HTML when the feed
gives us only a summary.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import feedparser

log = logging.getLogger(__name__)


@dataclass
class FeedItem:
    url: str
    title: str
    summary: str = ""
    published_at: Optional[datetime] = None
    author: Optional[str] = None
    language: str = "en"
    raw: dict[str, Any] = field(default_factory=dict)


def _coerce_dt(entry: Any) -> Optional[datetime]:
    """feedparser parses RFC-822/ISO timestamps into a time.struct_time on
    ``published_parsed`` / ``updated_parsed``. Convert to naive UTC."""
    for key in ("published_parsed", "updated_parsed"):
        st = getattr(entry, key, None) or entry.get(key) if isinstance(entry, dict) else getattr(entry, key, None)
        if st:
            try:
                return datetime(*st[:6], tzinfo=timezone.utc).replace(tzinfo=None)
            except (TypeError, ValueError):
                continue
    return None


def _get(entry: Any, key: str, default: str = "") -> str:
    try:
        value = entry[key] if key in entry else getattr(entry, key, default)
    except Exception:
        value = default
    return value or default


def parse_feed(feed_bytes: bytes) -> tuple[dict[str, Any], list[FeedItem]]:
    """Parse an Atom/RSS payload. Returns (feed_meta, items)."""
    parsed = feedparser.parse(feed_bytes)
    meta: dict[str, Any] = {
        "title": getattr(parsed.feed, "title", ""),
        "language": getattr(parsed.feed, "language", "en") or "en",
        "bozo": bool(getattr(parsed, "bozo", False)),
        "bozo_exception": str(getattr(parsed, "bozo_exception", "")) or None,
    }
    items: list[FeedItem] = []
    for entry in parsed.entries:
        url = _get(entry, "link")
        title = _get(entry, "title")
        if not url or not title:
            continue
        summary = _get(entry, "summary") or _get(entry, "description")
        author = _get(entry, "author") or None
        items.append(
            FeedItem(
                url=url.strip(),
                title=title.strip(),
                summary=summary.strip(),
                published_at=_coerce_dt(entry),
                author=author,
                language=meta["language"] or "en",
                raw=dict(entry) if isinstance(entry, dict) else {},
            )
        )
    return meta, items


def extract_full_text(html: bytes, url: str | None = None) -> Optional[str]:
    """Call trafilatura to extract readable article body from HTML.

    Returns None if extraction fails — callers should fall back to the feed
    summary in that case (explicitly, never silently treat missing body as
    empty string).
    """
    try:
        import trafilatura
    except ImportError:  # pragma: no cover - only if ingest extras not installed
        log.warning("trafilatura not installed; skipping full-text extraction")
        return None
    try:
        text = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=False,
            favor_recall=True,
        )
    except Exception as exc:  # trafilatura raises a mix of types; be defensive.
        log.warning("trafilatura extract failed for %s: %s", url, exc)
        return None
    return text
