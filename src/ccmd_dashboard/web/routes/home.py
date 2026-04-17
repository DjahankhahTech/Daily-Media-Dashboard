"""Home dashboard: stat tiles + per-CCMD tiles + unassigned diagnostic."""

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
    MDMAssessment,
)
from ..deps import db_session

router = APIRouter()


@router.get("/", response_class=HTMLResponse, name="home")
def home(request: Request, session: Session = Depends(db_session)):
    from ..app import shared_context, templates

    ccmds = session.exec(select(CCMD).order_by(CCMD.aor_type, CCMD.code)).all()
    geo_rows: list[dict] = []
    fun_rows: list[dict] = []

    total_articles = int(
        session.exec(select(func.count()).select_from(Article)).one() or 0  # type: ignore[arg-type]
    )
    feed_count = int(session.exec(select(func.count()).select_from(Feed)).one() or 0)  # type: ignore[arg-type]
    tagged_article_ids = set(
        session.exec(select(ArticleCCMD.article_id).distinct()).all()
    )
    unassigned_count = total_articles - len(tagged_article_ids)
    total_flagged = int(
        session.exec(
            select(func.count())  # type: ignore[arg-type]
            .select_from(AnalystNote)
            .where(AnalystNote.action_taken == AnalystAction.FLAGGED_FOR_OIC)
        ).one()
        or 0
    )

    for c in ccmds:
        article_ids = list(
            session.exec(
                select(ArticleCCMD.article_id).where(ArticleCCMD.ccmd_code == c.code)
            ).all()
        )
        total = len(set(article_ids))
        reviewed = int(session.exec(
            select(func.count())  # type: ignore[arg-type]
            .select_from(AnalystNote)
            .where(AnalystNote.article_id.in_(article_ids))
            .where(AnalystNote.action_taken == AnalystAction.REVIEWED)
        ).one() or 0) if article_ids else 0
        flagged = int(session.exec(
            select(func.count())  # type: ignore[arg-type]
            .select_from(AnalystNote)
            .where(AnalystNote.article_id.in_(article_ids))
            .where(AnalystNote.action_taken == AnalystAction.FLAGGED_FOR_OIC)
        ).one() or 0) if article_ids else 0
        assessed = int(session.exec(
            select(func.count(func.distinct(MDMAssessment.article_id)))  # type: ignore[arg-type]
            .where(MDMAssessment.article_id.in_(article_ids))
        ).one() or 0) if article_ids else 0

        row = {
            "code": c.code,
            "name": c.name,
            "href": str(request.url_for("ccmd_view", code=c.code)),
            "total": total,
            "reviewed": reviewed,
            "flagged": flagged,
            "assessed": assessed,
        }
        if c.aor_type == AORType.GEOGRAPHIC:
            geo_rows.append(row)
        else:
            fun_rows.append(row)

    ctx = shared_context(request, session, active_tab="HOME")
    ctx.update({
        "ccmd_count": len(ccmds),
        "feed_count": feed_count,
        "article_count": total_articles,
        "tagged_count": len(tagged_article_ids),
        "unassigned_count": unassigned_count,
        "total_flagged": total_flagged,
        "geo_rows": geo_rows,
        "fun_rows": fun_rows,
    })
    return templates.TemplateResponse(request, "pages/home.html", ctx)
