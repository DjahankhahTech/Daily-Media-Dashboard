"""Database engine + session management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel

from .config import settings

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings.ensure_dirs()
        _engine = create_engine(
            settings.database_url,
            echo=False,
            connect_args={"check_same_thread": False}
            if settings.database_url.startswith("sqlite")
            else {},
        )
    return _engine


def create_all() -> None:
    """Create tables from SQLModel metadata. Used as a development shortcut;
    production path is Alembic migrations."""
    from . import models  # noqa: F401  - register models with metadata

    SQLModel.metadata.create_all(get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    session = Session(get_engine())
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
