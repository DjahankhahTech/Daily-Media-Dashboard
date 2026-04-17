"""Request-scoped dependencies: DB session, current analyst, tab config."""

from collections.abc import Iterator

from fastapi import Request
from sqlmodel import Session

from ..db import get_engine

# Prototype: localhost-only. No auth. Analyst identity is a cookie-picked
# value from a fixed list so a walk-through can show per-analyst notes.
ANALYSTS = ["demo", "watch-floor-1", "OSW-staff", "ICC-staff"]
DEFAULT_ANALYST = ANALYSTS[0]
ANALYST_COOKIE = "ccmd_analyst"


def db_session() -> Iterator[Session]:
    session = Session(get_engine())
    try:
        yield session
    finally:
        session.close()


def current_analyst(request: Request) -> str:
    value = request.cookies.get(ANALYST_COOKIE)
    if value in ANALYSTS:
        return value
    return DEFAULT_ANALYST
