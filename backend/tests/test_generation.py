"""Integration tests for shift handover report generation service and API endpoint.

Covers AC-3, AC-4, AC-5, AC-6, AC-7, AC-8, and Issue #6 acceptance criteria.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock
from uuid import UUID

from alembic import command
from alembic.config import Config
from fastapi import status
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.db.models import AppSetting, Event, Report
from app.db.reports_repo import (
    InMemoryReportRepository,
    SqlReportRepository,
    get_report_repository,
)
from app.db.session import create_db_engine, get_db
from app.llm.client import FakeLLMClient, LLMClient, get_llm_client
from app.llm.exceptions import LLMError, ModelNotFound
from app.main import create_app
from app.schemas.errors import ProblemDetails
from app.schemas.events import Category
from app.schemas.reports import OpenAction, ReportContent, ReportResponse
from app.services.handover import (
    HandoverService,
    get_handover_service,
    get_llm_client_dep,
)


@pytest.fixture
def test_db_path(tmp_path: Path) -> Path:
    """Provide a path for an isolated temporary SQLite database."""
    return tmp_path / "test_generation.db"


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
def migrated_db(alembic_config: Config, test_db_url: str):
    """Run alembic upgrade head on temporary test database, returning Engine."""
    command.upgrade(alembic_config, "head")
    engine = create_db_engine(test_db_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(migrated_db) -> Generator[Session, None, None]:
    """Provide a transactional database Session bound to the migrated database."""
    session_factory = sessionmaker(bind=migrated_db, autocommit=False, autoflush=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(migrated_db) -> Generator[TestClient, None, None]:
    """Provide a TestClient wired to the temporary migrated database."""
    test_app = create_app()
    session_factory = sessionmaker(bind=migrated_db, autocommit=False, autoflush=False)

    def override_get_db() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    test_app.dependency_overrides[get_db] = override_get_db
    with TestClient(test_app) as test_client:
        yield test_client
    test_app.dependency_overrides.clear()


def seed_event(
    db: Session,
    shift_key: str,
    machine: str = "Press-1",
    category: str = "downtime",
    note: str = "Machine malfunction observed",
) -> Event:
    """Helper to seed an event record into the database."""
    event = Event(
        shift_key=shift_key,
        machine=machine,
        category=category,
        note=note,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


# ---------------------------------------------------------------------------
# AC-6: 0 Events Validation Tests
# ---------------------------------------------------------------------------


def test_generate_report_zero_events_returns_422(
    client: TestClient, db_session: Session
) -> None:
    """AC-6: With 0 events, API returns HTTP 422 with RFC 9457 ProblemDetails and detail 'No events found for shift'."""
    shift_key = "2026-11-14-early"
    response = client.post("/api/reports/generate", json={"shift_key": shift_key})

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "application/problem+json" in response.headers.get("content-type", "")

    data = response.json()
    problem = ProblemDetails(**data)
    assert problem.status == 422
    assert problem.title == "Unprocessable Entity"
    assert problem.detail == "No events found for shift"

    # Verify zero reports were created in the database
    reports = db_session.scalars(select(Report).where(Report.shift_key == shift_key)).all()
    assert len(reports) == 0


def test_generate_report_invalid_shift_key_returns_422(client: TestClient) -> None:
    """Schema validation: Invalid shift_key returns HTTP 422 RFC 9457 ProblemDetails."""
    response = client.post("/api/reports/generate", json={"shift_key": "invalid-shift-format"})

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "application/problem+json" in response.headers.get("content-type", "")
    data = response.json()
    assert "shift_key" in data["detail"]


def test_generate_report_missing_shift_key_returns_422(client: TestClient) -> None:
    """Schema validation: Missing shift_key in body returns HTTP 422 RFC 9457 ProblemDetails."""
    response = client.post("/api/reports/generate", json={})

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "application/problem+json" in response.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# AC-3: Primary Model Success Tests
# ---------------------------------------------------------------------------


def test_generate_report_primary_model_success(
    client: TestClient, db_session: Session
) -> None:
    """AC-3: With >= 1 event, report generates successfully with 201, active model, and persists in DB."""
    shift_key = "2026-11-14-early"
    seed_event(
        db_session,
        shift_key=shift_key,
        machine="CNC-Mill-4",
        category="downtime",
        note="Spindle overheat detected; maintenance halted production.",
    )
    seed_event(
        db_session,
        shift_key=shift_key,
        machine="Conveyor-2",
        category="info",
        note="Shift handover briefing scheduled at end of turn.",
    )

    response = client.post("/api/reports/generate", json={"shift_key": shift_key})

    assert response.status_code == status.HTTP_201_CREATED
    assert "application/json" in response.headers.get("content-type", "")

    data = response.json()
    report_res = ReportResponse(**data)
    assert report_res.shift_key == shift_key
    assert report_res.version == 1
    assert report_res.model_used == "gemini-3.5-flash-lite"
    assert report_res.event_count == 2
    assert report_res.summary
    assert len(report_res.open_actions) >= 1
    assert isinstance(report_res.open_actions[0], OpenAction)
    assert report_res.created_at.tzinfo is not None

    # Verify report is persisted in database
    db_reports = db_session.scalars(
        select(Report).where(Report.shift_key == shift_key)
    ).all()
    assert len(db_reports) == 1
    persisted = db_reports[0]
    assert persisted.id == report_res.id
    assert persisted.version == 1
    assert persisted.model_used == "gemini-3.5-flash-lite"
    assert persisted.event_count == 2
    assert persisted.summary == report_res.summary


# ---------------------------------------------------------------------------
# AC-4: Safety Notes Representation Rule Tests
# ---------------------------------------------------------------------------


def test_generate_report_safety_notes_rule_represented(
    client: TestClient, db_session: Session
) -> None:
    """AC-4: Every safety event in shift events is represented in safety_notes."""
    shift_key = "2026-11-14-night"
    seed_event(
        db_session,
        shift_key=shift_key,
        machine="Robot-Cell-1",
        category="safety",
        note="Light curtain trip error during pallet entry.",
    )
    seed_event(
        db_session,
        shift_key=shift_key,
        machine="Forklift-B",
        category="safety",
        note="Emergency horn battery low, replaced with spare.",
    )
    seed_event(
        db_session,
        shift_key=shift_key,
        machine="Press-3",
        category="info",
        note="Routine oil replenishment completed.",
    )

    response = client.post("/api/reports/generate", json={"shift_key": shift_key})
    assert response.status_code == status.HTTP_201_CREATED

    report_res = ReportResponse(**response.json())
    assert len(report_res.safety_notes) >= 2
    # Check that safety events are represented
    safety_notes_joined = " ".join(report_res.safety_notes).lower()
    assert "light curtain" in safety_notes_joined
    assert "emergency horn" in safety_notes_joined


def test_generate_report_safety_notes_post_processing_coverage(
    client: TestClient, db_session: Session
) -> None:
    """AC-4: Service ensures safety event coverage even if LLM output omitted it."""
    shift_key = "2026-11-14-late"
    seed_event(
        db_session,
        shift_key=shift_key,
        machine="Laser-Cutter-9",
        category="safety",
        note="Protective enclosure interlock failed to latch.",
    )

    # Use a custom mock LLM that returns empty safety_notes
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.generate_handover.return_value = ReportContent(
        summary="Shift summary with omitted safety note.",
        open_actions=[
            OpenAction(
                action="Review log",
                owner="Shift lead",
                priority="low",
            )
        ],
        safety_notes=[],  # LLM omitted the safety event
    )

    app = client.app
    app.dependency_overrides[get_llm_client_dep] = lambda: mock_llm

    try:
        response = client.post("/api/reports/generate", json={"shift_key": shift_key})
        assert response.status_code == status.HTTP_201_CREATED
        report_res = ReportResponse(**response.json())

        # AC-4 safety guardrail must have injected the missing safety note
        assert len(report_res.safety_notes) == 1
        assert "Laser-Cutter-9" in report_res.safety_notes[0]
        assert "Protective enclosure interlock" in report_res.safety_notes[0]
    finally:
        app.dependency_overrides.pop(get_llm_client_dep, None)


# ---------------------------------------------------------------------------
# AC-5: Incremental Versioning Tests
# ---------------------------------------------------------------------------


def test_generate_report_version_incrementing(
    client: TestClient, db_session: Session
) -> None:
    """AC-5: Successive generations increment version sequentially (1, 2, 3) without mutating prior reports."""
    shift_key = "2026-11-14-early"
    seed_event(
        db_session,
        shift_key=shift_key,
        machine="Press-1",
        category="quality",
        note="Visual inspection detected burr on edge.",
    )

    # First generation -> version 1
    res1 = client.post("/api/reports/generate", json={"shift_key": shift_key})
    assert res1.status_code == status.HTTP_201_CREATED
    r1 = ReportResponse(**res1.json())
    assert r1.version == 1

    # Second generation -> version 2
    res2 = client.post("/api/reports/generate", json={"shift_key": shift_key})
    assert res2.status_code == status.HTTP_201_CREATED
    r2 = ReportResponse(**res2.json())
    assert r2.version == 2
    assert r2.id != r1.id

    # Third generation -> version 3
    res3 = client.post("/api/reports/generate", json={"shift_key": shift_key})
    assert res3.status_code == status.HTTP_201_CREATED
    r3 = ReportResponse(**res3.json())
    assert r3.version == 3
    assert r3.id != r2.id

    # Verify all 3 version snapshots remain intact in DB
    db_reports = db_session.scalars(
        select(Report)
        .where(Report.shift_key == shift_key)
        .order_by(Report.version.asc())
    ).all()
    assert len(db_reports) == 3
    assert [r.version for r in db_reports] == [1, 2, 3]


# ---------------------------------------------------------------------------
# AC-7: Automatic Fallback Retry Tests
# ---------------------------------------------------------------------------


def test_generate_report_fallback_on_model_not_found(
    client: TestClient, db_session: Session
) -> None:
    """AC-7: When active model is unavailable (ModelNotFound), retries fallback and records fallback model."""
    shift_key = "2026-11-14-early"
    seed_event(
        db_session,
        shift_key=shift_key,
        machine="Press-1",
        category="info",
        note="Standard operational handover.",
    )

    # Seed app_settings table with an unavailable/deprecated active model
    db_session.add(
        AppSetting(key="active_model", value="deprecated-gemini-2.0")
    )
    db_session.commit()

    response = client.post("/api/reports/generate", json={"shift_key": shift_key})
    assert response.status_code == status.HTTP_201_CREATED

    report_res = ReportResponse(**response.json())
    # Active model failed, fallback gemini-3.1-flash-lite succeeded
    assert report_res.model_used == "gemini-3.1-flash-lite"
    assert report_res.version == 1

    # Verify DB records fallback model
    saved = db_session.scalar(select(Report).where(Report.shift_key == shift_key))
    assert saved is not None
    assert saved.model_used == "gemini-3.1-flash-lite"


def test_generate_report_fallback_on_timeout_or_upstream_error(
    client: TestClient, db_session: Session
) -> None:
    """AC-7: When primary model raises LLMError/TimeoutError, retries fallback model successfully."""
    shift_key = "2026-11-14-night"
    seed_event(
        db_session,
        shift_key=shift_key,
        machine="Mill-1",
        category="downtime",
        note="Tool wear limit reached.",
    )

    mock_llm = MagicMock(spec=LLMClient)
    # First call (primary) raises LLMError, second call (fallback) returns valid ReportContent
    mock_llm.generate_handover.side_effect = [
        LLMError("Simulated 504 Gateway Timeout on primary model"),
        ReportContent(
            summary="Fallback generated summary.",
            open_actions=[
                OpenAction(
                    action="Replace tool head",
                    owner="Maintenance",
                    priority="high",
                )
            ],
            safety_notes=[],
        ),
    ]

    app = client.app
    app.dependency_overrides[get_llm_client_dep] = lambda: mock_llm

    try:
        response = client.post("/api/reports/generate", json={"shift_key": shift_key})
        assert response.status_code == status.HTTP_201_CREATED

        report_res = ReportResponse(**response.json())
        assert report_res.model_used == "gemini-3.1-flash-lite"
        assert report_res.summary == "Fallback generated summary."
        assert mock_llm.generate_handover.call_count == 2
    finally:
        app.dependency_overrides.pop(get_llm_client_dep, None)


# ---------------------------------------------------------------------------
# AC-8: Atomic Failure on Double Failure Tests
# ---------------------------------------------------------------------------


def test_generate_report_atomic_failure_on_double_failure(
    client: TestClient, db_session: Session
) -> None:
    """AC-8: If both active and fallback models fail, returns 502 with title 'Generation Failed' and 0 reports in DB."""
    shift_key = "2026-11-14-early"
    seed_event(
        db_session,
        shift_key=shift_key,
        machine="Press-1",
        category="downtime",
        note="Complete power loss on cell.",
    )

    # Seed app_settings table with invalid models for both active and fallback
    db_session.add_all([
        AppSetting(key="active_model", value="invalid-active-model"),
        AppSetting(key="fallback_model", value="invalid-fallback-model"),
    ])
    db_session.commit()

    response = client.post("/api/reports/generate", json={"shift_key": shift_key})

    assert response.status_code == status.HTTP_502_BAD_GATEWAY
    assert "application/problem+json" in response.headers.get("content-type", "")

    data = response.json()
    problem = ProblemDetails(**data)
    assert problem.status == 502
    assert problem.title == "Generation Failed"
    assert "Report generation failed" in problem.detail

    # Verify atomic failure guarantee: ZERO partial reports stored in database
    db_reports = db_session.scalars(
        select(Report).where(Report.shift_key == shift_key)
    ).all()
    assert len(db_reports) == 0


def test_generate_report_trace_id_propagation_on_502(
    client: TestClient, db_session: Session
) -> None:
    """AC-8 & AC-11: trace_id in request header is propagated in 502 ProblemDetails response."""
    shift_key = "2026-11-14-early"
    seed_event(
        db_session,
        shift_key=shift_key,
        machine="Press-1",
        category="info",
        note="Shift start.",
    )

    db_session.add_all([
        AppSetting(key="active_model", value="bad-model-1"),
        AppSetting(key="fallback_model", value="bad-model-2"),
    ])
    db_session.commit()

    custom_trace_id = "trace-uuid-abcdef-123456"
    response = client.post(
        "/api/reports/generate",
        json={"shift_key": shift_key},
        headers={"x-trace-id": custom_trace_id},
    )

    assert response.status_code == status.HTTP_502_BAD_GATEWAY
    data = response.json()
    assert data["trace_id"] == custom_trace_id


# ---------------------------------------------------------------------------
# Dynamic Model Settings & Version Race Tests
# ---------------------------------------------------------------------------


def test_dynamic_model_override_via_app_settings(
    client: TestClient, db_session: Session
) -> None:
    """Dynamic model configuration: Setting active_model in DB app_settings takes effect immediately."""
    shift_key = "2026-11-14-late"
    seed_event(
        db_session,
        shift_key=shift_key,
        machine="CNC-1",
        category="info",
        note="Shift logging.",
    )

    # Set active_model to another valid model in KNOWN_MODELS (gemini-3.5-flash)
    db_session.add(
        AppSetting(key="active_model", value="gemini-3.5-flash")
    )
    db_session.commit()

    response = client.post("/api/reports/generate", json={"shift_key": shift_key})
    assert response.status_code == status.HTTP_201_CREATED

    report_res = ReportResponse(**response.json())
    assert report_res.model_used == "gemini-3.5-flash"


def test_version_race_conflict_retries_once(
    db_session: Session,
) -> None:
    """AC-5: HandoverService handles unique constraint conflict on (shift_key, version) by retrying once."""
    shift_key = "2026-11-14-early"
    seed_event(db_session, shift_key=shift_key)

    report_repo = SqlReportRepository(db_session)
    # Create an initial report version 1
    report_repo.create(
        shift_key=shift_key,
        version=1,
        summary="Initial version 1 report.",
        open_actions=[],
        safety_notes=[],
        model_used="gemini-3.5-flash-lite",
        event_count=1,
    )

    service = HandoverService(
        event_repo=MagicMock(list_by_shift=lambda s: [seed_event(db_session, s)]),
        report_repo=report_repo,
        llm_client=FakeLLMClient(),
        db=db_session,
    )

    # Calling generate_report should detect version 1 exists and generate version 2
    res = service.generate_report(shift_key)
    assert res.version == 2


def test_generate_report_fallback_on_429_rate_limit(
    client: TestClient, db_session: Session
) -> None:
    """AC-7: When primary model encounters HTTP 429 rate limit, retries fallback model successfully."""
    shift_key = "2026-11-14-early"
    seed_event(
        db_session,
        shift_key=shift_key,
        machine="Oven-1",
        category="downtime",
        note="Burner controller alarm.",
    )

    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.generate_handover.side_effect = [
        LLMError("ResourceExhausted: 429 Quota exceeded for quota metric 'GenerateContent'"),
        ReportContent(
            summary="Fallback generated handover summary.",
            open_actions=[
                OpenAction(
                    action="Reset controller alarm",
                    owner="Maintenance",
                    priority="high",
                )
            ],
            safety_notes=[],
        ),
    ]

    app = client.app
    app.dependency_overrides[get_llm_client_dep] = lambda: mock_llm

    try:
        response = client.post("/api/reports/generate", json={"shift_key": shift_key})
        assert response.status_code == status.HTTP_201_CREATED
        report_res = ReportResponse(**response.json())
        assert report_res.model_used == "gemini-3.1-flash-lite"
        assert mock_llm.generate_handover.call_count == 2
    finally:
        app.dependency_overrides.pop(get_llm_client_dep, None)


def test_generate_report_fallback_on_schema_validation_failure(
    client: TestClient, db_session: Session
) -> None:
    """AC-7: When primary model produces unparseable/schema failure, retries fallback model."""
    shift_key = "2026-11-14-night"
    seed_event(
        db_session,
        shift_key=shift_key,
        machine="Conveyor-1",
        category="info",
        note="Line running smoothly.",
    )

    mock_llm = MagicMock(spec=LLMClient)
    # Primary returns a dict missing required summary field (causing validation failure)
    mock_llm.generate_handover.side_effect = [
        {"invalid": "schema"},
        ReportContent(
            summary="Fallback summary after schema validation failure.",
            open_actions=[],
            safety_notes=[],
        ),
    ]

    app = client.app
    app.dependency_overrides[get_llm_client_dep] = lambda: mock_llm

    try:
        response = client.post("/api/reports/generate", json={"shift_key": shift_key})
        assert response.status_code == status.HTTP_201_CREATED
        report_res = ReportResponse(**response.json())
        assert report_res.model_used == "gemini-3.1-flash-lite"
        assert report_res.summary == "Fallback summary after schema validation failure."
    finally:
        app.dependency_overrides.pop(get_llm_client_dep, None)


def test_version_race_retry_on_integrity_error() -> None:
    """AC-5: HandoverService retries once on IntegrityError race condition."""
    from sqlalchemy.exc import IntegrityError

    mock_event_repo = MagicMock()
    mock_event_repo.list_by_shift.return_value = [
        MagicMock(machine="M1", category="info", note="Shift event", created_at=datetime.now(timezone.utc))
    ]

    mock_report_repo = MagicMock()
    # First get_latest_version returns None (version 1)
    # Second get_latest_version (during retry) returns 1 (version 2)
    mock_report_repo.get_latest_version.side_effect = [None, 1]

    successful_response = ReportResponse(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        shift_key="2026-11-14-early",
        version=2,
        summary="Summary",
        open_actions=[],
        safety_notes=[],
        model_used="gemini-3.5-flash-lite",
        event_count=1,
        created_at=datetime.now(timezone.utc),
    )

    # First create call fails with IntegrityError (simulating race), second succeeds
    mock_report_repo.create.side_effect = [
        IntegrityError("UNIQUE constraint failed", params=None, orig=Exception()),
        successful_response,
    ]

    service = HandoverService(
        event_repo=mock_event_repo,
        report_repo=mock_report_repo,
        llm_client=FakeLLMClient(),
    )

    res = service.generate_report("2026-11-14-early")
    assert res.version == 2
    assert mock_report_repo.create.call_count == 2


def test_in_memory_report_repository_lifecycle() -> None:
    """Unit test InMemoryReportRepository methods and unique constraint enforcement."""
    repo = InMemoryReportRepository()
    shift_key = "2026-11-14-early"

    assert repo.get_latest_version(shift_key) is None
    assert repo.list_by_shift(shift_key) == []

    # Create version 1
    r1 = repo.create(
        shift_key=shift_key,
        version=1,
        summary="Version 1 summary",
        open_actions=[{"action": "Check pressure", "owner": "Operator", "priority": "medium"}],
        safety_notes=["Guard OK"],
        model_used="gemini-3.5-flash-lite",
        event_count=3,
    )
    assert r1.version == 1
    assert repo.get_latest_version(shift_key) == 1

    # Attempt duplicate (shift_key, version) raises IntegrityError
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        repo.create(
            shift_key=shift_key,
            version=1,
            summary="Duplicate",
            open_actions=[],
            safety_notes=[],
            model_used="gemini-3.5-flash-lite",
            event_count=1,
        )

    # Create version 2
    r2 = repo.create(
        shift_key=shift_key,
        version=2,
        summary="Version 2 summary",
        open_actions=[],
        safety_notes=[],
        model_used="gemini-3.5-flash-lite",
        event_count=4,
    )
    assert r2.version == 2
    assert repo.get_latest_version(shift_key) == 2

    # Listing by shift returns in descending version order
    reports = repo.list_by_shift(shift_key)
    assert len(reports) == 2
    assert [r.version for r in reports] == [2, 1]

    # Limit parameter works
    limited = repo.list_by_shift(shift_key, limit=1)
    assert len(limited) == 1
    assert limited[0].version == 2

    # Get by ID
    fetched = repo.get_by_id(r1.id)
    assert fetched is not None
    assert fetched.id == r1.id

    # Clear repository
    repo.clear()
    assert repo.get_latest_version(shift_key) is None
    assert repo.get_by_id(r1.id) is None


def test_sql_report_repository_methods(db_session: Session) -> None:
    """Unit test SqlReportRepository methods."""
    repo = SqlReportRepository(db_session)
    shift_key = "2026-11-14-late"

    assert repo.get_latest_version(shift_key) is None
    assert repo.list_by_shift(shift_key) == []

    # Create version 1
    r1 = repo.create(
        shift_key=shift_key,
        version=1,
        summary="SQL repo v1 summary",
        open_actions=[{"action": "Check valves", "owner": "Maintenance", "priority": "high"}],
        safety_notes=["[Safety] All guards active"],
        model_used="gemini-3.5-flash-lite",
        event_count=2,
    )
    assert r1.version == 1
    assert repo.get_latest_version(shift_key) == 1

    # Get by ID
    fetched = repo.get_by_id(r1.id)
    assert fetched is not None
    assert fetched.id == r1.id
    assert fetched.summary == "SQL repo v1 summary"

    # Create version 2
    r2 = repo.create(
        shift_key=shift_key,
        version=2,
        summary="SQL repo v2 summary",
        open_actions=[],
        safety_notes=[],
        model_used="gemini-3.1-flash-lite",
        event_count=3,
    )
    assert repo.get_latest_version(shift_key) == 2

    # List by shift descending
    reports = repo.list_by_shift(shift_key)
    assert len(reports) == 2
    assert [r.version for r in reports] == [2, 1]
