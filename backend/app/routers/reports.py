"""API router for handover report generation and retrieval."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.db.reports_repo import ReportRepository, get_report_repository
from app.errors import ReportNotFoundException
from app.schemas.events import SHIFT_KEY_REGEX
from app.schemas.reports import (
    ReportGenerateRequest,
    ReportResponse,
    ReportSummary,
)
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


@router.get(
    "/reports",
    response_model=list[ReportSummary],
    status_code=status.HTTP_200_OK,
    summary="List shift handover report summaries",
    description="Retrieve handover report summaries optionally filtered by shift_key and bounded by limit.",
)
def list_reports(
    shift_key: Optional[str] = Query(
        default=None,
        pattern=SHIFT_KEY_REGEX,
        description="Shift identifier in YYYY-MM-DD-(early|late|night) format",
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of report summaries to return (1-100)",
    ),
    repo: ReportRepository = Depends(get_report_repository),
) -> list[ReportSummary]:
    """Retrieve report summaries across shifts or for a specific shift."""
    reports = repo.list_reports(shift_key=shift_key, limit=limit)
    return [ReportSummary.model_validate(r) for r in reports]


@router.get(
    "/reports/{id}",
    response_model=ReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Get shift handover report detail",
    description="Retrieve a complete immutable handover report snapshot by ID.",
)
def get_report_detail(
    id: UUID,
    repo: ReportRepository = Depends(get_report_repository),
) -> ReportResponse:
    """Retrieve full handover report details by ID."""
    report = repo.get_by_id(id)
    if report is None:
        raise ReportNotFoundException(id)
    return report
