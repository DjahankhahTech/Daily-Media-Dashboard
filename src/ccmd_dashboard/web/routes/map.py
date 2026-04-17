"""Geographic layout: world map with CCMD AOR zones + functional command tiles.

The map is a hand-drawn simplified SVG (equirectangular projection on a
1000x500 canvas). It's deliberately stylised rather than geodetically
accurate — OSW leadership briefings care about "which CCMD owns this"
more than coastline fidelity, and a stylised map renders cleanly in a
briefing room projector at any resolution without shipping 500KB of
TopoJSON.

Zones overlap slightly where AORs share seams (e.g. EUCOM/CENTCOM
in the Caucasus) — that mirrors how the real Unified Command Plan
handles adjacency.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlmodel import Session, select

from ...models import (
    AORType,
    ArticleCCMD,
    CCMD,
    MDMAssessment,
)
from ..deps import db_session

router = APIRouter()


@router.get("/map", response_class=HTMLResponse, name="map_view")
def map_view(request: Request, session: Session = Depends(db_session)):
    from ..app import shared_context, templates

    ccmds = session.exec(select(CCMD).order_by(CCMD.aor_type, CCMD.code)).all()

    counts: dict[str, int] = {}
    assessed: dict[str, int] = {}
    for c in ccmds:
        n = int(
            session.exec(
                select(func.count(func.distinct(ArticleCCMD.article_id)))  # type: ignore[arg-type]
                .where(ArticleCCMD.ccmd_code == c.code)
            ).one()
            or 0
        )
        counts[c.code] = n
        a = int(
            session.exec(
                select(func.count(func.distinct(MDMAssessment.article_id)))  # type: ignore[arg-type]
                .join(ArticleCCMD, ArticleCCMD.article_id == MDMAssessment.article_id)
                .where(ArticleCCMD.ccmd_code == c.code)
            ).one()
            or 0
        )
        assessed[c.code] = a

    geo = [c for c in ccmds if c.aor_type == AORType.GEOGRAPHIC]
    fun = [c for c in ccmds if c.aor_type == AORType.FUNCTIONAL]

    geo_rows = [
        {
            "code": c.code,
            "name": c.name,
            "description": c.description,
            "count": counts.get(c.code, 0),
            "assessed": assessed.get(c.code, 0),
            "href": str(request.url_for("ccmd_view", code=c.code)),
        }
        for c in geo
    ]
    fun_rows = [
        {
            "code": c.code,
            "name": c.name,
            "description": c.description,
            "count": counts.get(c.code, 0),
            "assessed": assessed.get(c.code, 0),
            "href": str(request.url_for("ccmd_view", code=c.code)),
        }
        for c in fun
    ]

    ctx = shared_context(request, session, active_tab="MAP")
    ctx.update({
        "geo_rows": geo_rows,
        "fun_rows": fun_rows,
        "total_tagged": sum(counts.values()),
    })
    return templates.TemplateResponse(request, "pages/map.html", ctx)
