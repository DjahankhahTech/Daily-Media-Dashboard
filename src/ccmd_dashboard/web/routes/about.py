"""Methodology, feed catalog, CCMD table."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from ...models import CCMD, Feed
from ..deps import db_session

router = APIRouter()


@router.get("/about", response_class=HTMLResponse, name="about_view")
def about_view(request: Request, session: Session = Depends(db_session)):
    from ..app import shared_context, templates

    ccmds = list(session.exec(select(CCMD).order_by(CCMD.aor_type, CCMD.code)).all())
    feeds = list(session.exec(select(Feed).order_by(Feed.source_tier, Feed.name)).all())

    ctx = shared_context(request, session, active_tab="ABOUT")
    ctx.update({"ccmds": ccmds, "feeds": feeds})
    return templates.TemplateResponse(request, "pages/about.html", ctx)
