"""Per-CCMD daily narrative.

Builds a small dict per CCMD capturing: count of articles in the window,
top 3 headlines (most recent first, de-duped across the CCMD), and a
short narrative string suitable for rendering on the map overlay and on
a daily-briefing panel.

No LLM. Narrative is deterministic: article counts + top headline theme
extracted from ArticleCCMD.matched_terms. That keeps the page fast, the
output explainable, and the rendering offline-friendly.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import or_
from sqlmodel import Session, select

from ..models import Article, ArticleCCMD, Feed, MDMAssessment, MDMCategory


@dataclass
class Headline:
    article_id: int
    title: str
    feed_name: str
    published_at: Optional[datetime]
    mdm_category: Optional[str]
    mdm_score: Optional[int]


@dataclass
class CCMDDailyBrief:
    code: str
    window_count: int
    total_count: int
    themes: list[str]
    headlines: list[Headline]
    narrative: str
    assessed_count: int
    mean_score: Optional[float]
    dominant_category: Optional[str]


def _window_cutoff(hours: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def _as_aware(ts: Optional[datetime]) -> Optional[datetime]:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _headline_line(h: Headline) -> str:
    when = ""
    if h.published_at:
        ts = _as_aware(h.published_at)
        delta = datetime.now(timezone.utc) - ts if ts else None
        if delta is not None:
            s = int(delta.total_seconds())
            if s < 3600:
                when = f"{max(s // 60, 1)} min ago · "
            elif s < 86400:
                when = f"{s // 3600} h ago · "
            else:
                when = f"{s // 86400} d ago · "
    return f"{when}{h.feed_name}: {h.title}"


def build_brief_for(
    session: Session,
    ccmd_code: str,
    *,
    window_hours: int = 24,
    headline_limit: int = 3,
    theme_limit: int = 4,
) -> CCMDDailyBrief:
    cutoff = _window_cutoff(window_hours)

    # Fetch everything tagged to this CCMD; we'll split into window vs total.
    rows = list(session.exec(
        select(ArticleCCMD, Article, Feed)
        .join(Article, Article.id == ArticleCCMD.article_id)
        .join(Feed, Feed.id == Article.feed_id)
        .where(ArticleCCMD.ccmd_code == ccmd_code)
    ).all())

    seen_article_ids: set[int] = set()
    in_window: list[tuple[ArticleCCMD, Article, Feed]] = []
    all_for_ccmd: list[tuple[ArticleCCMD, Article, Feed]] = []
    for (tag, article, feed) in rows:
        if article.id in seen_article_ids:
            continue
        seen_article_ids.add(article.id)
        all_for_ccmd.append((tag, article, feed))
        anchor = _as_aware(article.published_at) or _as_aware(article.fetched_at)
        if anchor and anchor >= cutoff:
            in_window.append((tag, article, feed))

    in_window.sort(
        key=lambda t: _as_aware(t[1].published_at) or _as_aware(t[1].fetched_at) or cutoff,
        reverse=True,
    )

    # MDM aggregates across the latest assessment per article in the window.
    article_ids_window = [a.id for (_, a, _) in in_window]
    assessments: list[MDMAssessment] = []
    if article_ids_window:
        assessments = list(session.exec(
            select(MDMAssessment).where(MDMAssessment.article_id.in_(article_ids_window))
        ).all())
    latest_by_article: dict[int, MDMAssessment] = {}
    for a in assessments:
        prev = latest_by_article.get(a.article_id)
        if prev is None or (a.assessed_at and prev.assessed_at and a.assessed_at > prev.assessed_at):
            latest_by_article[a.article_id] = a

    cat_counter: Counter[str] = Counter()
    scored: list[int] = []
    for a in latest_by_article.values():
        cat_counter[a.category.value] += 1
        if a.concern_score is not None:
            scored.append(a.concern_score)
    mean_score = round(sum(scored) / len(scored), 1) if scored else None
    real_cats = {k: v for k, v in cat_counter.items()
                 if k != MDMCategory.INSUFFICIENT_DATA.value}
    dominant = (max(real_cats, key=lambda k: real_cats[k])
                if real_cats else (max(cat_counter, key=lambda k: cat_counter[k])
                                   if cat_counter else None))

    # Themes: most common matched_terms across the window.
    term_counter: Counter[str] = Counter()
    for (tag, _, _) in in_window:
        for t in (tag.matched_terms or [])[:6]:
            # Normalize — dedupe trivial case differences.
            term_counter[t.strip()] += 1
    themes = [t for t, _ in term_counter.most_common(theme_limit) if t]

    headlines = []
    for (_, article, feed) in in_window[:headline_limit]:
        latest = latest_by_article.get(article.id)
        headlines.append(Headline(
            article_id=article.id,
            title=article.title or "(untitled)",
            feed_name=feed.name,
            published_at=article.published_at or article.fetched_at,
            mdm_category=latest.category.value if latest else None,
            mdm_score=latest.concern_score if latest else None,
        ))

    # Narrative — one sentence, deterministic.
    if in_window:
        theme_bit = (f" — themes: {', '.join(themes)}" if themes else "")
        score_bit = (f"; mean MDM {mean_score} ({dominant.replace('_', ' ')})"
                     if mean_score is not None and dominant else "")
        narrative = (
            f"{len(in_window)} article(s) in the last {window_hours} h"
            f"{theme_bit}{score_bit}."
        )
    else:
        narrative = f"No new articles in the last {window_hours} h."

    return CCMDDailyBrief(
        code=ccmd_code,
        window_count=len(in_window),
        total_count=len(all_for_ccmd),
        themes=themes,
        headlines=headlines,
        narrative=narrative,
        assessed_count=len(latest_by_article),
        mean_score=mean_score,
        dominant_category=dominant,
    )


def build_briefs(
    session: Session, ccmd_codes: Iterable[str], *, window_hours: int = 24,
) -> dict[str, CCMDDailyBrief]:
    return {code: build_brief_for(session, code, window_hours=window_hours)
            for code in ccmd_codes}
