"""Top-nav configuration. All tabs render with zero articles so the
walkthrough can demonstrate UI structure before ingestion."""

from dataclasses import dataclass

from fastapi import Request
from sqlmodel import Session, select

from ..models import CCMD, AORType


@dataclass
class Tab:
    code: str
    label: str
    href: str


def build_tabs(request: Request, session: Session) -> list[Tab]:
    ccmds = session.exec(
        select(CCMD).order_by(CCMD.aor_type, CCMD.code)
    ).all()

    # Group by aor_type so the nav reads: geographic block | functional block | utility tabs.
    geo = [c for c in ccmds if c.aor_type == AORType.GEOGRAPHIC]
    fun = [c for c in ccmds if c.aor_type == AORType.FUNCTIONAL]

    tabs: list[Tab] = [Tab(code="HOME", label="Home", href=str(request.url_for("home")))]
    for c in geo + fun:
        tabs.append(Tab(code=c.code, label=c.code, href=str(request.url_for("ccmd_view", code=c.code))))
    tabs.append(Tab(code="UNASSIGNED", label="Unassigned", href=str(request.url_for("unassigned_view"))))
    tabs.append(Tab(code="MDM", label="MDM Queue", href=str(request.url_for("mdm_queue"))))
    tabs.append(Tab(code="NOTES", label="Analyst Notes", href=str(request.url_for("notes_view"))))
    tabs.append(Tab(code="ABOUT", label="About", href=str(request.url_for("about_view"))))
    return tabs
