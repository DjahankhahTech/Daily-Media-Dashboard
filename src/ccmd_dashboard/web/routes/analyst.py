"""Set the current analyst via cookie (localhost dropdown)."""

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse

from ..deps import ANALYST_COOKIE, ANALYSTS, DEFAULT_ANALYST

router = APIRouter()


@router.get("/analyst", name="set_analyst")
def set_analyst(request: Request, analyst_id: str = Query(...), next: str = Query("/")):
    target = analyst_id if analyst_id in ANALYSTS else DEFAULT_ANALYST
    resp = RedirectResponse(url=next or "/", status_code=303)
    resp.set_cookie(ANALYST_COOKIE, target, httponly=True, samesite="lax")
    return resp
