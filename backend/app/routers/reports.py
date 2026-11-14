"""API router for handover report generation and retrieval."""

from fastapi import APIRouter, Depends, status

from app.schemas.reports import ReportGenerateRequest, ReportResponse
from app.services.handover import HandoverService, get_handover_service

router = APIRouter(prefix="/api", tags=["reports"])


@router.post(
    "/reports/generate",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate shift handover report",
    description="Generate, validate, and persist a structured handover report for a shift using LLM with fallback.",
)
def generate_report_endpoint(
    request: ReportGenerateRequest,
    service: HandoverService = Depends(get_handover_service),
) -> ReportResponse:
    """Generate a handover report for the given shift_key with fallback handling."""
    return service.generate_report(request.shift_key)
