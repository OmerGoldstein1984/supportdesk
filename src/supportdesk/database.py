"""Database engine, session, and declarative base.

Supports SQLite (local development/tests) and PostgreSQL (docker-compose) via
the ``DATABASE_URL`` environment variable. Sessions are short-lived and opened
per unit of work.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


_engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """Create all tables (idempotent). Used by the seed script and tests."""
    # Import models so they are registered on the metadata.
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=_engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope around a series of operations."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Session:
    """Return a new session (caller must close it). Preferred: use session_scope."""
    return SessionLocal()
