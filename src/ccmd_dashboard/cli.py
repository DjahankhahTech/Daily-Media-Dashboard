"""Typer CLI. Step-1 skeleton: only ``init-db`` and ``info`` wired up; the
remaining commands are stubbed so ``--help`` shows the intended workflow."""

from __future__ import annotations

import typer
from rich import print as rprint
from sqlmodel import select

from . import __version__
from .ccmd_loader import load_ccmd_definitions
from .config import settings
from .db import create_all, session_scope
from .feed_loader import load_feed_definitions
from .models import CCMD, Feed

app = typer.Typer(
    name="dashboard",
    help="CCMD Media Intelligence Dashboard — OSW prototype.",
    no_args_is_help=True,
)


@app.command("info")
def info() -> None:
    """Print resolved settings so the operator can sanity-check the environment."""
    rprint(f"[bold]ccmd-dashboard[/bold] v{__version__}")
    rprint(f"  classifier      : {settings.classifier}")
    rprint(f"  database_url    : {settings.database_url}")
    rprint(f"  config_dir      : {settings.config_dir}")
    rprint(f"  data_dir        : {settings.data_dir}")


@app.command("init-db")
def init_db(
    seed: bool = typer.Option(
        True, "--seed/--no-seed", help="Seed CCMDs and feeds from yaml configs."
    ),
) -> None:
    """Create database tables and optionally seed CCMDs + feeds from the
    yaml configs. For the prototype this doubles as the migration entry
    point; Alembic is wired up for the production port path."""
    create_all()
    rprint("[green]created tables[/green]")
    if not seed:
        return

    ccmds = load_ccmd_definitions()
    feeds = load_feed_definitions()
    with session_scope() as session:
        existing_ccmds = {c.code for c in session.exec(select(CCMD)).all()}
        for c in ccmds:
            if c.code in existing_ccmds:
                continue
            session.add(
                CCMD(
                    code=c.code,
                    name=c.name,
                    aor_type=c.aor_type,
                    description=c.description,
                )
            )
        existing_feeds = {f.url for f in session.exec(select(Feed)).all()}
        for f in feeds:
            if f.todo or f.url in existing_feeds:
                continue
            session.add(
                Feed(
                    name=f.name,
                    url=f.url,
                    source_tier=f.source_tier,
                    state_affiliation=f.state_affiliation,
                    language=f.language,
                    notes=f.notes,
                )
            )
    rprint(f"[green]seeded[/green] {len(ccmds)} CCMDs, "
           f"{sum(1 for f in feeds if not f.todo)} feeds "
           f"({sum(1 for f in feeds if f.todo)} TODO entries skipped)")


@app.command("ingest")
def ingest(
    feed: str | None = typer.Option(None, "--feed", help="Feed name."),
    since: str | None = typer.Option(None, "--since", help="ISO date (YYYY-MM-DD)."),
    no_extract: bool = typer.Option(
        False, "--no-extract",
        help="Skip trafilatura full-text extraction (feed summary only).",
    ),
) -> None:
    """Pull articles from one or all configured feeds."""
    from datetime import datetime as _dt

    from .db import session_scope
    from .ingest.pipeline import ingest_all

    since_dt = _dt.fromisoformat(since) if since else None
    with session_scope() as session:
        results = ingest_all(
            session,
            feed_name=feed,
            since=since_dt,
            extract_full=not no_extract,
        )

    if not results:
        rprint("[yellow]no feeds ingested[/yellow]")
        raise typer.Exit(code=1)

    total_new = 0
    for stats in results:
        rprint(stats.as_line())
        total_new += stats.new
        for err in stats.errors:
            rprint(f"  [red]error[/red] {err}")
    rprint(f"[green]{total_new} new article(s)[/green]")


@app.command("tag")
def tag(
    article_id: int | None = typer.Option(None, "--article-id"),
    recompute: bool = typer.Option(False, "--recompute"),
) -> None:
    """[Step 3] Run the AOR tagger over one or all articles."""
    raise typer.Exit(code=2)  # implemented in step 3


@app.command("serve")
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """[Step 4] Launch the FastAPI + HTMX web UI."""
    raise typer.Exit(code=2)  # implemented in step 4


@app.command("demo")
def demo() -> None:
    """[Step 8] Load the canned demo dataset and start the UI in offline mode."""
    raise typer.Exit(code=2)  # implemented in step 8


if __name__ == "__main__":  # pragma: no cover
    app()
