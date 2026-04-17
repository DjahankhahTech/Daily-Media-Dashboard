"""Analyst notes tab + note creation."""

from dataclasses import dataclass

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from ...models import AnalystAction, AnalystNote, Article
from ..deps import current_analyst, db_session

router = APIRouter()


@dataclass
class _NoteRow:
    note: AnalystNote
    article: Article


@router.get("/notes", response_class=HTMLResponse, name="notes_view")
def notes_view(request: Request, session: Session = Depends(db_session)):
    from ..app import shared_context, templates

    notes = list(
        session.exec(
            select(AnalystNote).order_by(AnalystNote.created_at.desc()).limit(200)
        ).all()
    )
    rows: list[_NoteRow] = []
    for n in notes:
        article = session.get(Article, n.article_id)
        if article is None:
            continue
        rows.append(_NoteRow(note=n, article=article))

    ctx = shared_context(request, session, active_tab="NOTES")
    ctx.update({"notes": rows})
    return templates.TemplateResponse(request, "pages/notes.html", ctx)


@router.post("/articles/{article_id}/notes", name="add_note")
def add_note(
    article_id: int,
    request: Request,
    observation: str = Form(""),
    significance: str = Form(""),
    recommended_action: str = Form(""),
    action_taken: str = Form("reviewed"),
    session: Session = Depends(db_session),
):
    article = session.get(Article, article_id)
    if article is None:
        raise HTTPException(404, "article not found")
    try:
        action_enum = AnalystAction(action_taken)
    except ValueError:
        action_enum = AnalystAction.REVIEWED

    note = AnalystNote(
        article_id=article_id,
        analyst_id=current_analyst(request),
        observation=observation.strip() or None,
        significance=significance.strip() or None,
        recommended_action=recommended_action.strip() or None,
        action_taken=action_enum,
    )
    session.add(note)
    session.commit()
    return RedirectResponse(
        url=str(request.url_for("article_detail", article_id=article_id)),
        status_code=303,
    )


@router.post("/articles/{article_id}/notes/new", name="add_note_form")
def add_note_form(article_id: int, request: Request):
    """Convenience redirect from the detail-page 'Add note' button so the
    form below the MDM section scrolls into view."""
    return RedirectResponse(
        url=f"/articles/{article_id}#add-note", status_code=303
    )
