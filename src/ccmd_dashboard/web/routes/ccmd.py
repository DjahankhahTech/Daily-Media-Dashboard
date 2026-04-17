"""Per-CCMD tab with filter bar + paginated article list."""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from ...models import CCMD
from ..deps import db_session
from ..queries import ArticleFilters, query_articles

router = APIRouter()

PAGE_SIZE = 25


@router.get("/ccmd/{code}", response_class=HTMLResponse, name="ccmd_view")
def ccmd_view(
    code: str,
    request: Request,
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    tier: str | None = Query(None),
    state: str | None = Query(None),
    mdm: str | None = Query(None),
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    session: Session = Depends(db_session),
):
    from ..app import shared_context, templates

    ccmd = session.get(CCMD, code.upper())
    if ccmd is None:
        raise HTTPException(404, f"unknown CCMD: {code}")

    filters = ArticleFilters(
        date_from=date_from, date_to=date_to, tier=tier, state=state, mdm=mdm, q=q
    )
    rows, total = query_articles(
        session,
        ccmd_code=ccmd.code,
        filters=filters,
        limit=PAGE_SIZE,
        offset=(page - 1) * PAGE_SIZE,
    )
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    def qs(p: int) -> str:
        params: dict[str, str] = {"page": str(p)}
        for k, v in filters.__dict__.items():
            if v:
                params[k] = v
        return urlencode(params)

    ctx = shared_context(request, session, active_tab=ccmd.code)
    ctx.update({
        "ccmd": ccmd,
        "articles": rows,
        "filters": filters,
        "page": page,
        "total": total,
        "total_pages": total_pages,
        "prev_qs": qs(page - 1) if page > 1 else "",
        "next_qs": qs(page + 1) if page < total_pages else "",
    })
    return templates.TemplateResponse(request, "pages/ccmd.html", ctx)
