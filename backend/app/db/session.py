"""Database engine, session factory, and FastAPI dependencies."""

from collections.abc import Generator
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def create_db_engine(url: str | None = None, **kwargs: Any) -> Engine:
    """Create a new SQLAlchemy Engine configured with pool_pre_ping=True."""
    database_url = url or get_settings().database_url
    connect_args = kwargs.pop("connect_args", {})
    if database_url.startswith("sqlite"):
        connect_args.setdefault("check_same_thread", False)

    return create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args=connect_args,
        **kwargs,
    )


engine = create_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a transactional database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
