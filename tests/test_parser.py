"""Feed parser test against a fixture RSS payload."""

from pathlib import Path

from ccmd_dashboard.ingest.parser import parse_feed

FIXTURE = Path(__file__).parent / "fixtures" / "sample_feed.xml"


def test_parse_feed_yields_entries() -> None:
    meta, items = parse_feed(FIXTURE.read_bytes())
    assert meta["title"] == "Test Defense Feed"
    assert meta["language"] == "en"
    assert len(items) == 3
    first = items[0]
    assert "Taiwan Strait" in first.title
    assert first.url.endswith("/taiwan-strait-exercise")
    assert first.published_at is not None
    assert first.published_at.year == 2026
