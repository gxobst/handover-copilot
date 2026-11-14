"""Integration tests for report history and detail API endpoints.

Covers Issue #7 acceptance criteria:
- GET /api/reports: empty DB, unfiltered (sorted by created_at desc), shift filtered (sorted by version desc), limit capping
- GET /api/reports: parameter validation (invalid limit, malformed shift_key) returning 422 ProblemDetails
- GET /api/reports: exclusion of content fields (summary, open_actions, safety_notes)
- GET /api/reports/{id}: 200 with full ReportResponse
- GET /api/reports/{id}: 404 with RFC 9457 ProblemDetails (title "Report Not Found")
- GET /api/reports/{id}: 422 with RFC 9457 ProblemDetails on malformed non-UUID
- Repository methods and dependency injection override
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from fastapi import status
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Report
from app.db.reports_repo import (
    InMemoryReportRepository,
    SqlReportRepository,
    get_report_repository,
)
from app.db.session import create_db_engine, get_db
from app.main import app, create_app
from app.schemas.errors import ProblemDetails
from app.schemas.reports import OpenAction, ReportResponse, ReportSummary


@pytest.fixture
def test_db_path(tmp_path: Path) -> Path:
    """Provide a path for an isolated temporary SQLite database."""
    return tmp_path / "test_report_history.db"


@pytest.fixture
def test_db_url(test_db_path: Path) -> str:
    """Provide SQLite URL for the isolated temporary database."""
    return f"sqlite:///{test_db_path.as_posix()}"


@pytest.fixture
def alembic_config(test_db_url: str) -> Config:
    """Provide Alembic Config pointing to the temporary test database."""
    backend_dir = Path(__file__).resolve().parent.parent
    ini_path = backend_dir / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("sqlalchemy.url", test_db_url)
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    return cfg


@pytest.fixture
def db_session(alembic_config: Config, test_db_url: str) -> Generator[Session, None, None]:
    """Run Alembic migrations to head and provide transactional session."""
    command.upgrade(alembic_config, "head")
    engine = create_db_engine(test_db_url)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """Provide a TestClient with get_db overridden to the test session."""
    test_app = create_app()
    test_app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(test_app) as tc:
        yield tc
    test_app.dependency_overrides.clear()


@pytest.fixture
def sql_repo(db_session: Session) -> SqlReportRepository:
    """Provide a SqlReportRepository instance bound to the test session."""
    return SqlReportRepository(db_session)


# ---------------------------------------------------------------------------
# Helper: Seed Reports
# ---------------------------------------------------------------------------


def create_persisted_report(
    session: Session,
    shift_key: str,
    version: int,
    created_at: datetime,
    summary: str = "Test summary",
    open_actions: list = None,
    safety_notes: list = None,
    model_used: str = "gemini-3.5-flash-lite",
    event_count: int = 5,
) -> Report:
    """Helper to seed a Report directly into the database session."""
    if open_actions is None:
        open_actions = [
            {"action": "Check lubrication pressure", "owner": "Maintenance Lead", "priority": "high"}
        ]
    if safety_notes is None:
        safety_notes = ["Emergency stop on Press-1 tested OK"]

    report = Report(
        shift_key=shift_key,
        version=version,
        summary=summary,
        open_actions=open_actions,
        safety_notes=safety_notes,
        model_used=model_used,
        event_count=event_count,
        created_at=created_at,
    )
    session.add(report)
    session.commit()
    session.refresh(report)
    return report


# ---------------------------------------------------------------------------
# GET /api/reports Tests (List, Filter, Sort, Limit)
# ---------------------------------------------------------------------------


def test_list_reports_empty_db_returns_200_empty_list(client: TestClient) -> None:
    """Verify list reports with empty database returns HTTP 200 and empty JSON array []."""
    response = client.get("/api/reports")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == []


def test_list_reports_unfiltered_sorted_by_created_at_desc(
    client: TestClient, db_session: Session
) -> None:
    """Verify list reports without shift_key returns reports across shifts ordered by created_at descending."""
    base_time = datetime(2026, 11, 14, 10, 0, 0, tzinfo=timezone.utc)

    r1 = create_persisted_report(
        db_session,
        shift_key="2026-11-14-early",
        version=1,
        created_at=base_time - timedelta(hours=2),
    )
    r2 = create_persisted_report(
        db_session,
        shift_key="2026-11-14-late",
        version=1,
        created_at=base_time - timedelta(hours=1),
    )
    r3 = create_persisted_report(
        db_session,
        shift_key="2026-11-14-early",
        version=2,
        created_at=base_time,
    )

    response = client.get("/api/reports")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    assert len(data) == 3
    # Check ordering by created_at desc (r3, r2, r1)
    assert data[0]["id"] == str(r3.id)
    assert data[1]["id"] == str(r2.id)
    assert data[2]["id"] == str(r1.id)

    # Check that items match ReportSummary schema
    for item in data:
        summary = ReportSummary(**item)
        assert summary.id is not None
        assert summary.shift_key is not None
        assert summary.version >= 1
        assert summary.model_used is not None
        assert summary.event_count >= 0
        assert summary.created_at is not None


def test_list_reports_excludes_full_content_fields(
    client: TestClient, db_session: Session
) -> None:
    """Verify GET /api/reports excludes summary, open_actions, and safety_notes from summaries."""
    now = datetime.now(timezone.utc)
    create_persisted_report(
        db_session,
        shift_key="2026-11-14-early",
        version=1,
        created_at=now,
        summary="Detailed secret summary",
        open_actions=[{"action": "Check gear", "owner": "Bob", "priority": "medium"}],
        safety_notes=["Crucial safety rule"],
    )

    response = client.get("/api/reports")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) == 1
    report_dict = data[0]

    # Content fields must be omitted
    assert "summary" not in report_dict
    assert "open_actions" not in report_dict
    assert "safety_notes" not in report_dict

    # Required summary fields must be present
    assert "id" in report_dict
    assert "shift_key" in report_dict
    assert "version" in report_dict
    assert "model_used" in report_dict
    assert "event_count" in report_dict
    assert "created_at" in report_dict


def test_list_reports_filter_by_shift_key_sorted_by_version_desc(
    client: TestClient, db_session: Session
) -> None:
    """Verify filter by shift_key returns only matching reports ordered by version descending."""
    base_time = datetime(2026, 11, 14, 8, 0, 0, tzinfo=timezone.utc)

    # Early shift: versions 1, 2, 3
    r_early_v1 = create_persisted_report(
        db_session,
        shift_key="2026-11-14-early",
        version=1,
        created_at=base_time,
    )
    r_early_v2 = create_persisted_report(
        db_session,
        shift_key="2026-11-14-early",
        version=2,
        created_at=base_time + timedelta(minutes=30),
    )
    r_early_v3 = create_persisted_report(
        db_session,
        shift_key="2026-11-14-early",
        version=3,
        created_at=base_time + timedelta(minutes=60),
    )

    # Late shift: versions 1, 2
    create_persisted_report(
        db_session,
        shift_key="2026-11-14-late",
        version=1,
        created_at=base_time + timedelta(hours=8),
    )

    response = client.get("/api/reports?shift_key=2026-11-14-early")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    assert len(data) == 3
    # Check that all belong to 2026-11-14-early
    assert all(d["shift_key"] == "2026-11-14-early" for d in data)
    # Check ordering by version desc (v3, v2, v1)
    assert [d["version"] for d in data] == [3, 2, 1]
    assert [d["id"] for d in data] == [str(r_early_v3.id), str(r_early_v2.id), str(r_early_v1.id)]


def test_list_reports_filter_shift_with_no_reports_returns_empty_list(
    client: TestClient, db_session: Session
) -> None:
    """Verify filtering for a shift with no reports returns HTTP 200 with []."""
    create_persisted_report(
        db_session,
        shift_key="2026-11-14-early",
        version=1,
        created_at=datetime.now(timezone.utc),
    )

    response = client.get("/api/reports?shift_key=2026-11-14-night")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == []


def test_list_reports_pagination_limit(
    client: TestClient, db_session: Session
) -> None:
    """Verify limit parameter caps returned results."""
    base_time = datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc)
    for v in range(1, 6):
        create_persisted_report(
            db_session,
            shift_key="2026-11-14-early",
            version=v,
            created_at=base_time + timedelta(minutes=v),
        )

    # Limit = 2
    res_limit_2 = client.get("/api/reports?shift_key=2026-11-14-early&limit=2")
    assert res_limit_2.status_code == status.HTTP_200_OK
    data_2 = res_limit_2.json()
    assert len(data_2) == 2
    assert [d["version"] for d in data_2] == [5, 4]

    # Limit = 1
    res_limit_1 = client.get("/api/reports?limit=1")
    assert res_limit_1.status_code == status.HTTP_200_OK
    data_1 = res_limit_1.json()
    assert len(data_1) == 1
    assert data_1[0]["version"] == 5

    # Default limit is 20 (returns all 5)
    res_default = client.get("/api/reports")
    assert res_default.status_code == status.HTTP_200_OK
    assert len(res_default.json()) == 5


@pytest.mark.parametrize(
    "invalid_limit",
    [0, -1, -5, 101, 200, "abc", "null"],
)
def test_list_reports_invalid_limit_returns_422_problem_details(
    client: TestClient, invalid_limit: object
) -> None:
    """Verify querying with invalid limit returns HTTP 422 with RFC 9457 ProblemDetails."""
    response = client.get(f"/api/reports?limit={invalid_limit}")
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "application/problem+json" in response.headers.get("content-type", "")

    problem = ProblemDetails(**response.json())
    assert problem.type == "about:blank"
    assert problem.title == "Unprocessable Entity"
    assert problem.status == 422
    assert "limit" in problem.detail.lower()


@pytest.mark.parametrize(
    "invalid_shift_key",
    [
        "2026-11-14",
        "2026-11-14-afternoon",
        "invalid-shift",
        "2026/11/14-early",
        "2026-1-1-early",
    ],
)
def test_list_reports_invalid_shift_key_returns_422_problem_details(
    client: TestClient, invalid_shift_key: str
) -> None:
    """Verify querying with malformed shift_key returns HTTP 422 with RFC 9457 ProblemDetails."""
    response = client.get(f"/api/reports?shift_key={invalid_shift_key}")
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "application/problem+json" in response.headers.get("content-type", "")

    problem = ProblemDetails(**response.json())
    assert problem.type == "about:blank"
    assert problem.title == "Unprocessable Entity"
    assert problem.status == 422
    assert "shift_key" in problem.detail.lower()


# ---------------------------------------------------------------------------
# GET /api/reports/{id} Tests (Detail, 404, 422)
# ---------------------------------------------------------------------------


def test_get_report_detail_success(
    client: TestClient, db_session: Session
) -> None:
    """Verify detail view for an existing report ID returns HTTP 200 with full ReportResponse."""
    now = datetime(2026, 11, 14, 14, 0, 0, tzinfo=timezone.utc)
    open_actions = [
        {"action": "Calibrate temperature sensor on CNC-1", "owner": "Shift Lead", "priority": "high"},
        {"action": "Restock PPE gloves at Station 4", "owner": "Operator", "priority": "low"},
    ]
    safety_notes = [
        "Oil leak near Press-2 marked with caution tape",
        "Emergency eyewash station inspected",
    ]

    report = create_persisted_report(
        db_session,
        shift_key="2026-11-14-early",
        version=1,
        created_at=now,
        summary="Shift completed safely with minor sensor drift on CNC-1.",
        open_actions=open_actions,
        safety_notes=safety_notes,
        model_used="gemini-3.5-flash-lite",
        event_count=8,
    )

    response = client.get(f"/api/reports/{report.id}")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    resp_obj = ReportResponse(**data)
    assert resp_obj.id == report.id
    assert resp_obj.shift_key == "2026-11-14-early"
    assert resp_obj.version == 1
    assert resp_obj.summary == "Shift completed safely with minor sensor drift on CNC-1."
    assert len(resp_obj.open_actions) == 2
    assert resp_obj.open_actions[0].action == "Calibrate temperature sensor on CNC-1"
    assert resp_obj.open_actions[0].owner == "Shift Lead"
    assert resp_obj.open_actions[0].priority == "high"
    assert resp_obj.open_actions[1].priority == "low"
    assert resp_obj.safety_notes == safety_notes
    assert resp_obj.model_used == "gemini-3.5-flash-lite"
    assert resp_obj.event_count == 8


def test_get_report_detail_not_found_returns_404_problem_details(
    client: TestClient,
) -> None:
    """Verify requesting non-existent report ID returns HTTP 404 with RFC 9457 ProblemDetails."""
    missing_id = uuid4()
    response = client.get(f"/api/reports/{missing_id}")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "application/problem+json" in response.headers.get("content-type", "")

    data = response.json()
    assert data["type"] == "about:blank"
    assert data["title"] == "Report Not Found"
    assert data["status"] == 404
    assert data["detail"] == f"Report with id '{missing_id}' not found"

    problem = ProblemDetails(**data)
    assert problem.title == "Report Not Found"
    assert problem.status == 404


def test_get_report_detail_malformed_uuid_returns_422_problem_details(
    client: TestClient,
) -> None:
    """Verify GET /api/reports/{id} with malformed non-UUID returns HTTP 422 ProblemDetails."""
    response = client.get("/api/reports/not-a-valid-uuid-12345")

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "application/problem+json" in response.headers.get("content-type", "")

    problem = ProblemDetails(**response.json())
    assert problem.type == "about:blank"
    assert problem.title == "Unprocessable Entity"
    assert problem.status == 422
    assert "uuid" in problem.detail.lower() or "id" in problem.detail.lower()


def test_trace_id_propagation_in_error_responses(
    client: TestClient,
) -> None:
    """Verify custom trace_id in request header is propagated in RFC 9457 ProblemDetails."""
    custom_trace_id = "trace-rep-hist-12345"
    headers = {"X-Trace-Id": custom_trace_id}

    # 404 Not Found
    res_404 = client.get(f"/api/reports/{uuid4()}", headers=headers)
    assert res_404.status_code == 404
    assert res_404.json()["trace_id"] == custom_trace_id

    # 422 Validation Error
    res_422 = client.get("/api/reports?limit=999", headers=headers)
    assert res_422.status_code == 422
    assert res_422.json()["trace_id"] == custom_trace_id


# ---------------------------------------------------------------------------
# Repository Dependency Injection Override Tests
# ---------------------------------------------------------------------------


def test_repository_dependency_injection_override() -> None:
    """Verify ReportRepository can be overridden via FastAPI dependency injection."""
    custom_repo = InMemoryReportRepository()
    test_app = create_app()
    test_app.dependency_overrides[get_report_repository] = lambda: custom_repo

    created_report = custom_repo.create(
        shift_key="2026-11-14-early",
        version=1,
        summary="In-memory test report summary",
        open_actions=[],
        safety_notes=["In-memory safety note"],
        model_used="gemini-3.5-flash-lite",
        event_count=2,
    )

    with TestClient(test_app) as custom_client:
        # 1. List
        list_res = custom_client.get("/api/reports?shift_key=2026-11-14-early")
        assert list_res.status_code == 200
        summaries = list_res.json()
        assert len(summaries) == 1
        assert summaries[0]["id"] == str(created_report.id)

        # 2. Detail
        detail_res = custom_client.get(f"/api/reports/{created_report.id}")
        assert detail_res.status_code == 200
        assert detail_res.json()["summary"] == "In-memory test report summary"

        # 3. 404 on missing ID
        missing_res = custom_client.get(f"/api/reports/{uuid4()}")
        assert missing_res.status_code == 404
        assert missing_res.json()["title"] == "Report Not Found"


# ---------------------------------------------------------------------------
# Direct Repository Unit Tests (InMemoryReportRepository & SqlReportRepository)
# ---------------------------------------------------------------------------


def test_in_memory_report_repository_list_and_get():
    """Unit test InMemoryReportRepository list_reports and get_by_id."""
    repo = InMemoryReportRepository()
    shift_early = "2026-11-14-early"
    shift_late = "2026-11-14-late"

    # Empty
    assert repo.list_reports() == []
    assert repo.get_by_id(uuid4()) is None

    # Create reports
    r1 = repo.create(
        shift_key=shift_early,
        version=1,
        summary="Early v1",
        open_actions=[],
        safety_notes=[],
        model_used="gemini-3.5-flash-lite",
        event_count=1,
    )
    r2 = repo.create(
        shift_key=shift_early,
        version=2,
        summary="Early v2",
        open_actions=[],
        safety_notes=[],
        model_used="gemini-3.5-flash-lite",
        event_count=2,
    )
    r3 = repo.create(
        shift_key=shift_late,
        version=1,
        summary="Late v1",
        open_actions=[],
        safety_notes=[],
        model_used="gemini-3.5-flash-lite",
        event_count=3,
    )

    # get_by_id (positional, id=, report_id=)
    assert repo.get_by_id(r1.id) is not None
    assert repo.get_by_id(id=r1.id).summary == "Early v1"
    assert repo.get_by_id(report_id=r2.id).summary == "Early v2"

    # Filtered by shift -> sorted by version desc
    early_reports = repo.list_reports(shift_key=shift_early)
    assert len(early_reports) == 2
    assert [r.version for r in early_reports] == [2, 1]

    # Unfiltered -> sorted by created_at desc
    all_reports = repo.list_reports()
    assert len(all_reports) == 3
    assert all_reports[0].id == r3.id

    # Limit
    assert len(repo.list_reports(limit=2)) == 2


def test_sql_report_repository_list_and_get(sql_repo: SqlReportRepository, db_session: Session):
    """Unit test SqlReportRepository list_reports and get_by_id."""
    shift_early = "2026-11-14-early"
    shift_late = "2026-11-14-late"

    # Empty
    assert sql_repo.list_reports() == []
    assert sql_repo.get_by_id(uuid4()) is None

    base_time = datetime(2026, 11, 14, 10, 0, 0, tzinfo=timezone.utc)
    r1 = create_persisted_report(db_session, shift_early, 1, base_time)
    r2 = create_persisted_report(db_session, shift_early, 2, base_time + timedelta(hours=1))
    r3 = create_persisted_report(db_session, shift_late, 1, base_time + timedelta(hours=2))

    # get_by_id
    assert sql_repo.get_by_id(r1.id) is not None
    assert sql_repo.get_by_id(id=r1.id).id == r1.id
    assert sql_repo.get_by_id(report_id=r2.id).version == 2

    # Filtered by shift -> version desc
    early_reports = sql_repo.list_reports(shift_key=shift_early)
    assert len(early_reports) == 2
    assert [r.version for r in early_reports] == [2, 1]

    # Unfiltered -> created_at desc
    all_reports = sql_repo.list_reports()
    assert len(all_reports) == 3
    assert all_reports[0].id == r3.id
    assert all_reports[1].id == r2.id
    assert all_reports[2].id == r1.id

    # Limit
    assert len(sql_repo.list_reports(limit=1)) == 1
    assert sql_repo.list_reports(limit=1)[0].id == r3.id
