"""Smoke test for the demo loader: 50 articles, all CCMDs touched, MDM
ran against the stub, and the resulting DB survives a UI request."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from ccmd_dashboard.models import (
    Article,
    ArticleCCMD,
    CCMD,
    Feed,
    MDMAssessment,
)


def test_build_demo_dataset(tmp_path: Path, monkeypatch) -> None:
    from ccmd_dashboard import db as db_module
    from ccmd_dashboard.demo import build_demo_dataset

    eng = create_engine(
        f"sqlite:///{tmp_path / 'demo.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(db_module, "_engine", eng)

    stats = build_demo_dataset(run_mdm=True)

    # 50 articles per the dataset, every one tagged, every one assessed.
    assert stats["articles"] == 50
    assert stats["tagged"] >= 30  # at least the majority have an AOR match
    assert stats["assessed"] == 50

    with Session(eng) as s:
        # 11 CCMDs seeded.
        assert s.exec(select(CCMD)).all().__len__() == 11
        # Feeds seeded from yaml (state-affiliated entries included).
        feeds = s.exec(select(Feed)).all()
        assert any(f.state_affiliation == "RU" for f in feeds)
        assert any(f.state_affiliation == "CN" for f in feeds)
        # Assessments: one per article, with a populated reasoning breakdown.
        assessments = list(s.exec(select(MDMAssessment)).all())
        assert len(assessments) == 50
        assert all(
            a.reasoning_breakdown.get("sub_signals") for a in assessments
        )
        # At least one article tagged to INDOPACOM.
        indo_hits = list(
            s.exec(select(ArticleCCMD).where(ArticleCCMD.ccmd_code == "INDOPACOM")).all()
        )
        assert indo_hits, "no INDOPACOM tags in demo dataset"
        # At least one unassigned (Premier League / VC / Bank of Canada).
        tagged_article_ids = {
            r for r in s.exec(select(ArticleCCMD.article_id).distinct()).all()
        }
        article_ids = {a.id for a in s.exec(select(Article)).all()}
        assert len(article_ids - tagged_article_ids) >= 1


def test_demo_ui_loads_ccmd_tab(tmp_path: Path, monkeypatch) -> None:
    """After building the demo DB, the INDOPACOM tab must render with at
    least one article (end-to-end sanity for the walk-through)."""
    from ccmd_dashboard import db as db_module
    from ccmd_dashboard.demo import build_demo_dataset
    from ccmd_dashboard.web.app import create_app

    eng = create_engine(
        f"sqlite:///{tmp_path / 'demo-ui.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(db_module, "_engine", eng)
    build_demo_dataset(run_mdm=False)  # faster; MDM not needed for this test

    client = TestClient(create_app())
    r = client.get("/ccmd/INDOPACOM")
    assert r.status_code == 200
    # Banner always visible.
    from ccmd_dashboard.constants import BANNER_TEXT
    assert BANNER_TEXT in r.text
    # At least one INDOPACOM headline from the demo dataset shows up.
    assert "Talisman Sabre" in r.text or "Taiwan Strait" in r.text
