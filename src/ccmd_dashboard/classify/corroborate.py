"""Corroboration: count articles from DIFFERENT feeds in the last N hours
whose embedding is above a cosine-similarity threshold to the target.

Embeddings use sentence-transformers ``all-MiniLM-L6-v2`` (runs locally,
no API call). The model is loaded lazily and cached in-process.

If sentence-transformers is not installed (prototype without the
``classify`` extras) the function returns 0 corroborators and logs a
warning; the scorer treats that as "low corroboration" per its weight.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional

from sqlalchemy import func
from sqlmodel import Session, select

from ..config import settings
from ..models import Article, Feed

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _embedder():
    """Return the embedder, or None if it cannot be loaded.

    Both the missing-package path and the missing-local-model path cache
    the ``None`` result so repeated calls don't log or retry. Corroboration
    degrades cleanly to zero-count in that case.
    """
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except ImportError:  # pragma: no cover - extras gate
        log.warning(
            "sentence-transformers not installed; corroboration returns 0. "
            "Install with `uv sync --extra classify`."
        )
        return None
    try:
        return SentenceTransformer("all-MiniLM-L6-v2")
    except Exception as exc:
        log.warning(
            "could not load all-MiniLM-L6-v2 (%s); corroboration returns 0. "
            "Pre-download the model to enable corroboration.",
            exc,
        )
        return None


def _vector(text: str):
    model = _embedder()
    if model is None:
        return None
    return model.encode([text[:4000]], normalize_embeddings=True)[0]


def _cosine(a, b) -> float:
    # Vectors are L2-normalized by the embedder -> cosine == dot product.
    return float((a * b).sum())


def find_corroborators(
    session: Session,
    article: Article,
    *,
    threshold: Optional[float] = None,
    window_hours: Optional[int] = None,
) -> tuple[int, list[int]]:
    """Return (count, corroborating_article_ids).

    "Corroborating" means: from a different feed, within the window,
    cosine similarity >= threshold on title+first-500-body embedding.
    """
    threshold = threshold if threshold is not None else settings.corroboration_similarity_threshold
    window = window_hours if window_hours is not None else settings.corroboration_window_hours

    target_vec = _vector(
        f"{article.title}\n{(article.raw_text or article.summary or '')[:2000]}"
    )
    if target_vec is None:
        return 0, []

    anchor = article.published_at or article.fetched_at
    cutoff = (anchor or datetime.utcnow()) - timedelta(hours=window)

    candidates = list(
        session.exec(
            select(Article)
            .where(Article.id != article.id)
            .where(Article.feed_id != article.feed_id)
            .where(func.coalesce(Article.published_at, Article.fetched_at) >= cutoff)
        ).all()
    )
    if not candidates:
        return 0, []

    feeds_seen: set[int] = set()
    hits: list[int] = []
    for cand in candidates:
        if cand.feed_id in feeds_seen:
            # At most one corroborator per feed; two reruns of the same
            # story by the same wire shouldn't inflate the count.
            continue
        cand_vec = _vector(
            f"{cand.title}\n{(cand.raw_text or cand.summary or '')[:2000]}"
        )
        if cand_vec is None:
            continue
        sim = _cosine(target_vec, cand_vec)
        if sim >= threshold:
            hits.append(cand.id)
            feeds_seen.add(cand.feed_id)
    return len(hits), hits
