"""Event repository interfaces and in-memory implementations."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import threading
from typing import Optional
from uuid import UUID, uuid4

from app.schemas.events import EventCreate, EventResponse


class EventRepository(ABC):
    """Abstract interface for event storage and retrieval."""

    @abstractmethod
    def create(self, event_in: EventCreate) -> EventResponse:
        """Create and store a new event, returning the stored EventResponse."""
        pass

    @abstractmethod
    def get_by_id(self, event_id: UUID) -> Optional[EventResponse]:
        """Retrieve an event by its unique UUID, or None if not found."""
        pass

    @abstractmethod
    def list_by_shift(self, shift_key: str) -> list[EventResponse]:
        """Retrieve all events for a given shift_key, ordered chronologically by created_at ascending."""
        pass

    @abstractmethod
    def delete(self, event_id: UUID) -> bool:
        """Permanently delete an event by its UUID. Returns True if deleted, False if not found."""
        pass


class InMemoryEventRepository(EventRepository):
    """Thread-safe in-memory implementation of EventRepository."""

    def __init__(self) -> None:
        self._events: dict[UUID, EventResponse] = {}
        self._lock = threading.Lock()

    def create(self, event_in: EventCreate) -> EventResponse:
        """Create and store a new event, returning the stored EventResponse."""
        event_id = uuid4()
        now_utc = datetime.now(timezone.utc)
        event = EventResponse(
            id=event_id,
            shift_key=event_in.shift_key,
            machine=event_in.machine,
            category=event_in.category,
            note=event_in.note,
            created_at=now_utc,
        )
        with self._lock:
            self._events[event_id] = event
        return event

    def get_by_id(self, event_id: UUID) -> Optional[EventResponse]:
        """Retrieve an event by its unique UUID, or None if not found."""
        with self._lock:
            return self._events.get(event_id)

    def list_by_shift(self, shift_key: str) -> list[EventResponse]:
        """Retrieve all events for a given shift_key, ordered chronologically by created_at ascending."""
        with self._lock:
            matching = [
                event for event in self._events.values() if event.shift_key == shift_key
            ]
        return sorted(matching, key=lambda e: e.created_at)

    def delete(self, event_id: UUID) -> bool:
        """Permanently delete an event by its UUID. Returns True if deleted, False if not found."""
        with self._lock:
            if event_id in self._events:
                del self._events[event_id]
                return True
            return False

    def clear(self) -> None:
        """Clear all stored events (primarily for testing)."""
        with self._lock:
            self._events.clear()


_in_memory_repository = InMemoryEventRepository()


def __getattr__(name: str):
    if name in ("SqlEventRepository", "get_event_repository"):
        from app.db import repo
        return getattr(repo, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

