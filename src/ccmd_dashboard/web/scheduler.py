"""Background ingest scheduler.

APScheduler's BackgroundScheduler runs jobs in a daemon thread alongside
uvicorn. On every tick we pull every active feed, record an IngestRun row
per feed (which also drives the "last refresh" chip on /), and optionally
run the AOR tagger over anything new. MDM is not triggered here — it's an
analyst-on-demand step per README.

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


def _run_ingest_job() -> None:
    from ..ingest.pipeline import ingest_all

    log.info("scheduler: starting ingest pass")
    try:
        with session_scope() as session:
            results = ingest_all(session, extract_full=settings.ingest_extract_full)
            total_new = sum(r.new for r in results)
        log.info("scheduler: ingest pass done — %d new article(s) across %d feed(s)",
                 total_new, len(results))
    except Exception:
        log.exception("scheduler: ingest pass failed")
        return

    if not settings.ingest_tag_after or total_new == 0:
        return

    try:
        from ..classify.aor_runner import tag_all_untagged
        with session_scope() as session:
            processed, written = tag_all_untagged(session)
        log.info("scheduler: tagged %d article(s), wrote %d row(s)", processed, written)
    except Exception:
        log.exception("scheduler: AOR tagging pass failed")


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
