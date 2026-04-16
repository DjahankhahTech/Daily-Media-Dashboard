"""Read-side queries reused by multiple routes."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import func, or_
from sqlmodel import Session, select

from ..models import (
    AnalystNote,
    Article,
    ArticleCCMD,
    Feed,
    MDMAssessment,
)


@dataclass
class ArticleRow:
    article: Article
    feed: Feed
    tags: list[ArticleCCMD]
    latest_mdm: Optional[MDMAssessment]
    note_count: int


@dataclass
class ArticleFilters:
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    tier: Optional[str] = None
    state: Optional[str] = None  # "exclude" | "only"
    mdm: Optional[str] = None
    q: Optional[str] = None


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _latest_mdm(session: Session, article_id: int) -> Optional[MDMAssessment]:
    return session.exec(
        select(MDMAssessment)
        .where(MDMAssessment.article_id == article_id)
        .order_by(MDMAssessment.assessed_at.desc())
    ).first()


def _note_count(session: Session, article_id: int) -> int:
    return int(
        session.exec(
            select(func.count())  # type: ignore[arg-type]
            .select_from(AnalystNote)
            .where(AnalystNote.article_id == article_id)
        ).one()
        or 0
    )


def _decorate(session: Session, articles: list[Article]) -> list[ArticleRow]:
    if not articles:
        return []
    feed_ids = {a.feed_id for a in articles}
    feeds_by_id = {
        f.id: f for f in session.exec(select(Feed).where(Feed.id.in_(feed_ids))).all()
    }
    article_ids = [a.id for a in articles]
    tags_by_article: dict[int, list[ArticleCCMD]] = {}
    for tag in session.exec(
        select(ArticleCCMD).where(ArticleCCMD.article_id.in_(article_ids))
    ).all():
        tags_by_article.setdefault(tag.article_id, []).append(tag)

    rows: list[ArticleRow] = []
    for a in articles:
        rows.append(
            ArticleRow(
                article=a,
                feed=feeds_by_id[a.feed_id],
                tags=sorted(
                    tags_by_article.get(a.id, []),
                    key=lambda t: -t.match_score,
                ),
                latest_mdm=_latest_mdm(session, a.id),
                note_count=_note_count(session, a.id),
            )
        )
    return rows


def query_articles(
    session: Session,
    *,
    ccmd_code: Optional[str] = None,
    only_unassigned: bool = False,
    require_mdm: bool = False,
    filters: Optional[ArticleFilters] = None,
    limit: int = 30,
    offset: int = 0,
) -> tuple[list[ArticleRow], int]:
    """Return (page_of_rows, total_count)."""
    filters = filters or ArticleFilters()

    stmt = select(Article).join(Feed, Feed.id == Article.feed_id)

    if ccmd_code:
        stmt = stmt.join(ArticleCCMD, ArticleCCMD.article_id == Article.id).where(
            ArticleCCMD.ccmd_code == ccmd_code
        )
    if only_unassigned:
        tagged_subq = select(ArticleCCMD.article_id).distinct()
        stmt = stmt.where(~Article.id.in_(tagged_subq))
    if require_mdm:
        mdm_subq = select(MDMAssessment.article_id).distinct()
        stmt = stmt.where(Article.id.in_(mdm_subq))

    if filters.tier:
        stmt = stmt.where(Feed.source_tier == int(filters.tier))
    if filters.state == "exclude":
        stmt = stmt.where(Feed.state_affiliation.is_(None))
    elif filters.state == "only":
        stmt = stmt.where(Feed.state_affiliation.is_not(None))

    dt_from = _parse_date(filters.date_from)
    dt_to = _parse_date(filters.date_to)
    if dt_from:
        stmt = stmt.where(Article.published_at >= dt_from)
    if dt_to:
        stmt = stmt.where(Article.published_at <= dt_to)

    if filters.q:
        pattern = f"%{filters.q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Article.title).like(pattern),
                func.lower(Article.raw_text).like(pattern),
                func.lower(Article.summary).like(pattern),
            )
        )

    if filters.mdm:
        latest_cat_subq = (
            select(MDMAssessment.article_id, MDMAssessment.category)
            .order_by(MDMAssessment.assessed_at.desc())
            .subquery()
        )
        stmt = stmt.join(
            latest_cat_subq, latest_cat_subq.c.article_id == Article.id
        ).where(latest_cat_subq.c.category == filters.mdm)

    total = int(session.exec(
        select(func.count()).select_from(stmt.subquery())  # type: ignore[arg-type]
    ).one() or 0)

    page = list(
        session.exec(
            stmt.order_by(Article.published_at.desc().nullslast(), Article.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return _decorate(session, page), total
