"""Demo dataset loader.

``dashboard demo`` drops the current dashboard.db, seeds CCMDs + feeds
from yaml, loads 50 canned articles (``demo_data.jsonl``), runs the AOR
tagger on each, and runs the stub MDM classifier + deterministic scorer
on each. Then starts the web UI. Fully offline.

This is the walkthrough path for OSW leadership when network is not
available or no API key is set.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from .ccmd_loader import load_ccmd_definitions
from .classify.aor_runner import tag_and_store
from .classify.mdm_runner import assess_article
from .classify.stub_classifier import StubClassifier
from .config import settings
from .db import create_all, get_engine
from .feed_loader import load_feed_definitions
from .ingest.dedupe import content_hash, normalize_url
from .models import (
    AnalystAction,
    AnalystNote,
    Article,
    ArticleCCMD,
    CCMD,
    Feed,
    IngestRun,
    MDMAssessment,
)

log = logging.getLogger(__name__)

DATASET_PATH = Path(__file__).resolve().parent / "demo_data.jsonl"


def _wipe(session: Session) -> None:
    """Clear rows but keep schema so Alembic history stays intact."""
    for model in (
        MDMAssessment, ArticleCCMD, AnalystNote, IngestRun, Article, Feed, CCMD,
    ):
        for row in list(session.exec(select(model)).all()):
            session.delete(row)
    session.commit()


def _seed_configs(session: Session) -> None:
    """Seed CCMDs + ALL feeds.

    The demo never fetches from the network, so feeds with ``todo: true``
    (URL unverified for real ingestion) are safe to seed here and let the
    demo dataset reference them. In non-demo flows, init-db skips todo
    feeds to keep them out of the ingestion loop.
    """
    for c in load_ccmd_definitions():
        session.add(CCMD(code=c.code, name=c.name, aor_type=c.aor_type, description=c.description))
    for f in load_feed_definitions():
        session.add(Feed(
            name=f.name, url=f.url, source_tier=f.source_tier,
            state_affiliation=f.state_affiliation,
            language=f.language, notes=f.notes,
            active=not f.todo,  # keep unverified feeds flagged as inactive
        ))
    session.commit()


def _load_articles(session: Session) -> list[int]:
    """Load demo_data.jsonl and return the inserted article IDs.

    URL + content_hash are salted with the row index so that if two rows
    happen to share a title (common in wire-mirror coverage) they don't
    collide on the unique constraints. The URL points at example.test so
    the demo never links out to real sites.
    """
    feeds_by_name = {f.name: f for f in session.exec(select(Feed)).all()}
    inserted: list[int] = []
    for idx, raw in enumerate(DATASET_PATH.read_text().splitlines()):
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        row = json.loads(raw)
        feed = feeds_by_name.get(row["feed"])
        if feed is None:
            log.warning("demo row references unknown feed %r; skipping", row["feed"])
            continue
        published = datetime.fromisoformat(row["published_at"]) if row.get("published_at") else None
        body = row.get("body", "")
        article = Article(
            feed_id=feed.id,
            url=normalize_url(f"https://example.test/demo/{idx}-{feed.id}"),
            title=row["title"],
            published_at=published,
            raw_text=body,
            summary=body[:240] + ("…" if len(body) > 240 else ""),
            content_hash=content_hash(f"{idx}:{row['title']}", body),
            language=feed.language,
        )
        session.add(article)
        session.commit()
        session.refresh(article)
        inserted.append(article.id)
    return inserted


def _add_sample_notes(session: Session, article_ids: list[int]) -> None:
    """Drop a handful of ATP-2 style notes so Notes/OIC/export tabs have
    realistic content on first load."""
    if not article_ids:
        return
    rng = random.Random(42)
    picks = rng.sample(article_ids, min(5, len(article_ids)))
    vignettes = [
        ("demo", AnalystAction.REVIEWED,
         "Narrative consistent with prior 48h.", "Baseline.", "Continue monitoring."),
        ("ICC-staff", AnalystAction.FLAGGED_FOR_OIC,
         "State-media framing diverges markedly from wire coverage.",
         "Possible propaganda vector.",
         "Brief OIC at next sync; request additional corroboration."),
        ("OSW-staff", AnalystAction.REVIEWED,
         "Routine training activity with allied forces.",
         "No change to indicator set.",
         "File for weekly roll-up."),
        ("watch-floor-1", AnalystAction.ESCALATED,
         "Kinetic event in CENTCOM AOR with potential escalation path.",
         "Watch for follow-on.",
         "Escalate to OSW section chief."),
        ("demo", AnalystAction.REVIEWED,
         "Attribution ambiguity; single-source.", "Requires verification.",
         "Hold for corroborating wire."),
    ]
    for article_id, (who, action, obs, sig, rec) in zip(picks, vignettes):
        session.add(AnalystNote(
            article_id=article_id, analyst_id=who,
            observation=obs, significance=sig, recommended_action=rec,
            action_taken=action,
        ))
    session.commit()


def build_demo_dataset(run_mdm: bool = True) -> dict:
    """Drop current data, load the demo dataset, tag, and assess.

    Returns a small stats dict for CLI display.
    """
    create_all()
    eng = get_engine()
    stats = {"articles": 0, "tagged": 0, "tags_written": 0, "assessed": 0}
    classifier = StubClassifier()

    with Session(eng) as s:
        _wipe(s)
        _seed_configs(s)
        article_ids = _load_articles(s)
        stats["articles"] = len(article_ids)

        for aid in article_ids:
            article = s.get(Article, aid)
            rows = tag_and_store(s, article, recompute=True)
            s.commit()
            if rows:
                stats["tagged"] += 1
                stats["tags_written"] += len(rows)

        # Source-based best-guess for anything the keyword tagger missed.
        from .classify.best_guess import best_guess_untagged
        _, bg_written = best_guess_untagged(s)
        stats["tags_written"] += bg_written

        if run_mdm:
            for aid in article_ids:
                try:
                    assess_article(s, aid, classifier=classifier)
                    stats["assessed"] += 1
                except Exception as exc:  # keep going even if one row errors
                    log.warning("demo assess failed for %s: %s", aid, exc)

        _add_sample_notes(s, article_ids)

    return stats
