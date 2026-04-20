"""Geographic map tab — world-layout view of the 6 geographic CCMDs.

Renders an inline SVG schematic world map with one rectangle per geographic
AOR, heat-colored by article volume. Functional CCMDs have no geography, so
they render as a chip row beneath the map. Air-gap safe — no JS libs, no
external tiles, no network calls; the map is a static equirectangular-style
schematic, not a cartographic overlay.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlmodel import Session, select

from ...models import AORType, Article, ArticleCCMD, CCMD
from ..deps import db_session

router = APIRouter()

# Approximate AOR footprints on a 1000x500 viewBox. The map is schematic:
# rectangles are sized/positioned so an analyst glancing at the screen
# recognizes the continent, not to any cartographic standard.
CCMD_MAP_LAYOUT: dict[str, dict[str, int]] = {
    "NORTHCOM":  {"x":  60, "y": 110, "w": 230, "h": 150},
    "SOUTHCOM":  {"x": 220, "y": 265, "w": 130, "h": 195},
    "EUCOM":     {"x": 430, "y":  40, "w": 330, "h": 145},
    "AFRICOM":   {"x": 450, "y": 200, "w": 170, "h": 225},
    "CENTCOM":   {"x": 580, "y": 160, "w": 155, "h": 135},
    "INDOPACOM": {"x": 705, "y":  90, "w": 285, "h": 360},
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


@router.get("/geographic", response_class=HTMLResponse, name="geographic_view")
def geographic_view(
    request: Request,
    session: Session = Depends(db_session),
):
    from ..app import shared_context, templates

    ccmds = session.exec(select(CCMD).order_by(CCMD.aor_type, CCMD.code)).all()

    # Per-CCMD distinct article counts. Mirrors home.py aggregation but we
    # only need totals here.
    counts: dict[str, int] = {}
    for c in ccmds:
        ids = session.exec(
            select(ArticleCCMD.article_id).where(ArticleCCMD.ccmd_code == c.code)
        ).all()
        counts[c.code] = len(set(ids))

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
            "x": layout["x"],
            "y": layout["y"],
            "w": layout["w"],
            "h": layout["h"],
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

    total_articles = int(
        session.exec(select(func.count()).select_from(Article)).one() or 0  # type: ignore[arg-type]
    )

    ctx = shared_context(request, session, active_tab="MAP")
    ctx.update({
        "regions": regions,
        "functional": functional,
        "max_geo_count": max_geo_count,
        "total_articles": total_articles,
    })
    return templates.TemplateResponse(request, "pages/geographic.html", ctx)
