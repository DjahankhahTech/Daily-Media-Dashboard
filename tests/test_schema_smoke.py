"""Step-1 smoke tests: the DB initializes, seeds, and round-trips a write."""

from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine, select

from ccmd_dashboard.ccmd_loader import load_ccmd_definitions
from ccmd_dashboard.feed_loader import load_feed_definitions
from ccmd_dashboard.models import (
    CCMD,
    AnalystAction,
    AnalystNote,
    Article,
    ArticleCCMD,
    Feed,
    MDMAssessment,
    MDMCategory,
)


def _fresh_engine(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'smoke.db'}")
    SQLModel.metadata.create_all(engine)
    return engine


def test_yaml_configs_parse() -> None:
    ccmds = load_ccmd_definitions()
    feeds = load_feed_definitions()
    codes = {c.code for c in ccmds}
    # All 11 CCMDs must be present.
    assert codes == {
        "AFRICOM", "CENTCOM", "EUCOM", "INDOPACOM", "NORTHCOM", "SOUTHCOM",
        "SPACECOM", "STRATCOM", "CYBERCOM", "SOCOM", "TRANSCOM",
    }
    # At least four must have populated keyword lists (build step 1 floor).
    populated = [c for c in ccmds if c.all_keywords]
    assert len(populated) >= 4
    # Feed catalog must distinguish tiers and flag state-affiliated.
    assert any(f.source_tier == 1 for f in feeds)
    assert any(f.source_tier == 2 for f in feeds)
    assert any(f.source_tier == 3 for f in feeds)
    assert any(f.state_affiliation == "RU" for f in feeds)


def test_article_round_trip(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    with Session(engine) as s:
        s.add(CCMD(code="INDOPACOM", name="Indo-Pacific"))
        feed = Feed(name="Test", url="https://example.com/rss", source_tier=2)
        s.add(feed)
        s.commit()
        s.refresh(feed)

        art = Article(
            feed_id=feed.id,
            url="https://example.com/a1",
            title="Test headline",
            content_hash="deadbeef",
            raw_text="body",
        )
        s.add(art)
        s.commit()
        s.refresh(art)

        s.add(
            ArticleCCMD(
                article_id=art.id,
                ccmd_code="INDOPACOM",
                match_score=0.42,
                matched_terms=["PLA", "Taiwan Strait"],
            )
        )
        s.add(
            MDMAssessment(
                article_id=art.id,
                classifier_version="stub-0.1",
                concern_score=17,
                category=MDMCategory.LIKELY_RELIABLE,
                reasoning_breakdown={"sub_signals": [], "total": 17},
            )
        )
        s.add(
            AnalystNote(
                article_id=art.id,
                analyst_id="demo",
                observation="nominal",
                action_taken=AnalystAction.REVIEWED,
            )
        )
        s.commit()

        round_trip = s.exec(select(ArticleCCMD)).one()
        assert round_trip.matched_terms == ["PLA", "Taiwan Strait"]
        assert s.exec(select(MDMAssessment)).one().reasoning_breakdown["total"] == 17
        assert s.exec(select(AnalystNote)).one().observation == "nominal"


def test_handling_fields_default_unclassified(tmp_path: Path) -> None:
    """Schema-ready classification markings must default to 'U' and leave
    the other fields nullable (populated later by classified port)."""
    engine = _fresh_engine(tmp_path)
    with Session(engine) as s:
        feed = Feed(name="Test2", url="https://example.com/rss2", source_tier=1)
        s.add(feed)
        s.commit()
        s.refresh(feed)
        art = Article(
            feed_id=feed.id,
            url="https://example.com/b",
            title="t",
            content_hash="x",
        )
        s.add(art)
        s.commit()
        s.refresh(art)
        assert art.classification_marking == "U"
        assert art.handling_caveat is None
        assert art.dissemination_controls is None
        assert art.source_reliability is None
        assert art.info_credibility is None
