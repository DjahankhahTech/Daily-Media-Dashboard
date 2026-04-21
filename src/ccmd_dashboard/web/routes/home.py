"""Home dashboard: satellite map with narrative overlay + daily briefing."""

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
)
from ..daily_summary import build_brief_for
from ..deps import db_session

router = APIRouter()

# AOR bounds in (sw_lat, sw_lon), (ne_lat, ne_lon) — approximate rectangles
# over each geographic CCMD's footprint. Irregular polygons in reality;
# rectangles read cleanly at world zoom.
CCMD_BOUNDS: dict[str, list[list[float]]] = {
    "NORTHCOM":  [[14.0, -168.0], [72.0,  -52.0]],
    "SOUTHCOM":  [[-56.0, -92.0], [30.0,  -34.0]],
    "EUCOM":     [[35.0,  -10.0], [72.0,  180.0]],
    "AFRICOM":   [[-36.0, -20.0], [37.0,   52.0]],
    "CENTCOM":   [[10.0,   25.0], [50.0,   78.0]],
    "INDOPACOM": [[-50.0,  60.0], [55.0,  180.0]],
}

WINDOW_HOURS = 24


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
    briefs = {c.code: build_brief_for(session, c.code, window_hours=WINDOW_HOURS)
              for c in ccmds}

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

    def _note_count(article_ids: list[int], action: AnalystAction) -> int:
        if not article_ids:
            return 0
        return int(session.exec(
            select(func.count())  # type: ignore[arg-type]
            .select_from(AnalystNote)
            .where(AnalystNote.article_id.in_(article_ids))
            .where(AnalystNote.action_taken == action)
        ).one() or 0)

    def _ids_for(code: str) -> list[int]:
        return list({r.article_id for r in session.exec(
            select(ArticleCCMD).where(ArticleCCMD.ccmd_code == code)
        ).all()})

    regions = []
    for c in geo_ccmds:
        bounds = CCMD_BOUNDS.get(c.code)
        if bounds is None:
            continue
        b = briefs[c.code]
        top_line = b.headlines[0].title if b.headlines else None
        regions.append({
            "code": c.code,
            "name": c.name,
            "href": str(request.url_for("ccmd_view", code=c.code)),
            "bounds": bounds,
            "articles_total": b.total_count,
            "articles_window": b.window_count,
            "assessed_count": b.assessed_count,
            "mean_score": b.mean_score,
            "dominant_category": b.dominant_category,
            "narrative": b.narrative,
            "top_headline": top_line,
            "themes": b.themes,
            "headlines": [
                {"title": h.title, "feed_name": h.feed_name,
                 "mdm_category": h.mdm_category, "mdm_score": h.mdm_score,
                 "href": str(request.url_for("article_detail", article_id=h.article_id))}
                for h in b.headlines
            ],
        })

    functional = [
        {
            "code": c.code,
            "name": c.name,
            "total": briefs[c.code].total_count,
            "window_count": briefs[c.code].window_count,
            "dominant_category": briefs[c.code].dominant_category,
            "href": str(request.url_for("ccmd_view", code=c.code)),
        }
        for c in fun_ccmds
    ]

    rows = []
    for c in ccmds:
        b = briefs[c.code]
        ids = _ids_for(c.code)
        rows.append({
            "code": c.code,
            "name": c.name,
            "href": str(request.url_for("ccmd_view", code=c.code)),
            "total": b.total_count,
            "window": b.window_count,
            "reviewed": _note_count(ids, AnalystAction.REVIEWED),
            "flagged": _note_count(ids, AnalystAction.FLAGGED_FOR_OIC),
            "assessed": b.assessed_count,
            "mean_score": b.mean_score,
            "dominant_category": b.dominant_category,
            "narrative": b.narrative,
        })

    # Top-line narrative for the hero.
    window_total = sum(briefs[c.code].window_count for c in ccmds)
    most_active = max(briefs.values(), key=lambda br: br.window_count, default=None)
    hero_narrative = (
        f"{window_total} article(s) in the last {WINDOW_HOURS} h across "
        f"{len(ccmds)} commands."
    )
    if most_active and most_active.window_count > 0:
        hero_narrative += (
            f" Most active: {most_active.code} ({most_active.window_count})."
        )

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
        "hero_narrative": hero_narrative,
        "window_hours": WINDOW_HOURS,
    })
    return templates.TemplateResponse(request, "pages/home.html", ctx)
