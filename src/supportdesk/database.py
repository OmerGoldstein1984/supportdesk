"""Database engine, session, and declarative base.

WHAT: SQLAlchemy engine, session factory, and declarative Base. Supports SQLite
(local development/tests) and PostgreSQL (docker-compose) via DATABASE_URL env var.
Sessions are short-lived and opened per unit of work.

WHY: Centralizes database configuration so the same code works with SQLite in
local/dev and PostgreSQL in production. The session_scope context manager provides
transactional scope — commit on success, rollback on exception, close always.

INPUTS: DATABASE_URL environment variable.
OUTPUTS: engine, SessionLocal session factory, Base declarative base, session_scope
context manager, get_session function.

FAILURE MODES:
- Wrong DATABASE_URL → fails at import time
- Unclosed session → connection leak (session_scope.close() in finally prevents this)
- SQLite check_same_thread=False required for threaded/FastAPI apps

# GAP: no connection-pool sizing (pool_size, max_overflow) — Postgres under load
#   can exhaust connections
# GAP: no engine echo/SQL logging for debugging slow queries
# BUSINESS: SQLite for local dev, Postgres in prod — schema drift risk (SQLite
#   lenient on types, Postgres strict)
# INTERVIEW: "How do you run migrations when the schema changes?" Answer: init_db
#   uses create_all (dev/tests only); production would need Alembic.
# INTERVIEW: "Why autoflush=False?" Answer: explicit control over when changes
#   hit the database.
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
