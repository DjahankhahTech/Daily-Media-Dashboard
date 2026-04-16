"""Tests for the analyst-workflow exports: OIC queue, PDF brief, CSV brief."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

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


@pytest.fixture()
def client_with_note(tmp_path: Path, monkeypatch):
    from ccmd_dashboard import db as db_module
    from ccmd_dashboard.web.app import create_app

    eng = create_engine(
        f"sqlite:///{tmp_path / 'export.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(db_module, "_engine", eng)

    today = datetime.utcnow().replace(hour=12, minute=0, second=0, microsecond=0)
    with Session(eng) as s:
        s.add(CCMD(code="INDOPACOM", name="Indo-Pacific"))
        feed = Feed(name="DoD News", url="https://example.test/dod", source_tier=1)
        s.add(feed)
        s.commit()
        s.refresh(feed)
        article = Article(
            feed_id=feed.id, url="https://example.test/a1",
            title="INDOPACOM exercise with Philippine forces",
            content_hash="aaa",
            published_at=today,
            summary="Routine training activity.",
        )
        s.add(article)
        s.commit()
        s.refresh(article)
        s.add(ArticleCCMD(
            article_id=article.id, ccmd_code="INDOPACOM",
            match_score=0.42, matched_terms=["Philippines"],
        ))
        s.add(MDMAssessment(
            article_id=article.id, classifier_version="stub|scoring-v1",
            concern_score=15, category=MDMCategory.LIKELY_RELIABLE,
            reasoning_breakdown={"sub_signals": [], "total": 15, "category": "likely_reliable"},
        ))
        # One note today flagged for OIC, one reviewed yesterday (must not appear today).
        s.add(AnalystNote(
            article_id=article.id, analyst_id="ICC-staff",
            observation="steady tempo",
            significance="baseline",
            recommended_action="continue monitoring",
            action_taken=AnalystAction.FLAGGED_FOR_OIC,
            created_at=today,
        ))
        s.add(AnalystNote(
            article_id=article.id, analyst_id="demo",
            observation="old note",
            action_taken=AnalystAction.REVIEWED,
            created_at=today - timedelta(days=2),
        ))
        s.commit()

    return TestClient(create_app()), today.date()


def test_oic_queue_lists_flagged(client_with_note) -> None:
    client, _ = client_with_note
    r = client.get("/oic")
    assert r.status_code == 200
    assert BANNER_TEXT in r.text
    assert "steady tempo" in r.text
    assert "ICC-staff" in r.text


def test_csv_export_contains_today_only(client_with_note) -> None:
    client, today = client_with_note
    r = client.get(f"/export/brief.csv?day={today.isoformat()}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    body = r.text
    assert "article_id,title,source_feed" in body  # header row present
    assert "INDOPACOM exercise" in body
    assert "ICC-staff" in body
    assert "flagged_for_oic" in body
    # Yesterday's "reviewed" note is outside the target day and must not appear.
    assert "old note" not in body


def test_pdf_export_produces_pdf(client_with_note) -> None:
    client, today = client_with_note
    r = client.get(f"/export/brief.pdf?day={today.isoformat()}")
    if r.status_code == 501:
        pytest.skip("weasyprint not installed in this environment")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    # Spec-compliant PDFs start with the %PDF- header.
    assert r.content[:5] == b"%PDF-"
    assert "attachment" in r.headers.get("content-disposition", "")


def test_notes_tab_has_export_buttons(client_with_note) -> None:
    client, _ = client_with_note
    r = client.get("/notes")
    assert r.status_code == 200
    assert "Export today's brief (PDF)" in r.text
    assert "Export today's brief (CSV)" in r.text
