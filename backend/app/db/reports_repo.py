"""Handover report repository interfaces and implementations."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import threading
from typing import Any, Optional
from uuid import UUID, uuid4

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Report
from app.db.session import get_db
from app.schemas.reports import OpenAction, ReportResponse


class ReportRepository(ABC):
    """Abstract interface for handover report storage and retrieval."""

    @abstractmethod
    def create(
        self,
        shift_key: str,
        version: int,
        summary: str,
        open_actions: list[Any],
        safety_notes: list[str],
        model_used: str,
        event_count: int,
    ) -> ReportResponse:
        """Create and store a new handover report, returning the stored ReportResponse."""
        pass

    @abstractmethod
    def get_latest_version(self, shift_key: str) -> Optional[int]:
        """Retrieve the latest version number for a shift, or None if no report exists."""
        pass

    @abstractmethod
    def get_by_id(
        self, id: Optional[UUID] = None, report_id: Optional[UUID] = None
    ) -> Optional[ReportResponse]:
        """Retrieve a report by its UUID, or None if not found."""
        pass

    @abstractmethod
    def list_reports(
        self, shift_key: Optional[str] = None, limit: Optional[int] = None
    ) -> list[ReportResponse]:
        """Retrieve reports, optionally filtered by shift_key and bounded by limit."""
        pass

    @abstractmethod
    def list_by_shift(
        self, shift_key: str, limit: Optional[int] = None
    ) -> list[ReportResponse]:
        """Retrieve reports for a given shift_key, ordered by version descending."""
        pass


class InMemoryReportRepository(ReportRepository):
    """Thread-safe in-memory implementation of ReportRepository."""

    def __init__(self) -> None:
        self._reports: dict[UUID, ReportResponse] = {}
        self._lock = threading.Lock()

    def get_latest_version(self, shift_key: str) -> Optional[int]:
        """Retrieve the maximum version number for the given shift_key, or None if no report exists."""
        with self._lock:
            versions = [
                r.version for r in self._reports.values() if r.shift_key == shift_key
            ]
            return max(versions) if versions else None

    def create(
        self,
        shift_key: str,
        version: int,
        summary: str,
        open_actions: list[Any],
        safety_notes: list[str],
        model_used: str,
        event_count: int,
    ) -> ReportResponse:
        """Create and store a new report in memory."""
        with self._lock:
            for r in self._reports.values():
                if r.shift_key == shift_key and r.version == version:
                    raise IntegrityError(
                        "Unique constraint violation: (shift_key, version) must be unique",
                        params=None,
                        orig=Exception("UNIQUE constraint failed"),
                    )

            report_id = uuid4()
            now_utc = datetime.now(timezone.utc)
            actions = [
                OpenAction(**a) if isinstance(a, dict) else a for a in open_actions
            ]
            report = ReportResponse(
                id=report_id,
                shift_key=shift_key,
                version=version,
                summary=summary,
                open_actions=actions,
                safety_notes=list(safety_notes),
                model_used=model_used,
                event_count=event_count,
                created_at=now_utc,
            )
            self._reports[report_id] = report
            return report

    def get_by_id(
        self, id: Optional[UUID] = None, report_id: Optional[UUID] = None
    ) -> Optional[ReportResponse]:
        """Retrieve a report by UUID."""
        target_id = id if id is not None else report_id
        if target_id is None:
            return None
        with self._lock:
            return self._reports.get(target_id)

    def list_reports(
        self, shift_key: Optional[str] = None, limit: Optional[int] = None
    ) -> list[ReportResponse]:
        """Retrieve reports, optionally filtered by shift_key and bounded by limit.

        When shift_key is specified, returns reports for that shift ordered by version desc.
        When shift_key is omitted, returns reports across shifts ordered by created_at desc.
        """
        with self._lock:
            if shift_key is not None:
                matching = [
                    r for r in self._reports.values() if r.shift_key == shift_key
                ]
                sorted_reports = sorted(matching, key=lambda r: r.version, reverse=True)
            else:
                matching = list(self._reports.values())
                sorted_reports = sorted(matching, key=lambda r: r.created_at, reverse=True)

            if limit is not None and limit > 0:
                return sorted_reports[:limit]
            return sorted_reports

    def list_by_shift(
        self, shift_key: str, limit: Optional[int] = None
    ) -> list[ReportResponse]:
        """Retrieve reports for a shift ordered by version descending."""
        return self.list_reports(shift_key=shift_key, limit=limit)

    def clear(self) -> None:
        """Clear all stored reports."""
        with self._lock:
            self._reports.clear()


class SqlReportRepository(ReportRepository):
    """SQLAlchemy-backed implementation of ReportRepository."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_latest_version(self, shift_key: str) -> Optional[int]:
        """Retrieve the maximum version number for the given shift_key via SQL MAX()."""
        stmt = select(func.max(Report.version)).where(Report.shift_key == shift_key)
        return self.session.scalar(stmt)

    def create(
        self,
        shift_key: str,
        version: int,
        summary: str,
        open_actions: list[Any],
        safety_notes: list[str],
        model_used: str,
        event_count: int,
    ) -> ReportResponse:
        """Insert and commit a new Report entity, returning ReportResponse."""
        serialized_actions = [
            a.model_dump() if hasattr(a, "model_dump") else a for a in open_actions
        ]
        report = Report(
            shift_key=shift_key,
            version=version,
            summary=summary,
            open_actions=serialized_actions,
            safety_notes=list(safety_notes),
            model_used=model_used,
            event_count=event_count,
        )
        try:
            self.session.add(report)
            self.session.commit()
            self.session.refresh(report)
            return self._to_response(report)
        except IntegrityError:
            self.session.rollback()
            raise

    def get_by_id(
        self, id: Optional[UUID] = None, report_id: Optional[UUID] = None
    ) -> Optional[ReportResponse]:
        """Retrieve a report by UUID primary key or return None."""
        target_id = id if id is not None else report_id
        if target_id is None:
            return None
        report = self.session.get(Report, target_id)
        if report is None:
            return None
        return self._to_response(report)

    def list_reports(
        self, shift_key: Optional[str] = None, limit: Optional[int] = None
    ) -> list[ReportResponse]:
        """Retrieve reports, optionally filtered by shift_key and bounded by limit.

        When shift_key is specified, returns reports for that shift ordered by version desc.
        When shift_key is omitted, returns reports across shifts ordered by created_at desc.
        """
        stmt = select(Report)
        if shift_key is not None:
            stmt = stmt.where(Report.shift_key == shift_key).order_by(Report.version.desc())
        else:
            stmt = stmt.order_by(Report.created_at.desc())

        if limit is not None and limit > 0:
            stmt = stmt.limit(limit)

        reports = self.session.scalars(stmt).all()
        return [self._to_response(r) for r in reports]

    def list_by_shift(
        self, shift_key: str, limit: Optional[int] = None
    ) -> list[ReportResponse]:
        """Retrieve all reports for a shift ordered by version descending."""
        return self.list_reports(shift_key=shift_key, limit=limit)

    @staticmethod
    def _to_response(report: Report) -> ReportResponse:
        created_at = report.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return ReportResponse(
            id=report.id,
            shift_key=report.shift_key,
            version=report.version,
            summary=report.summary,
            open_actions=report.open_actions,
            safety_notes=report.safety_notes,
            model_used=report.model_used,
            event_count=report.event_count,
            created_at=created_at,
        )


def get_report_repository(
    db: Session = Depends(get_db),
) -> ReportRepository:
    """FastAPI dependency provider returning an SQL-backed report repository."""
    return SqlReportRepository(db)
