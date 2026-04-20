"""FastAPI app factory + shared context for the dashboard."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import __version__
from ..config import settings
from ..constants import BANNER_TEXT, MDM_CATEGORY_BANDS
from .deps import ANALYSTS
from .nav import build_tabs
from .scheduler import shutdown_scheduler, start_scheduler

_HERE = Path(__file__).resolve().parent
TEMPLATE_DIR = _HERE / "templates"
STATIC_DIR = _HERE / "static"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def shared_context(request: Request, session, active_tab: str = "HOME") -> dict:
    from .deps import current_analyst

    return {
        "request": request,
        "banner": BANNER_TEXT,
        "version": __version__,
        "classifier_mode": settings.classifier,
        "tabs": build_tabs(request, session),
        "active_tab": active_tab,
        "analysts": ANALYSTS,
        "current_analyst": current_analyst(request),
        "mdm_categories": [band[2] for band in MDM_CATEGORY_BANDS]
        + ["insufficient_data"],
    }


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Pre-warm the corroboration embedder so the first /assess click
    # doesn't block on a multi-second cold-start model load. Safe to skip
    # on failure — corroborate.py degrades cleanly to zero corroborators.
    try:
        from ..classify.corroborate import _embedder
        _embedder()
    except Exception:
        pass
    start_scheduler()
    try:
        yield
    finally:
        shutdown_scheduler()


def create_app() -> FastAPI:
    app = FastAPI(
        title="CCMD Media Intelligence Dashboard",
        version=__version__,
        lifespan=_lifespan,
    )

    from .routes import (
        about, analyst, articles, ccmd, export, home, mdm, notes, unassigned,
    )

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(home.router)
    app.include_router(ccmd.router)
    app.include_router(unassigned.router)
    app.include_router(mdm.router)
    app.include_router(notes.router)
    app.include_router(articles.router)
    app.include_router(analyst.router)
    app.include_router(export.router)
    app.include_router(about.router)

    return app
