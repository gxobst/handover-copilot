"""API router for dynamic admin settings inspection and reconfiguration."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.admin import AdminSettingsResponse, AdminSettingsUpdate
from app.schemas.errors import ProblemDetails
from app.settings_store import get_admin_settings, update_admin_settings

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get(
    "/settings",
    response_model=AdminSettingsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get active and fallback model settings",
    description="Retrieve the current active and fallback LLM model names.",
    responses={
        401: {"model": ProblemDetails, "description": "Unauthorized"},
    },
)
def get_settings_endpoint(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _: str = Depends(require_admin_token),
) -> AdminSettingsResponse:
    """Return the currently configured active and fallback models."""
    return get_admin_settings(db=db, settings=settings)


@router.put(
    "/settings",
    response_model=AdminSettingsResponse,
    status_code=status.HTTP_200_OK,
    summary="Update active and/or fallback model settings",
    description="Update active and/or fallback model names at runtime without server restart.",
    responses={
        401: {"model": ProblemDetails, "description": "Unauthorized"},
        422: {"model": ProblemDetails, "description": "Unprocessable Entity"},
    },
)
def update_settings_endpoint(
    payload: AdminSettingsUpdate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _: str = Depends(require_admin_token),
) -> AdminSettingsResponse:
    """Update active and/or fallback model names in app_settings table."""
    return update_admin_settings(update=payload, db=db, settings=settings)
