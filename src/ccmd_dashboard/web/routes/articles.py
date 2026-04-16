"""Per-article detail page."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from ...models import AnalystNote, Article, ArticleCCMD, Feed, MDMAssessment
from ..deps import db_session

router = APIRouter()


@router.get("/articles/{article_id}", response_class=HTMLResponse, name="article_detail")
def article_detail(
    article_id: int,
    request: Request,
    session: Session = Depends(db_session),
):
    from ..app import shared_context, templates

    article = session.get(Article, article_id)
    if article is None:
        raise HTTPException(404, "article not found")
    feed = session.get(Feed, article.feed_id)
    tags = list(
        session.exec(
            select(ArticleCCMD).where(ArticleCCMD.article_id == article.id)
        ).all()
    )
    notes = list(
        session.exec(
            select(AnalystNote)
            .where(AnalystNote.article_id == article.id)
            .order_by(AnalystNote.created_at.desc())
        ).all()
    )
    latest_mdm = session.exec(
        select(MDMAssessment)
        .where(MDMAssessment.article_id == article.id)
        .order_by(MDMAssessment.assessed_at.desc())
    ).first()

    referrer = request.headers.get("referer") or str(request.url_for("home"))

    ctx = shared_context(request, session, active_tab="")
    ctx.update({
        "article": article,
        "feed": feed,
        "tags": tags,
        "notes": notes,
        "latest_mdm": latest_mdm,
        "referrer": referrer,
    })
    return templates.TemplateResponse(request, "pages/article_detail.html", ctx)
