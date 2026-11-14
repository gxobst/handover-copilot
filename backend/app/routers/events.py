"""API router for shift event CRUD operations."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.config import Settings, get_settings
from app.db.repo import EventRepository, get_event_repository
from app.schemas.events import SHIFT_KEY_REGEX, EventCreate, EventResponse
from app.telemetry import get_logger, record_event_created

router = APIRouter(prefix="/api", tags=["events"])


@router.post(
    "/events",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a shift event",
    description="Record a new shift event with machine, category, and note.",
)
def create_event(
    event_in: EventCreate,
    repo: EventRepository = Depends(get_event_repository),
    settings: Settings = Depends(get_settings),
) -> EventResponse:
    """Create a new event associated with a shift_key."""
    created = repo.create(event_in)
    record_event_created(env=settings.environment, version=settings.version)
    logger = get_logger("events")
    category_str = (
        created.category.value
        if hasattr(created.category, "value")
        else str(created.category)
    )
    logger.info(
        "Shift event created",
        shift_key=created.shift_key,
        category=category_str,
        event_id=str(created.id),
    )
    return created


@router.get(
    "/events",
    response_model=list[EventResponse],
    status_code=status.HTTP_200_OK,
    summary="List shift events",
    description="Retrieve all events for a given shift_key, ordered chronologically ascending.",
)
def list_events(
    shift_key: Optional[str] = Query(
        default=None,
        pattern=SHIFT_KEY_REGEX,
        alias="shift_key",
        description="Shift identifier in YYYY-MM-DD-(early|late|night) format",
    ),
    shiftKey: Optional[str] = Query(
        default=None,
        pattern=SHIFT_KEY_REGEX,
        alias="shiftKey",
        description="Shift identifier in YYYY-MM-DD-(early|late|night) format (camelCase alias)",
    ),
    repo: EventRepository = Depends(get_event_repository),
) -> list[EventResponse]:
    """List events matching the shift_key in ascending chronological order."""
    target_key = shift_key or shiftKey
    if not target_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="query -> shift_key: Field required",
        )
    return repo.list_by_shift(target_key)


@router.delete(
    "/events/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a shift event",
)
def delete_event(
    id: UUID,
    repo: EventRepository = Depends(get_event_repository),
) -> Response:
    """Delete an event by its unique ID. Returns 204 on success, 404 if not found."""
    deleted = repo.delete(id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event with id '{id}' not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
