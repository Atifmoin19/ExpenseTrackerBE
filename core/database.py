"""SQLAlchemy 2.0 engine + session factory for the Neon Postgres database.

Sync SQLAlchemy (psycopg2 driver) — matches this org's house style (see the
sibling project `mmil-dcms-api`), no async engine needed here.
"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from core.config import settings

# `pool_pre_ping` avoids handing out dead connections after Neon's pooler
# idles one out; Neon's pooled connection string already handles most pooling
# concerns, this is just a safety net for long-lived worker processes.
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Shared declarative base for every ORM model in `models/`."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped SQLAlchemy session, closed
    after the request completes (committed/rolled back explicitly by callers)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
