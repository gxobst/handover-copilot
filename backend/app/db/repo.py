"""SQL and in-memory event repository implementations and providers."""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.events_repo import (
    EventRepository,
    InMemoryEventRepository,
)
from app.db.models import Event
from app.db.reports_repo import (
    InMemoryReportRepository,
    ReportRepository,
    SqlReportRepository,
    get_report_repository,
)
from app.db.session import get_db
from app.schemas.events import Category, EventCreate, EventResponse


class SqlEventRepository(EventRepository):
    """SQLAlchemy-backed implementation of EventRepository."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, event_in: EventCreate) -> EventResponse:
        """Insert a new event, commit the transaction, and return the persisted EventResponse."""
        event = Event(
            shift_key=event_in.shift_key,
            machine=event_in.machine,
            category=event_in.category.value if hasattr(event_in.category, "value") else str(event_in.category),
            note=event_in.note,
        )
        self.session.add(event)
        self.session.commit()
        self.session.refresh(event)
        return self._to_response(event)

    def get_by_id(self, event_id: UUID) -> Optional[EventResponse]:
        """Retrieve an event by UUID primary key or return None if not found."""
        event = self.session.get(Event, event_id)
        if event is None:
            return None
        return self._to_response(event)

    def list_by_shift(self, shift_key: str) -> list[EventResponse]:
        """Retrieve all events for a given shift ordered chronologically ascending."""
        stmt = (
            select(Event)
            .where(Event.shift_key == shift_key)
            .order_by(Event.created_at.asc())
        )
        events = self.session.scalars(stmt).all()
        return [self._to_response(e) for e in events]

    def delete(self, event_id: UUID) -> bool:
        """Permanently delete an event by UUID. Returns True if deleted, False if not found."""
        event = self.session.get(Event, event_id)
        if event is None:
            return False
        self.session.delete(event)
        self.session.commit()
        return True

    @staticmethod
    def _to_response(event: Event) -> EventResponse:
        created_at = event.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return EventResponse(
            id=event.id,
            shift_key=event.shift_key,
            machine=event.machine,
            category=Category(event.category),
            note=event.note,
            created_at=created_at,
        )


def get_event_repository(
    db: Session = Depends(get_db),
) -> EventRepository:
    """FastAPI dependency provider returning an SQL-backed event repository."""
    return SqlEventRepository(db)


__all__ = [
    "EventRepository",
    "InMemoryEventRepository",
    "SqlEventRepository",
    "get_event_repository",
    "ReportRepository",
    "InMemoryReportRepository",
    "SqlReportRepository",
    "get_report_repository",
]
