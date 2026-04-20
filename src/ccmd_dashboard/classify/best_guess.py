"""Best-guess AOR tagger for articles that didn't match any keyword list.

The primary tagger (aor_tagger.py) is keyword- and NER-driven: it matches
the article body and title against per-CCMD keyword lists. Stories that
are legitimately about a region but don't happen to name a keyword slip
into the Unassigned bucket — a ``TASS`` piece about domestic Russian
economics, for example, never names NATO bases or Ukrainian cities but
is clearly EUCOM-relevant because the outlet is Russia-affiliated.

This module fills that gap with a source-based best guess. It runs
AFTER the primary tagger and only touches articles with zero primary
matches. Best-guess rows are marked ``tagged_by="best_guess_source"``
so the UI can render them with a "BG" badge and the analyst can tell
them apart from keyword-matched tags.

Mapping rules (in priority order):
  1. Feed state_affiliation (ISO-3166 alpha-2) → CCMD
  2. Feed source_tier 1 (USG) → NORTHCOM (weak default; homeland-defense
     AOR is the least-wrong fallback for unattributed DoD-adjacent
     reporting)

If neither rule fires, the article stays Unassigned.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlmodel import Session, select

from ..models import Article, ArticleCCMD, Feed

log = logging.getLogger(__name__)

BEST_GUESS_TAGGER_VERSION = "best_guess_source_v1"
BEST_GUESS_MATCH_SCORE = 0.0  # below the primary threshold so any real
                              # match would win during a recompute.

# State-affiliated outlets map to the CCMD responsible for that state.
# Keep conservative: only list country codes where the mapping is
# uncontroversial. Edit by analyst review.
STATE_TO_CCMD: dict[str, str] = {
    "RU": "EUCOM",       # Russia — EUCOM AOR
    "BY": "EUCOM",       # Belarus
    "UA": "EUCOM",       # Ukraine (target of EUCOM reporting)
    "CN": "INDOPACOM",   # China
    "KP": "INDOPACOM",   # DPRK
    "IR": "CENTCOM",     # Iran
    "SY": "CENTCOM",     # Syria
    "VE": "SOUTHCOM",    # Venezuela
    "CU": "SOUTHCOM",    # Cuba
}


def _guess_ccmd_for(feed: Feed) -> Optional[str]:
    if feed.state_affiliation:
        guessed = STATE_TO_CCMD.get(feed.state_affiliation.upper())
        if guessed:
            return guessed
    if feed.source_tier == 1:
        return "NORTHCOM"
    return None


def best_guess_untagged(session: Session) -> tuple[int, int]:
    """Insert a best-guess ArticleCCMD row for every article with zero
    tags whose feed has a usable default. Returns (considered, written).
    """
    articles = list(session.exec(select(Article)).all())
    feeds_by_id: dict[int, Feed] = {
        f.id: f for f in session.exec(select(Feed)).all()  # type: ignore[misc]
    }

    tagged_ids: set[int] = set(
        session.exec(select(ArticleCCMD.article_id).distinct()).all()
    )

    considered = 0
    written = 0
    for article in articles:
        if article.id in tagged_ids:
            continue
        considered += 1
        feed = feeds_by_id.get(article.feed_id)
        if feed is None:
            continue
        guess = _guess_ccmd_for(feed)
        if guess is None:
            continue
        session.add(ArticleCCMD(
            article_id=article.id,
            ccmd_code=guess,
            match_score=BEST_GUESS_MATCH_SCORE,
            matched_terms=[],
            tagged_by=BEST_GUESS_TAGGER_VERSION,
        ))
        written += 1

    if written:
        session.commit()
    log.info("best-guess pass: considered %d untagged, wrote %d rows",
             considered, written)
    return considered, written
