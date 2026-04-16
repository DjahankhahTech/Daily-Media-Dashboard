"""Ingestion pipeline: fetch -> parse -> extract -> dedupe -> persist.

This is the only place in the ingest module that writes to the DB. Keep
fetch/parse/dedupe pure so they can be unit-tested against fixtures.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlmodel import Session, select

from ..config import settings
from ..models import Article, Feed, IngestRun
from .dedupe import content_hash, normalize_url
from .fetcher import Fetcher
from .parser import FeedItem, extract_full_text, parse_feed

log = logging.getLogger(__name__)


@dataclass
class IngestStats:
    feed_name: str
    seen: int = 0
    new: int = 0
    deduped_by_url: int = 0
    deduped_by_hash: int = 0
    extraction_failures: int = 0
    errors: list[str] = field(default_factory=list)

    def as_line(self) -> str:
        return (
            f"{self.feed_name:28s} seen={self.seen:3d} new={self.new:3d} "
            f"dup_url={self.deduped_by_url:3d} dup_hash={self.deduped_by_hash:3d} "
            f"extract_fail={self.extraction_failures:3d}"
        )


def _save_raw(payload: bytes, feed_name: str) -> Optional[Path]:
    """Persist raw feed XML to disk for audit / reprocessing."""
    if not payload:
        return None
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    safe = "".join(c if c.isalnum() else "_" for c in feed_name)[:64]
    dest = settings.raw_feed_dir / f"{safe}__{stamp}.xml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(payload)
    return dest


def _persist_item(
    session: Session,
    feed: Feed,
    item: FeedItem,
    fetcher: Optional[Fetcher],
    extract_full: bool,
    since: Optional[datetime],
    stats: IngestStats,
) -> None:
    stats.seen += 1
    if since is not None and item.published_at is not None and item.published_at < since:
        return

    url_norm = normalize_url(item.url)

    if session.exec(select(Article).where(Article.url == url_norm)).first() is not None:
        stats.deduped_by_url += 1
        return

    body = item.summary or ""
    if extract_full and fetcher is not None:
        try:
            page = fetcher.get(item.url)
        except Exception as exc:
            log.info("full-text fetch failed for %s: %s", item.url, exc)
            stats.extraction_failures += 1
        else:
            extracted = extract_full_text(page.content, url=item.url)
            if extracted:
                body = extracted
            else:
                stats.extraction_failures += 1

    digest = content_hash(item.title, body)
    if session.exec(select(Article).where(Article.content_hash == digest)).first() is not None:
        stats.deduped_by_hash += 1
        return

    session.add(
        Article(
            feed_id=feed.id,
            url=url_norm,
            title=item.title,
            author=item.author,
            published_at=item.published_at,
            raw_text=body or None,
            summary=item.summary or None,
            content_hash=digest,
            language=item.language or feed.language,
        )
    )
    stats.new += 1


def ingest_feed(
    feed: Feed,
    session: Session,
    *,
    fetcher: Optional[Fetcher] = None,
    extract_full: bool = True,
    since: Optional[datetime] = None,
) -> IngestStats:
    """Pull one feed and persist new articles. Always records an IngestRun."""
    stats = IngestStats(feed_name=feed.name)
    run = IngestRun(feed_id=feed.id)
    session.add(run)
    session.flush()

    owns_fetcher = False
    if fetcher is None:
        fetcher = Fetcher()
        owns_fetcher = True

    try:
        result = fetcher.get(feed.url)
        raw_path = _save_raw(result.content, feed.name)
        run.raw_feed_path = str(raw_path) if raw_path else None

        _, items = parse_feed(result.content)
        for item in items:
            _persist_item(session, feed, item, fetcher, extract_full, since, stats)

        feed.last_fetched_at = datetime.utcnow()
    except Exception as exc:
        log.exception("ingest failed for %s", feed.name)
        run.error = f"{type(exc).__name__}: {exc}"
        stats.errors.append(run.error)
    finally:
        run.articles_seen = stats.seen
        run.articles_new = stats.new
        run.finished_at = datetime.utcnow()
        if owns_fetcher:
            fetcher.close()

    return stats


def ingest_all(
    session: Session,
    *,
    feed_name: Optional[str] = None,
    since: Optional[datetime] = None,
    extract_full: bool = True,
) -> list[IngestStats]:
    """Run ingest across every active feed (or a single named feed)."""
    q = select(Feed).where(Feed.active == True)  # noqa: E712
    if feed_name:
        q = q.where(Feed.name == feed_name)
    feeds = list(session.exec(q).all())
    if not feeds:
        log.warning("no active feeds match filter %r", feed_name)
        return []

    results: list[IngestStats] = []
    with Fetcher() as fetcher:
        for feed in feeds:
            stats = ingest_feed(
                feed,
                session,
                fetcher=fetcher,
                extract_full=extract_full,
                since=since,
            )
            session.commit()
            results.append(stats)
    return results
