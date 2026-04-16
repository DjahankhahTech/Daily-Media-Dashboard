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
def assess_article(
    article_id: int, request: Request, session: Session = Depends(db_session)
):
    """Run the MDM pipeline for one article (stage 1 + stage 2) and
    redirect back to the detail page. Failures are caught and surfaced
    via the assessment row's ``failure_reason`` — no 500s."""
    from ...classify.mdm_runner import assess_article as run_assess

    try:
        run_assess(session, article_id)
    except LookupError:
        raise HTTPException(404, f"article {article_id} not found")

    return RedirectResponse(
        url=str(request.url_for("article_detail", article_id=article_id)),
        status_code=303,
    )
