"""Wire tag_article() to the DB: persist ArticleCCMD rows, support recompute."""

from typing import Optional

from sqlmodel import Session, delete, select

from ..models import Article, ArticleCCMD
from .aor_tagger import TAGGER_VERSION, tag_article


def tag_and_store(
    session: Session,
    article: Article,
    *,
    recompute: bool = False,
) -> list[ArticleCCMD]:
    """Tag one article and persist ArticleCCMD rows.

    If ``recompute`` is False and any tags exist for this article they are
    returned as-is; the tagger never double-writes by default.
    """
    existing = list(
        session.exec(select(ArticleCCMD).where(ArticleCCMD.article_id == article.id)).all()
    )
    if existing and not recompute:
        return existing
    if recompute and existing:
        session.exec(delete(ArticleCCMD).where(ArticleCCMD.article_id == article.id))

    matches = tag_article(article.title or "", article.raw_text or article.summary or "")
    rows = [
        ArticleCCMD(
            article_id=article.id,
            ccmd_code=m.ccmd_code,
            match_score=m.score,
            matched_terms=m.matched_terms,
            tagged_by=TAGGER_VERSION,
        )
        for m in matches
    ]
    for row in rows:
        session.add(row)
    return rows


def tag_all_untagged(session: Session, *, recompute: bool = False) -> tuple[int, int]:
    """Tag every article that has no ArticleCCMD rows yet (or every article
    if ``recompute``). Returns (articles_processed, tags_written).

    Runs the best-guess (source-based) pass afterward: articles that
    still have no match get a low-confidence BG row if their feed has
    a state affiliation or is tier-1 USG."""
    q = select(Article)
    articles = list(session.exec(q).all())
    processed = 0
    written = 0
    for article in articles:
        if not recompute:
            has_tag = session.exec(
                select(ArticleCCMD).where(ArticleCCMD.article_id == article.id)
            ).first()
            if has_tag is not None:
                continue
        rows = tag_and_store(session, article, recompute=recompute)
        processed += 1
        written += len(rows)
        session.commit()

    from .best_guess import best_guess_untagged
    _, bg_written = best_guess_untagged(session)
    written += bg_written
    return processed, written


def tag_one(
    session: Session, article_id: int, *, recompute: bool = False
) -> Optional[list[ArticleCCMD]]:
    article = session.get(Article, article_id)
    if article is None:
        return None
    rows = tag_and_store(session, article, recompute=recompute)
    session.commit()
    return rows
