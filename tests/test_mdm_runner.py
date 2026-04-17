"""End-to-end MDM pipeline test (stub classifier, no network).

Covers:
  * assess_article writes a full MDMAssessment row (category, score,
    reasoning_breakdown with sub_signals).
  * The /articles/{id}/assess POST route produces the same result.
  * Re-assessing an article appends a new row (audit trail), doesn't
    overwrite.
"""

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from ccmd_dashboard.models import (
    Article,
    CCMD,
    Feed,
    MDMAssessment,
    MDMCategory,
)


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch):
    from ccmd_dashboard import db as db_module

    eng = create_engine(
        f"sqlite:///{tmp_path / 'mdm.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(db_module, "_engine", eng)
    return eng


@pytest.fixture()
def seeded(isolated_db):
    with Session(isolated_db) as s:
        s.add(CCMD(code="CENTCOM", name="U.S. Central Command"))
        feed = Feed(name="DoD News", url="https://example.test/dod", source_tier=1)
        state_feed = Feed(
            name="TASS", url="https://example.test/tass",
            source_tier=3, state_affiliation="RU",
        )
        s.add_all([feed, state_feed])
        s.commit()
        s.refresh(feed)
        s.refresh(state_feed)

        a1 = Article(
            feed_id=feed.id, url="https://example.test/a1",
            title="CENTCOM interdicts Houthi drones in Red Sea",
            content_hash="aaa",
            published_at=datetime(2026, 4, 14),
            raw_text=(
                "U.S. Central Command announced that U.S. forces intercepted "
                "multiple one-way attack drones over the Red Sea on Monday. "
                "According to CENTCOM, the operation was routine. Officials "
                "said no casualties were reported."
            ),
        )
        a2 = Article(
            feed_id=state_feed.id, url="https://example.test/a2",
            title="Western puppet regime unleashes catastrophic attack",
            content_hash="bbb",
            published_at=datetime(2026, 4, 14),
            raw_text=(
                "Foreign agents planted the device. NATO coordinated the "
                "provocation. The operation was vile and reckless. Either "
                "sanctions continue or peace returns. Civilians were "
                "deliberately targeted."
            ),
        )
        s.add_all([a1, a2])
        s.commit()
        s.refresh(a1)
        s.refresh(a2)
        return {"tier1_article_id": a1.id, "state_article_id": a2.id}


def test_assess_tier1_article_produces_low_concern(seeded, isolated_db) -> None:
    from ccmd_dashboard.classify.mdm_runner import assess_article

    with Session(isolated_db) as s:
        result = assess_article(s, seeded["tier1_article_id"])
        s.refresh(result)

    assert result.concern_score is not None
    assert result.concern_score <= 50
    assert result.category in (
        MDMCategory.LIKELY_RELIABLE,
        MDMCategory.REQUIRES_VERIFICATION,
    )
    # Reasoning breakdown must be populated with all sub-signals.
    sub = result.reasoning_breakdown.get("sub_signals", [])
    assert {s["name"] for s in sub} >= {
        "source_tier", "state_affiliation", "source_transparency",
        "corroboration",
    }
    assert result.reasoning_breakdown["total"] == result.concern_score
    assert result.failure_reason is None


def test_assess_state_propaganda_style_article_scores_high(seeded, isolated_db) -> None:
    from ccmd_dashboard.classify.mdm_runner import assess_article

    with Session(isolated_db) as s:
        result = assess_article(s, seeded["state_article_id"])
        s.refresh(result)

    assert result.concern_score is not None
    # Tier-3 RU-affiliated + many unsourced + emotional + fallacy pattern
    # + no corroboration lands in the upper half.
    assert result.concern_score >= 60
    assert result.category in (
        MDMCategory.SIGNIFICANT_CONCERNS,
        MDMCategory.HIGH_CONCERN,
    )
    # Confirm the state_affiliation sub-signal contributed.
    sub = {s["name"]: s for s in result.reasoning_breakdown["sub_signals"]}
    assert sub["state_affiliation"]["contribution"] > 0
    assert sub["state_affiliation"]["value"] == "RU"


def test_assess_route_roundtrip(seeded, isolated_db) -> None:
    from ccmd_dashboard.web.app import create_app

    client = TestClient(create_app())
    r = client.post(
        f"/articles/{seeded['tier1_article_id']}/assess",
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert f"/articles/{seeded['tier1_article_id']}" in r.headers["location"]

    with Session(isolated_db) as s:
        rows = list(
            s.exec(
                select(MDMAssessment).where(
                    MDMAssessment.article_id == seeded["tier1_article_id"]
                )
            ).all()
        )
        assert len(rows) == 1
        assert rows[0].reasoning_breakdown["total"] == rows[0].concern_score


def test_reassess_appends_new_row(seeded, isolated_db) -> None:
    from ccmd_dashboard.classify.mdm_runner import assess_article

    with Session(isolated_db) as s:
        first = assess_article(s, seeded["tier1_article_id"])
        second = assess_article(s, seeded["tier1_article_id"])
        assert first.id != second.id
        rows = list(
            s.exec(
                select(MDMAssessment).where(
                    MDMAssessment.article_id == seeded["tier1_article_id"]
                )
            ).all()
        )
        assert len(rows) == 2


def test_missing_article_raises_lookup_error(seeded, isolated_db) -> None:
    from ccmd_dashboard.classify.mdm_runner import assess_article

    with Session(isolated_db) as s:
        with pytest.raises(LookupError):
            assess_article(s, 99999)
