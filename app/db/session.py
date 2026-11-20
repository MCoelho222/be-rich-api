"""Engine and session factory."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_engine: Engine | None = None
SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True)
        SessionLocal.configure(bind=_engine)
    return _engine


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    get_engine()
    with SessionLocal() as session:
        yield session
