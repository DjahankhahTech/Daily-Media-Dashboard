"""Smoke tests: every tab renders, banner is present on every page,
filter parameters round-trip, and article detail works."""

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from ccmd_dashboard.constants import BANNER_TEXT
from ccmd_dashboard.models import (
    AnalystAction,
    AnalystNote,
    Article,
    ArticleCCMD,
    CCMD,
    Feed,
    MDMAssessment,
    MDMCategory,
)


@pytest.fixture(scope="module")
def app_with_fixtures(tmp_path_factory):
    from ccmd_dashboard import db as db_module
    from ccmd_dashboard.web import app as web_app

    tmp = tmp_path_factory.mktemp("web-smoke")
    db_path = tmp / "smoke.db"
    eng = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    db_module._engine = eng  # swap the singleton for the test DB

    with Session(eng) as s:
        s.add_all([
            CCMD(code="INDOPACOM", name="U.S. Indo-Pacific Command"),
            CCMD(code="CENTCOM", name="U.S. Central Command"),
            CCMD(code="CYBERCOM", name="U.S. Cyber Command",
                 aor_type=__import__("ccmd_dashboard.models", fromlist=["AORType"]).AORType.FUNCTIONAL),
        ])
        feed_usg = Feed(name="DoD News", url="https://example.test/dod", source_tier=1)
        feed_state = Feed(name="TASS", url="https://example.test/tass",
                          source_tier=3, state_affiliation="RU")
        # Neutral tier-3 feed used for an article whose fixture deliberately
        # inserts no ArticleCCMD row, so the Unassigned tab has something
        # to render.
        feed_neutral = Feed(name="Local Weather", url="https://example.test/wx",
                            source_tier=3)
        s.add_all([feed_usg, feed_state, feed_neutral])
        s.commit()
        s.refresh(feed_usg)
        s.refresh(feed_state)
        s.refresh(feed_neutral)

        # 1 tagged article, 1 untagged (unassigned), 1 with an MDM assessment.
        a1 = Article(feed_id=feed_usg.id, url="https://example.test/a1",
                     title="INDOPACOM announces Talisman Sabre",
                     content_hash="aaa", published_at=datetime(2026, 4, 1))
        a2 = Article(feed_id=feed_neutral.id, url="https://example.test/a2",
                     title="Unrelated story about weather",
                     content_hash="bbb")
        a3 = Article(feed_id=feed_usg.id, url="https://example.test/a3",
                     title="CENTCOM interdiction in Red Sea",
                     content_hash="ccc")
        s.add_all([a1, a2, a3])
        s.commit()
        for a in (a1, a2, a3):
            s.refresh(a)

        s.add(ArticleCCMD(article_id=a1.id, ccmd_code="INDOPACOM",
                          match_score=0.42, matched_terms=["Talisman Sabre"]))
        s.add(ArticleCCMD(article_id=a3.id, ccmd_code="CENTCOM",
                          match_score=0.55, matched_terms=["Red Sea"]))
        s.add(MDMAssessment(
            article_id=a3.id, classifier_version="stub-0.1",
            concern_score=22, category=MDMCategory.LIKELY_RELIABLE,
            reasoning_breakdown={
                "sub_signals": [{
                    "name": "source_tier", "value": 1, "weight": 0,
                    "contribution": 0, "explanation": "Tier 1 USG feed",
                }],
                "total": 22,
            },
        ))
        s.add(AnalystNote(
            article_id=a1.id, analyst_id="demo",
            observation="PLA responded with notional exercise",
            significance="baseline",
            recommended_action="monitor",
            action_taken=AnalystAction.REVIEWED,
        ))
        s.commit()

    app = web_app.create_app()
    yield TestClient(app)


def _assert_banner(resp) -> None:
    assert BANNER_TEXT in resp.text, "classification banner missing"


def test_home_renders(app_with_fixtures) -> None:
    r = app_with_fixtures.get("/")
    assert r.status_code == 200
    _assert_banner(r)
    assert "Home" in r.text
    assert "INDOPACOM" in r.text


def test_ccmd_tab_renders_and_filters(app_with_fixtures) -> None:
    r = app_with_fixtures.get("/ccmd/INDOPACOM")
    assert r.status_code == 200
    _assert_banner(r)
    assert "Talisman Sabre" in r.text

    r = app_with_fixtures.get("/ccmd/INDOPACOM?tier=3")
    assert "Talisman Sabre" not in r.text  # filtered to tier 3


def test_ccmd_unknown_returns_404(app_with_fixtures) -> None:
    r = app_with_fixtures.get("/ccmd/FOOBAR")
    assert r.status_code == 404


def test_unassigned_tab(app_with_fixtures) -> None:
    r = app_with_fixtures.get("/unassigned")
    assert r.status_code == 200
    _assert_banner(r)
    assert "Unrelated story" in r.text


def test_mdm_queue_shows_assessed_only(app_with_fixtures) -> None:
    r = app_with_fixtures.get("/mdm")
    assert r.status_code == 200
    _assert_banner(r)
    assert "Red Sea" in r.text
    assert "Talisman Sabre" not in r.text


def test_notes_tab(app_with_fixtures) -> None:
    r = app_with_fixtures.get("/notes")
    assert r.status_code == 200
    _assert_banner(r)
    assert "PLA responded" in r.text


def test_about_tab(app_with_fixtures) -> None:
    r = app_with_fixtures.get("/about")
    assert r.status_code == 200
    _assert_banner(r)
    assert "TASS" in r.text  # feed table includes state-affiliated entry
    assert "INDOPACOM" in r.text


def test_article_detail_shows_mdm_breakdown(app_with_fixtures) -> None:
    # a3 has an MDM assessment
    r = app_with_fixtures.get("/articles/3")
    assert r.status_code == 200
    _assert_banner(r)
    assert "source_tier" in r.text  # sub-signal row visible
    assert "Tier 1 USG feed" in r.text


def test_analyst_cookie_roundtrip(app_with_fixtures) -> None:
    r = app_with_fixtures.get("/analyst?analyst_id=ICC-staff&next=/notes",
                              follow_redirects=False)
    assert r.status_code == 303
    assert "ccmd_analyst" in r.cookies or any(
        "ccmd_analyst" in h[1] for h in r.headers.raw if h[0].lower() == b"set-cookie"
    ) or "ccmd_analyst" in str(r.headers.get("set-cookie", ""))


def test_add_note_posts_successfully(app_with_fixtures) -> None:
    r = app_with_fixtures.post(
        "/articles/1/notes",
        data={
            "observation": "follow-up",
            "significance": "baseline",
            "recommended_action": "continue monitoring",
            "action_taken": "flagged_for_oic",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    # Confirm the note is visible on the notes tab afterward.
    listing = app_with_fixtures.get("/notes")
    assert "follow-up" in listing.text
