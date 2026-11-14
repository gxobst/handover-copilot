"""Repository interfaces and providers for persistence decoupling."""

from app.db.events_repo import (
    EventRepository,
    InMemoryEventRepository,
    get_event_repository,
)

__all__ = [
    "EventRepository",
    "InMemoryEventRepository",
    "get_event_repository",
]
