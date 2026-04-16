"""MDM Queue tab — articles with at least one MDM assessment.

The POST endpoint to queue a new assessment is implemented in step 6.
For step 4 the UI stub returns 501 so the structure is in place.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from ..deps import db_session
from ..queries import query_articles

router = APIRouter()


@router.get("/mdm", response_class=HTMLResponse, name="mdm_queue")
def mdm_queue(request: Request, session: Session = Depends(db_session)):
    from ..app import shared_context, templates

    rows, _ = query_articles(session, require_mdm=True, limit=200)
    ctx = shared_context(request, session, active_tab="MDM")
    ctx.update({"articles": rows, "filters": {}})
    return templates.TemplateResponse(request, "pages/mdm_queue.html", ctx)


@router.post("/articles/{article_id}/assess", name="assess_article")
def assess_article(article_id: int, session: Session = Depends(db_session)):
    """Step-4 stub: redirect to article detail with a marker. Step 6 will
    enqueue a real MDM run and populate the assessment."""
    # Deliberately not a 500 — a demo walkthrough can click this button and
    # get back to the article page with no surprise traceback.
    return RedirectResponse(
        url=f"/articles/{article_id}?assess=pending",
        status_code=303,
    )
