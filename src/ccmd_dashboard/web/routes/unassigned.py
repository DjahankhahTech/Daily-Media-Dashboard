"""Articles that failed to match any AOR. Visible diagnostic for analysts."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from ..deps import db_session
from ..queries import query_articles

router = APIRouter()


@router.get("/unassigned", response_class=HTMLResponse, name="unassigned_view")
def unassigned_view(request: Request, session: Session = Depends(db_session)):
    from ..app import shared_context, templates

    rows, _ = query_articles(session, only_unassigned=True, limit=200)
    ctx = shared_context(request, session, active_tab="UNASSIGNED")
    ctx.update({"articles": rows})
    return templates.TemplateResponse(request, "pages/unassigned.html", ctx)
