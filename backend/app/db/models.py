"""SQLAlchemy declarative models for Shift Handover Copilot."""

from datetime import datetime, timezone
from typing import Any, Optional
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    JSON,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class UtcDateTime(TypeDecorator):
    """DateTime type that guarantees timezone-awareness (UTC) across SQLite and PostgreSQL."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(
        self, value: Optional[datetime], dialect: Any
    ) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    def process_bind_param(
        self, value: Optional[datetime], dialect: Any
    ) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models."""

    pass


class Event(Base):
    """Event domain model representing an event logged during a shift."""

    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    shift_key: Mapped[str] = mapped_column(String, nullable=False)
    machine: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "category IN ('downtime', 'quality', 'safety', 'info')",
            name="ck_events_category",
        ),
        CheckConstraint(
            "length(note) BETWEEN 1 AND 2000",
            name="ck_events_note_length",
        ),
        Index("idx_events_shift", "shift_key", "created_at"),
    )


class Report(Base):
    """Report domain model representing an immutable handover report snapshot."""

    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    shift_key: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    open_actions: Mapped[Any] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
    )
    safety_notes: Mapped[Any] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
    )
    model_used: Mapped[str] = mapped_column(String, nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("shift_key", "version", name="uq_reports_shift_key_version"),
    )


class AppSetting(Base):
    """Key-value application settings persisted in the database."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        onupdate=func.now(),
    )
