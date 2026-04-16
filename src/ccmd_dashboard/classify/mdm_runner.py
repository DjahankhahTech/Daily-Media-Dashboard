"""MDM orchestration: extract (stage 1) -> score (stage 2) -> persist.

Called by:
  - the FastAPI POST /articles/{id}/assess endpoint (queues a job)
  - apscheduler background runner
  - the demo loader (step 8) to bulk-assess the canned dataset

Idempotency: re-assessing an article appends a new MDMAssessment row so
the audit trail is preserved. The UI always displays the latest row.
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime

from sqlmodel import Session

from ..models import Article, Feed, MDMAssessment, MDMCategory
from .classifier import ArticleForExtraction, Classifier, get_classifier
from .corroborate import find_corroborators
from .mdm_types import MDMExtraction
from .scoring import SCORING_VERSION, ScoreInput, score

log = logging.getLogger(__name__)


def _article_payload(article: Article, feed: Feed) -> ArticleForExtraction:
    body = article.raw_text or article.summary or ""
    return ArticleForExtraction(
        title=article.title or "",
        body=body,
        source_name=feed.name,
        source_tier=feed.source_tier,
        state_affiliation=feed.state_affiliation,
        published_at_iso=(article.published_at or article.fetched_at).isoformat()
        if (article.published_at or article.fetched_at)
        else None,
    )


def _extraction_to_json(e: MDMExtraction) -> dict:
    """Pydantic -> plain dict for JSON columns."""
    return {
        "verifiable_claims": [c.model_dump() for c in e.verifiable_claims],
        "emotional_language": list(e.emotional_language),
        "logical_fallacies": [f.model_dump() for f in e.logical_fallacies],
        "unsourced_assertions": list(e.unsourced_assertions),
        "temporal_claims": [t.model_dump() for t in e.temporal_claims],
        "source_transparency_score": e.source_transparency_score,
        "anomalies": list(e.anomalies),
    }


def assess_article(
    session: Session,
    article_id: int,
    *,
    classifier: Classifier | None = None,
) -> MDMAssessment:
    """Run stage 1 + stage 2 for one article and persist the assessment."""
    article = session.get(Article, article_id)
    if article is None:
        raise LookupError(f"article {article_id} not found")
    feed = session.get(Feed, article.feed_id)
    if feed is None:
        raise LookupError(f"feed {article.feed_id} not found")

    classifier = classifier or get_classifier()

    assessment = MDMAssessment(
        article_id=article.id,
        assessed_at=datetime.utcnow(),
        classifier_version=f"{classifier.version}|{SCORING_VERSION}",
        category=MDMCategory.INSUFFICIENT_DATA,
    )
    session.add(assessment)

    try:
        extraction = classifier.extract(_article_payload(article, feed))
    except Exception as exc:
        log.exception("stage 1 extraction failed for article %s", article_id)
        assessment.failure_reason = f"stage1: {type(exc).__name__}: {exc}"
        session.commit()
        return assessment

    assessment.verifiable_claims = [c.model_dump() for c in extraction.verifiable_claims]
    assessment.emotional_language = list(extraction.emotional_language)
    assessment.logical_fallacies = [f.model_dump() for f in extraction.logical_fallacies]
    assessment.unsourced_assertions = list(extraction.unsourced_assertions)
    assessment.temporal_claims = [t.model_dump() for t in extraction.temporal_claims]
    assessment.source_transparency_score = extraction.source_transparency_score

    try:
        corroboration_count, corroborating_ids = find_corroborators(session, article)
    except Exception as exc:  # embedder failure shouldn't take down the score
        log.warning("corroboration failed for article %s: %s", article_id, exc)
        corroboration_count, corroborating_ids = 0, []

    assessment.corroboration_count = corroboration_count
    assessment.corroborating_article_ids = corroborating_ids

    try:
        result = score(
            ScoreInput(
                source_tier=feed.source_tier,
                state_affiliation=feed.state_affiliation,
                extraction=extraction,
                corroboration_count=corroboration_count,
            )
        )
    except Exception as exc:
        log.exception("stage 2 scoring failed for article %s", article_id)
        assessment.failure_reason = f"stage2: {type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        session.commit()
        return assessment

    assessment.concern_score = result.concern_score
    assessment.category = result.category
    assessment.reasoning_breakdown = result.reasoning_breakdown()
    session.commit()
    session.refresh(assessment)
    return assessment
