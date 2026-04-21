"""Persist tagger output to the DB.

Every article gets at least one CCMD assignment. The cascade is:

1. Primary: keyword + NER matches above ``aor_min_match_score``.
2. Fallback A: if nothing passed the threshold but the tagger found any
   hits on at least one CCMD, take the single highest-scoring match.
3. Fallback B: if no hits anywhere, map from the feed's state_affiliation
   (RU->EUCOM, CN/KP->INDOPACOM, IR/SY->CENTCOM, VE/CU->SOUTHCOM, etc.).
4. Fallback C: if still nothing, default to NORTHCOM (homeland). A
   catch-all is preferable to leaving an article Unassigned — the
   product-level contract is that every article rolls up under a CCMD.

All rows use ``tagged_by=TAGGER_VERSION`` so the UI treats them
uniformly. Internal audit (``match_score=0.0`` + empty ``matched_terms``)
still exposes fallback cases to developers via the DB.
"""

from __future__ import annotations

from typing import Optional

from sqlmodel import Session, delete, select

from ..models import Article, ArticleCCMD, Feed
from .aor_tagger import AORMatch, TAGGER_VERSION, tag_article


# Country-code -> CCMD. Only uncontroversial mappings. Edit by analyst review.
STATE_TO_CCMD: dict[str, str] = {
    "RU": "EUCOM",
    "BY": "EUCOM",
    "UA": "EUCOM",
    "CN": "INDOPACOM",
    "KP": "INDOPACOM",
    "IR": "CENTCOM",
    "SY": "CENTCOM",
    "VE": "SOUTHCOM",
    "CU": "SOUTHCOM",
}

DEFAULT_CCMD = "NORTHCOM"  # homeland-defense AOR is the least-wrong catch-all.


def _match_to_row(article_id: int, m: AORMatch) -> ArticleCCMD:
    return ArticleCCMD(
        article_id=article_id,
        ccmd_code=m.ccmd_code,
        match_score=m.score,
        matched_terms=m.matched_terms,
        tagged_by=TAGGER_VERSION,
    )


def _fallback_code(feed: Optional[Feed]) -> str:
    if feed is not None and feed.state_affiliation:
        guessed = STATE_TO_CCMD.get(feed.state_affiliation.upper())
        if guessed:
            return guessed
    return DEFAULT_CCMD


def _synthetic_row(article_id: int, ccmd_code: str) -> ArticleCCMD:
    return ArticleCCMD(
        article_id=article_id,
        ccmd_code=ccmd_code,
        match_score=0.0,
        matched_terms=[],
        tagged_by=TAGGER_VERSION,
    )


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

    text_title = article.title or ""
    text_body = article.raw_text or article.summary or ""

    # (1) primary pass — above threshold.
    matches = tag_article(text_title, text_body)
    rows: list[ArticleCCMD] = []
    if matches:
        rows = [_match_to_row(article.id, m) for m in matches]
    else:
        # (2) below-threshold best candidate — still evidence-backed.
        loose = tag_article(text_title, text_body, min_score=0.0)
        if loose:
            rows = [_match_to_row(article.id, loose[0])]
        else:
            # (3,4) source-based / default fallback — no article evidence, so
            # score 0 and matched_terms empty.
            feed = session.get(Feed, article.feed_id)
            rows = [_synthetic_row(article.id, _fallback_code(feed))]

    for row in rows:
        session.add(row)
    return rows


def tag_all_untagged(session: Session, *, recompute: bool = False) -> tuple[int, int]:
    """Tag every article that has no ArticleCCMD rows yet (or every article
    if ``recompute``). Returns (articles_processed, tags_written)."""
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
