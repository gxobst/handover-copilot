from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import Settings, get_settings


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str


router = APIRouter(prefix="/api", tags=["health"])


@router.get("/healthz", response_model=HealthResponse)
def health_check(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """In-memory health check endpoint.

    Fulfills Global Acceptance Criterion AC-9: returns 200 with version + environment
    and does not connect to or touch any database or external service.
    """
    return HealthResponse(
        status="ok",
        version=settings.version,
        environment=settings.environment,
    )
