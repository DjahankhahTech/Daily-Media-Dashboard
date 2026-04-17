"""Analyst workflow exports: daily PDF brief + CSV bundle + OIC queue tab.

The PDF brief is generated with WeasyPrint so it mirrors the on-screen
layout and ships the classification banner on every page via CSS fixed
positioning. Runs entirely local — no external PDF service.

The CSV export dumps every article that was reviewed or flagged on the
requested date (one row per article, one row per note — analysts can
slice both in Excel). Date filter defaults to today if omitted.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from sqlmodel import Session, select

from ... import __version__
from ...constants import BANNER_TEXT
from ...models import (
    AnalystAction,
    AnalystNote,
    Article,
    ArticleCCMD,
    Feed,
    MDMAssessment,
)
from ..deps import db_session

router = APIRouter()

_REVIEWED_ACTIONS = {
    AnalystAction.REVIEWED,
    AnalystAction.FLAGGED_FOR_OIC,
    AnalystAction.ESCALATED,
}


@dataclass
class _BriefItem:
    article: Article
    feed: Feed
    ccmd_codes: list[str]
    latest_mdm: Optional[MDMAssessment]
    notes: list[AnalystNote] = field(default_factory=list)


def _parse_day(value: Optional[str]) -> date:
    if value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    return datetime.utcnow().date()


def _collect_items(session: Session, day: date) -> list[_BriefItem]:
    """Notes are authoritative: every article with at least one
    reviewed/flagged/escalated note on the target date goes into the
    brief. This matches how the analyst workflow works in practice."""
    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)
    notes = list(
        session.exec(
            select(AnalystNote)
            .where(AnalystNote.created_at >= start)
            .where(AnalystNote.created_at < end)
            .where(AnalystNote.action_taken.in_([a.value for a in _REVIEWED_ACTIONS]))
            .order_by(AnalystNote.created_at.desc())
        ).all()
    )
    by_article: dict[int, list[AnalystNote]] = defaultdict(list)
    for n in notes:
        by_article[n.article_id].append(n)

    items: list[_BriefItem] = []
    for article_id, note_list in by_article.items():
        article = session.get(Article, article_id)
        if article is None:
            continue
        feed = session.get(Feed, article.feed_id)
        if feed is None:
            continue
        codes = list(
            session.exec(
                select(ArticleCCMD.ccmd_code).where(
                    ArticleCCMD.article_id == article_id
                )
            ).all()
        )
        latest = session.exec(
            select(MDMAssessment)
            .where(MDMAssessment.article_id == article_id)
            .order_by(MDMAssessment.assessed_at.desc())
        ).first()
        items.append(
            _BriefItem(
                article=article, feed=feed,
                ccmd_codes=codes, latest_mdm=latest, notes=note_list,
            )
        )
    return items


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------


@router.get("/export/brief.pdf", name="export_brief_pdf")
def export_brief_pdf(
    request: Request,
    day: Optional[str] = Query(None, description="YYYY-MM-DD"),
    session: Session = Depends(db_session),
):
    from ..app import templates

    target = _parse_day(day)
    items = _collect_items(session, target)
    grouped: dict[str, list[_BriefItem]] = defaultdict(list)
    for item in items:
        if not item.ccmd_codes:
            grouped["(Unassigned)"].append(item)
        else:
            for code in item.ccmd_codes:
                grouped[code].append(item)
    grouped_sorted = [
        {"ccmd": code, "articles": articles}
        for code, articles in sorted(grouped.items())
    ]

    html = templates.get_template("pages/brief.html").render(
        banner=BANNER_TEXT,
        day=target.isoformat(),
        generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        items=items,
        ccmd_count=len({c for item in items for c in item.ccmd_codes}),
        grouped=grouped_sorted,
        version=__version__,
    )

    try:
        from weasyprint import HTML  # type: ignore
    except ImportError:
        # Hard failure beats a silent surprise — analysts need to know the
        # PDF dep is missing rather than getting a misformatted HTML blob.
        return Response(
            "weasyprint not installed; run `uv sync --extra web`.",
            status_code=501,
            media_type="text/plain",
        )

    pdf_bytes = HTML(string=html, base_url=str(request.base_url)).write_pdf()
    filename = f"ccmd-brief-{target.isoformat()}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


@router.get("/export/brief.csv", name="export_brief_csv")
def export_brief_csv(
    day: Optional[str] = Query(None, description="YYYY-MM-DD"),
    session: Session = Depends(db_session),
):
    target = _parse_day(day)
    items = _collect_items(session, target)

    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        "article_id", "title", "source_feed", "source_tier",
        "state_affiliation", "ccmd_codes", "mdm_category", "mdm_concern_score",
        "note_analyst", "note_action", "note_created_at",
        "observation", "significance", "recommended_action", "source_url",
    ])
    for item in items:
        for note in item.notes:
            writer.writerow([
                item.article.id,
                item.article.title,
                item.feed.name,
                item.feed.source_tier,
                item.feed.state_affiliation or "",
                "|".join(item.ccmd_codes),
                item.latest_mdm.category.value if item.latest_mdm else "",
                item.latest_mdm.concern_score if item.latest_mdm else "",
                note.analyst_id,
                note.action_taken.value,
                note.created_at.isoformat(),
                note.observation or "",
                note.significance or "",
                note.recommended_action or "",
                item.article.url,
            ])

    buf.seek(0)
    filename = f"ccmd-brief-{target.isoformat()}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# OIC flag queue tab
# ---------------------------------------------------------------------------


@router.get("/oic", response_class=HTMLResponse, name="oic_queue")
def oic_queue(request: Request, session: Session = Depends(db_session)):
    from ..app import shared_context, templates

    notes = list(
        session.exec(
            select(AnalystNote)
            .where(AnalystNote.action_taken == AnalystAction.FLAGGED_FOR_OIC)
            .order_by(AnalystNote.created_at.desc())
            .limit(200)
        ).all()
    )
    rows: list[dict] = []
    for n in notes:
        article = session.get(Article, n.article_id)
        if article is None:
            continue
        feed = session.get(Feed, article.feed_id)
        if feed is None:
            continue
        rows.append({"note": n, "article": article, "feed": feed})

    ctx = shared_context(request, session, active_tab="OIC")
    ctx.update({"items": rows})
    return templates.TemplateResponse(request, "pages/oic_queue.html", ctx)
