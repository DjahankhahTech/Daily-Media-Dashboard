"""Home dashboard: Leaflet satellite map with MDM-colored AOR overlays."""

from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlmodel import Session, select

from ...models import (
    AnalystAction,
    AnalystNote,
    AORType,
    Article,
    ArticleCCMD,
    CCMD,
    Feed,
    IngestRun,
    MDMAssessment,
    MDMCategory,
)
from ..deps import db_session

router = APIRouter()

# AOR bounds in (sw_lat, sw_lon), (ne_lat, ne_lon) — approximate rectangles
# over each geographic CCMD's footprint. Good enough for a Leaflet overlay;
# the underlying AORs are irregular polygons but rectangles read cleanly
# at world zoom.
CCMD_BOUNDS: dict[str, list[list[float]]] = {
    "NORTHCOM":  [[14.0, -168.0], [72.0,  -52.0]],
    "SOUTHCOM":  [[-56.0, -92.0], [30.0,  -34.0]],
    "EUCOM":     [[35.0,  -10.0], [72.0,  180.0]],  # incl. Russia
    "AFRICOM":   [[-36.0, -20.0], [37.0,   52.0]],
    "CENTCOM":   [[10.0,   25.0], [50.0,   78.0]],
    "INDOPACOM": [[-50.0,  60.0], [55.0,  180.0]],
}


def _humanize_age(delta_seconds: float) -> str:
    s = int(delta_seconds)
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60} min ago"
    if s < 86400:
        return f"{s // 3600} h ago"
    return f"{s // 86400} d ago"


@router.get("/", response_class=HTMLResponse, name="home")
def home(request: Request, session: Session = Depends(db_session)):
    from ..app import shared_context, templates

    ccmds = session.exec(select(CCMD).order_by(CCMD.aor_type, CCMD.code)).all()

    counts: dict[str, int] = {}
    best_guess_counts: dict[str, int] = {}
    reviewed_counts: dict[str, int] = {}
    flagged_counts: dict[str, int] = {}
    assessed_counts: dict[str, int] = {}
    mean_scores: dict[str, float | None] = {}
    dominant_cat: dict[str, str | None] = {}
    category_counts: dict[str, dict[str, int]] = {}

    for c in ccmds:
        tag_rows = list(session.exec(
            select(ArticleCCMD).where(ArticleCCMD.ccmd_code == c.code)
        ).all())
        article_ids = list({r.article_id for r in tag_rows})
        counts[c.code] = len(article_ids)
        best_guess_counts[c.code] = sum(
            1 for r in tag_rows if r.tagged_by.startswith("best_guess")
        )

        if article_ids:
            reviewed_counts[c.code] = int(session.exec(
                select(func.count())  # type: ignore[arg-type]
                .select_from(AnalystNote)
                .where(AnalystNote.article_id.in_(article_ids))
                .where(AnalystNote.action_taken == AnalystAction.REVIEWED)
            ).one() or 0)
            flagged_counts[c.code] = int(session.exec(
                select(func.count())  # type: ignore[arg-type]
                .select_from(AnalystNote)
                .where(AnalystNote.article_id.in_(article_ids))
                .where(AnalystNote.action_taken == AnalystAction.FLAGGED_FOR_OIC)
            ).one() or 0)
        else:
            reviewed_counts[c.code] = 0
            flagged_counts[c.code] = 0

        # MDM aggregates — use the latest assessment per article.
        assessments = []
        if article_ids:
            assessments = list(session.exec(
                select(MDMAssessment).where(MDMAssessment.article_id.in_(article_ids))
            ).all())
        # Keep only the latest row per article (mdm_runner appends on re-assess).
        latest_by_article: dict[int, MDMAssessment] = {}
        for a in assessments:
            prev = latest_by_article.get(a.article_id)
            if prev is None or (a.assessed_at and prev.assessed_at and a.assessed_at > prev.assessed_at):
                latest_by_article[a.article_id] = a
        latest = list(latest_by_article.values())

        assessed_counts[c.code] = len(latest)
        cat_counter: Counter[str] = Counter()
        scored = [a.concern_score for a in latest if a.concern_score is not None]
        for a in latest:
            cat_counter[a.category.value] += 1
        category_counts[c.code] = dict(cat_counter)
        mean_scores[c.code] = (sum(scored) / len(scored)) if scored else None
        # Most common real category (ignore insufficient_data if we have real ones).
        real_cats = {k: v for k, v in cat_counter.items()
                     if k != MDMCategory.INSUFFICIENT_DATA.value}
        if real_cats:
            dominant_cat[c.code] = max(real_cats, key=lambda k: real_cats[k])
        elif cat_counter:
            dominant_cat[c.code] = MDMCategory.INSUFFICIENT_DATA.value
        else:
            dominant_cat[c.code] = None

    total_articles = int(
        session.exec(select(func.count()).select_from(Article)).one() or 0  # type: ignore[arg-type]
    )
    feed_count = int(
        session.exec(select(func.count()).select_from(Feed)).one() or 0  # type: ignore[arg-type]
    )
    tagged_article_ids = set(
        session.exec(select(ArticleCCMD.article_id).distinct()).all()
    )
    unassigned_count = total_articles - len(tagged_article_ids)

    # Last successful ingest — drives the "last refreshed" chip.
    last_run = session.exec(
        select(IngestRun)
        .where(IngestRun.finished_at.is_not(None))  # type: ignore[union-attr]
        .order_by(IngestRun.finished_at.desc())  # type: ignore[union-attr]
        .limit(1)
    ).first()
    last_refresh_label = "never"
    if last_run and last_run.finished_at:
        now = datetime.now(timezone.utc)
        ts = last_run.finished_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        last_refresh_label = _humanize_age((now - ts).total_seconds())

    geo_ccmds = [c for c in ccmds if c.aor_type == AORType.GEOGRAPHIC]
    fun_ccmds = [c for c in ccmds if c.aor_type == AORType.FUNCTIONAL]

    regions = []
    for c in geo_ccmds:
        bounds = CCMD_BOUNDS.get(c.code)
        if bounds is None:
            continue
        regions.append({
            "code": c.code,
            "name": c.name,
            "href": str(request.url_for("ccmd_view", code=c.code)),
            "bounds": bounds,
            "articles_total": counts[c.code],
            "articles_best_guess": best_guess_counts[c.code],
            "assessed_count": assessed_counts[c.code],
            "mean_score": round(mean_scores[c.code], 1) if mean_scores[c.code] is not None else None,
            "dominant_category": dominant_cat[c.code],
            "category_counts": category_counts[c.code],
        })

    functional = [
        {
            "code": c.code,
            "name": c.name,
            "total": counts[c.code],
            "dominant_category": dominant_cat[c.code],
            "assessed_count": assessed_counts[c.code],
            "href": str(request.url_for("ccmd_view", code=c.code)),
        }
        for c in fun_ccmds
    ]

    rows = [
        {
            "code": c.code,
            "name": c.name,
            "href": str(request.url_for("ccmd_view", code=c.code)),
            "total": counts[c.code],
            "best_guess": best_guess_counts[c.code],
            "reviewed": reviewed_counts[c.code],
            "flagged": flagged_counts[c.code],
            "assessed": assessed_counts[c.code],
            "mean_score": (round(mean_scores[c.code], 1)
                           if mean_scores[c.code] is not None else None),
            "dominant_category": dominant_cat[c.code],
        }
        for c in ccmds
    ]

    ctx = shared_context(request, session, active_tab="HOME")
    ctx.update({
        "ccmd_count": len(ccmds),
        "feed_count": feed_count,
        "article_count": total_articles,
        "tagged_count": len(tagged_article_ids),
        "unassigned_count": unassigned_count,
        "ccmd_rows": rows,
        "regions": regions,
        "functional": functional,
        "last_refresh_label": last_refresh_label,
    })
    return templates.TemplateResponse(request, "pages/home.html", ctx)
