"""Home dashboard: world map overlay + per-CCMD volume table + last-refresh."""

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
)
from ..deps import db_session

router = APIRouter()


# Approximate AOR footprints on a 1000x500 viewBox. Tuned to overlay the
# simplified continent polygons in partials/world_basemap.html — rectangles
# sit roughly over the landmasses each CCMD is responsible for.
CCMD_MAP_LAYOUT: dict[str, dict[str, int]] = {
    "NORTHCOM":  {"x":  95, "y":  85, "w": 220, "h": 190},
    "SOUTHCOM":  {"x": 235, "y": 290, "w": 110, "h": 185},
    "EUCOM":     {"x": 445, "y":  80, "w": 180, "h": 110},
    "AFRICOM":   {"x": 470, "y": 195, "w": 155, "h": 230},
    "CENTCOM":   {"x": 575, "y": 170, "w": 180, "h": 100},
    "INDOPACOM": {"x": 745, "y": 145, "w": 225, "h": 290},
}


def _heat_band(count: int, max_count: int) -> int:
    if count <= 0 or max_count <= 0:
        return 0
    ratio = count / max_count
    if ratio <= 0.25:
        return 1
    if ratio <= 0.50:
        return 2
    if ratio <= 0.75:
        return 3
    return 4


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

    # Aggregate counts we need for both the map heat and the stats table.
    counts: dict[str, int] = {}
    reviewed_counts: dict[str, int] = {}
    flagged_counts: dict[str, int] = {}
    assessed_counts: dict[str, int] = {}
    for c in ccmds:
        ids = list(session.exec(
            select(ArticleCCMD.article_id).where(ArticleCCMD.ccmd_code == c.code)
        ).all())
        counts[c.code] = len(set(ids))
        if ids:
            reviewed_counts[c.code] = int(session.exec(
                select(func.count())  # type: ignore[arg-type]
                .select_from(AnalystNote)
                .where(AnalystNote.article_id.in_(ids))
                .where(AnalystNote.action_taken == AnalystAction.REVIEWED)
            ).one() or 0)
            flagged_counts[c.code] = int(session.exec(
                select(func.count())  # type: ignore[arg-type]
                .select_from(AnalystNote)
                .where(AnalystNote.article_id.in_(ids))
                .where(AnalystNote.action_taken == AnalystAction.FLAGGED_FOR_OIC)
            ).one() or 0)
            assessed_counts[c.code] = int(session.exec(
                select(func.count(func.distinct(MDMAssessment.article_id)))  # type: ignore[arg-type]
                .where(MDMAssessment.article_id.in_(ids))
            ).one() or 0)
        else:
            reviewed_counts[c.code] = 0
            flagged_counts[c.code] = 0
            assessed_counts[c.code] = 0

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

    # Last successful ingest — drives the "last refreshed" chip on the map.
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
    max_geo_count = max((counts[c.code] for c in geo_ccmds), default=0)

    regions = []
    for c in geo_ccmds:
        layout = CCMD_MAP_LAYOUT.get(c.code)
        if layout is None:
            continue
        total = counts[c.code]
        regions.append({
            "code": c.code,
            "name": c.name,
            "total": total,
            "heat": _heat_band(total, max_geo_count),
            "href": str(request.url_for("ccmd_view", code=c.code)),
            "x": layout["x"], "y": layout["y"],
            "w": layout["w"], "h": layout["h"],
            "cx": layout["x"] + layout["w"] // 2,
            "cy": layout["y"] + layout["h"] // 2,
        })

    functional = [
        {
            "code": c.code,
            "name": c.name,
            "total": counts[c.code],
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
            "reviewed": reviewed_counts[c.code],
            "flagged": flagged_counts[c.code],
            "assessed": assessed_counts[c.code],
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
        "max_geo_count": max_geo_count,
        "last_refresh_label": last_refresh_label,
    })
    return templates.TemplateResponse(request, "pages/home.html", ctx)
