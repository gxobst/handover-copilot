"""API router for Grafana alert webhook relay and GitHub repository dispatch."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import require_relay_token
from app.schemas.errors import ProblemDetails
from app.schemas.relay import GrafanaAlertPayload, RelayResponse
from app.services.relay import GitHubDispatchError, RelayService, get_relay_service

router = APIRouter(prefix="/api/relay", tags=["relay"])


@router.post(
    "/webhook",
    response_model=RelayResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_200_OK,
    summary="Receive Grafana alert webhook and dispatch GitHub Actions workflow",
    description=(
        "Receives Grafana Cloud alert notifications, verifies webhook secret token, "
        "deduplicates repeated alerts within cooldown window, reshapes alert into "
        "GitHub repository_dispatch event, and triggers incident responder workflow."
    ),
    responses={
        200: {"model": RelayResponse, "description": "Alert successfully processed"},
        401: {"model": ProblemDetails, "description": "Unauthorized (missing or invalid token)"},
        422: {"model": ProblemDetails, "description": "Unprocessable Entity (malformed payload)"},
        502: {"model": ProblemDetails, "description": "Bad Gateway (upstream GitHub failure)"},
    },
)
async def relay_webhook(
    payload: GrafanaAlertPayload,
    relay_service: RelayService = Depends(get_relay_service),
    _: str = Depends(require_relay_token),
) -> RelayResponse:
    """Process incoming Grafana alert notification and dispatch incident workflow."""
    try:
        return await relay_service.process_alert(payload)
    except GitHubDispatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
