"""End-to-end pipeline test with a fake Fetcher.

Verifies that:
* new articles are persisted with normalized URLs and content hashes
* a second ingest run doesn't double-insert (URL dedupe)
* an entry whose URL differs but whose normalized title+body matches
  an existing article is rejected (content-hash dedupe)
* an IngestRun row is written for every ingest pass (audit trail)
"""

from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine, select

from ccmd_dashboard.ingest.fetcher import FetchResult
from ccmd_dashboard.ingest.pipeline import ingest_feed
from ccmd_dashboard.models import Article, Feed, IngestRun

FIXTURE = Path(__file__).parent / "fixtures" / "sample_feed.xml"


@dataclass
class FakeFetcher:
    """Minimal fetcher that serves the fixture XML for the feed URL and an
    HTML blurb for every article URL. Avoids network in tests."""

    feed_url: str
    feed_bytes: bytes

    def get(self, url: str) -> FetchResult:
        if url == self.feed_url:
            body = self.feed_bytes
            ctype = "application/rss+xml"
        else:
            body = (
                b"<html><head><title>t</title></head>"
                b"<body><article><p>" + url.encode() + b"</p></article></body></html>"
            )
            ctype = "text/html"
        return FetchResult(
            url=url, status_code=200, content=body,
            content_type=ctype, encoding="utf-8", final_url=url,
        )

    def close(self) -> None:  # match Fetcher's contract
        pass


def _engine(tmp_path: Path):
    eng = create_engine(f"sqlite:///{tmp_path / 'ingest.db'}")
    SQLModel.metadata.create_all(eng)
    return eng


def test_ingest_persists_and_dedupes(tmp_path: Path) -> None:
    eng = _engine(tmp_path)
    fixture_bytes = FIXTURE.read_bytes()

    with Session(eng) as s:
        feed = Feed(name="T", url="https://example.test/rss", source_tier=2)
        s.add(feed)
        s.commit()
        s.refresh(feed)

        fetcher = FakeFetcher(feed_url=feed.url, feed_bytes=fixture_bytes)
        stats = ingest_feed(feed, s, fetcher=fetcher, extract_full=False)
        s.commit()

        assert stats.seen == 3
        assert stats.new == 2  # third entry is a URL duplicate of the first
        assert stats.deduped_by_url == 1

        urls = {a.url for a in s.exec(select(Article)).all()}
        # tracking params stripped, trailing slash preserved correctly
        assert "https://example.test/story/taiwan-strait-exercise" in urls
        assert "https://example.test/story/red-sea-interdiction" in urls

        runs = s.exec(select(IngestRun)).all()
        assert len(runs) == 1
        assert runs[0].articles_new == 2
        assert runs[0].articles_seen == 3

        # Second run over the same feed: nothing new (URL dedupe).
        stats2 = ingest_feed(feed, s, fetcher=fetcher, extract_full=False)
        s.commit()
        assert stats2.new == 0
        assert stats2.deduped_by_url == 3


def test_content_hash_dedupe_blocks_reposted_story(tmp_path: Path) -> None:
    """Same title+body under a different URL must be rejected."""
    eng = _engine(tmp_path)
    with Session(eng) as s:
        feed = Feed(name="T2", url="https://example.test/rss", source_tier=2)
        s.add(feed)
        s.commit()
        s.refresh(feed)

        fetcher = FakeFetcher(feed.url, FIXTURE.read_bytes())
        ingest_feed(feed, s, fetcher=fetcher, extract_full=False)
        s.commit()

        repost = (
            b'<?xml version="1.0"?><rss version="2.0"><channel>'
            b"<title>Mirror</title>"
            b"<item><title>PLA Navy conducts exercises near Taiwan Strait</title>"
            b"<link>https://other.test/amp/taiwan</link>"
            b"<description>Naval exercises reported in the Taiwan Strait today.</description>"
            b"</item></channel></rss>"
        )

        feed.url = "https://other.test/rss"
        s.add(feed)
        s.commit()

        mirror = FakeFetcher("https://other.test/rss", repost)
        stats = ingest_feed(feed, s, fetcher=mirror, extract_full=False)
        s.commit()

        assert stats.seen == 1
        assert stats.new == 0
        assert stats.deduped_by_hash == 1
