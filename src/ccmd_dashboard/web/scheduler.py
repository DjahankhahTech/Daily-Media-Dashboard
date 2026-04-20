"""Background ingest + MDM scheduler.

APScheduler's BackgroundScheduler runs jobs in a daemon thread alongside
uvicorn. On every tick the scheduler:

  1. Pulls every active feed (records an IngestRun row per feed, which
     also drives the "last refresh" chip on /).
  2. Runs the AOR tagger over anything newly ingested.
  3. Runs MDM assessment for up to ``mdm_batch_per_tick`` articles that
     don't have an assessment yet — so the home page's MDM aggregates
     are computed automatically instead of requiring an analyst click.

The scheduler is off by default. Enable by setting CCMD_INGEST_ENABLED=1
(and make sure at least one Fly machine stays running, otherwise the job
won't fire while the app is scaled to zero).
"""

from __future__ import annotations

import logging
from typing import Optional

from ..config import settings
from ..db import session_scope

log = logging.getLogger(__name__)

_scheduler: Optional["object"] = None  # lazy type so apscheduler is never
                                       # imported when the feature is off.


def _run_mdm_batch() -> None:
    """Assess up to settings.mdm_batch_per_tick articles that have no
    MDMAssessment yet. Stub classifier: cheap; Anthropic: rate-limited
    by the batch size. Runs inline on the scheduler thread."""
    from sqlmodel import select
    from ..classify.mdm_runner import assess_article
    from ..models import Article, MDMAssessment

    batch = max(0, int(settings.mdm_batch_per_tick))
    if batch == 0:
        return

    try:
        with session_scope() as session:
            assessed_ids = set(session.exec(
                select(MDMAssessment.article_id).distinct()
            ).all())
            pending = list(session.exec(
                select(Article.id)
                .where(~Article.id.in_(assessed_ids) if assessed_ids else True)
                .order_by(Article.fetched_at.desc())
                .limit(batch)
            ).all())
    except Exception:
        log.exception("scheduler: could not enumerate MDM backlog")
        return

    if not pending:
        return

    log.info("scheduler: MDM batch — assessing %d article(s)", len(pending))
    done = 0
    for aid in pending:
        try:
            with session_scope() as session:
                assess_article(session, aid)
            done += 1
        except Exception:
            log.exception("scheduler: MDM assess failed for article %s", aid)
    log.info("scheduler: MDM batch done — %d/%d succeeded", done, len(pending))


def _run_ingest_job() -> None:
    from ..ingest.pipeline import ingest_all

    log.info("scheduler: starting ingest pass")
    total_new = 0
    try:
        with session_scope() as session:
            results = ingest_all(session, extract_full=settings.ingest_extract_full)
            total_new = sum(r.new for r in results)
        log.info("scheduler: ingest pass done — %d new article(s) across %d feed(s)",
                 total_new, len(results))
    except Exception:
        log.exception("scheduler: ingest pass failed")

    if settings.ingest_tag_after:
        try:
            from ..classify.aor_runner import tag_all_untagged
            with session_scope() as session:
                processed, written = tag_all_untagged(session)
            log.info("scheduler: tagged %d article(s), wrote %d row(s)",
                     processed, written)
        except Exception:
            log.exception("scheduler: AOR tagging pass failed")

    if settings.mdm_auto_enabled:
        _run_mdm_batch()


def start_scheduler() -> None:
    """Start the background ingest scheduler if enabled in settings.

    Safe to call multiple times; re-entry is a no-op once started.
    """
    global _scheduler
    if not settings.ingest_enabled:
        log.info("scheduler: disabled (CCMD_INGEST_ENABLED=0)")
        return
    if _scheduler is not None:
        log.info("scheduler: already running")
        return

    from apscheduler.schedulers.background import BackgroundScheduler

    sch = BackgroundScheduler(daemon=True, timezone="UTC")
    sch.add_job(
        _run_ingest_job,
        trigger="interval",
        minutes=settings.ingest_interval_minutes,
        id="ingest_all",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    # Fire once on startup so the "last refresh" chip is populated without
    # waiting out the first interval.
    sch.add_job(_run_ingest_job, id="ingest_all_bootstrap", max_instances=1)
    sch.start()
    _scheduler = sch
    log.info("scheduler: started — ingest every %d min(s)",
             settings.ingest_interval_minutes)


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)  # type: ignore[attr-defined]
    except Exception:
        log.exception("scheduler: error on shutdown")
    _scheduler = None
