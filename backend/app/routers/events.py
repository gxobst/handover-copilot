"""API router for shift event CRUD operations."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.db.events_repo import EventRepository, get_event_repository
from app.schemas.events import SHIFT_KEY_REGEX, EventCreate, EventResponse

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
) -> EventResponse:
    """Create a new event associated with a shift_key."""
    return repo.create(event_in)


@router.get(
    "/events",
    response_model=list[EventResponse],
    status_code=status.HTTP_200_OK,
    summary="List shift events",
    description="Retrieve all events for a given shift_key, ordered chronologically ascending.",
)
def list_events(
    shift_key: str = Query(
        ...,
        pattern=SHIFT_KEY_REGEX,
        description="Shift identifier in YYYY-MM-DD-(early|late|night) format",
    ),
    repo: EventRepository = Depends(get_event_repository),
) -> list[EventResponse]:
    """List events matching the shift_key in ascending chronological order."""
    return repo.list_by_shift(shift_key)


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
