"""Integration tests for database persistence, Alembic migrations, and repository layer."""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Generator
import uuid

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.db.models import AppSetting, Base, Event, Report
from app.db.repo import SqlEventRepository, get_event_repository
from app.db.session import create_db_engine, get_db
from app.main import create_app
from app.schemas.events import Category, EventCreate


@pytest.fixture
def test_db_path(tmp_path: Path) -> Path:
    """Provide a path for a temporary SQLite database."""
    return tmp_path / "test_handover.db"


@pytest.fixture
def test_db_url(test_db_path: Path) -> str:
    """Provide a SQLite URL for a temporary database."""
    return f"sqlite:///{test_db_path.as_posix()}"


@pytest.fixture
def alembic_config(test_db_url: str) -> Config:
    """Provide an Alembic Config pointing to the temporary test database."""
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
def sql_repo(db_session: Session) -> SqlEventRepository:
    """Provide a SqlEventRepository instance using the test session."""
    return SqlEventRepository(db_session)


# ---------------------------------------------------------------------------
# Alembic Migration & Schema Tests
# ---------------------------------------------------------------------------


def test_alembic_upgrade_and_downgrade(alembic_config: Config, test_db_url: str) -> None:
    """Verify Alembic upgrade head creates all 3 tables & indexes, and downgrade base removes them."""
    command.upgrade(alembic_config, "head")
    engine = create_db_engine(test_db_url)
    inspector = inspect(engine)

    # 1. Verify tables exist
    tables = inspector.get_table_names()
    assert "events" in tables
    assert "reports" in tables
    assert "app_settings" in tables

    # 2. Verify idx_events_shift on (shift_key, created_at)
    indexes = inspector.get_indexes("events")
    idx_names = [idx["name"] for idx in indexes]
    assert "idx_events_shift" in idx_names
    shift_idx = next(idx for idx in indexes if idx["name"] == "idx_events_shift")
    assert shift_idx["column_names"] == ["shift_key", "created_at"]

    # 3. Verify downgrade base drops tables
    engine.dispose()
    command.downgrade(alembic_config, "base")

    engine2 = create_db_engine(test_db_url)
    inspector2 = inspect(engine2)
    tables_after = inspector2.get_table_names()
    assert "events" not in tables_after
    assert "reports" not in tables_after
    assert "app_settings" not in tables_after
    engine2.dispose()


# ---------------------------------------------------------------------------
# SqlEventRepository CRUD Tests
# ---------------------------------------------------------------------------


def test_sql_event_repo_crud_lifecycle(sql_repo: SqlEventRepository) -> None:
    """Verify create, get_by_id, list_by_shift, and delete operations via SqlEventRepository."""
    # 1. Create
    event_in = EventCreate(
        shift_key="2026-11-14-early",
        machine="Press-1",
        category=Category.DOWNTIME,
        note="Hydraulic cylinder seal replaced during early shift.",
    )
    created = sql_repo.create(event_in)
    assert created.id is not None
    assert created.shift_key == "2026-11-14-early"
    assert created.machine == "Press-1"
    assert created.category == Category.DOWNTIME
    assert created.note == "Hydraulic cylinder seal replaced during early shift."
    assert created.created_at.tzinfo is not None

    # 2. Get by ID
    fetched = sql_repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.shift_key == created.shift_key
    assert fetched.machine == created.machine
    assert fetched.category == created.category
    assert fetched.note == created.note
    assert fetched.created_at == created.created_at

    # Get non-existent
    assert sql_repo.get_by_id(uuid.uuid4()) is None

    # 3. List by shift
    event_in_2 = EventCreate(
        shift_key="2026-11-14-early",
        machine="CNC-2",
        category=Category.QUALITY,
        note="Calibration check completed within tolerances.",
    )
    event_in_other_shift = EventCreate(
        shift_key="2026-11-14-late",
        machine="Press-1",
        category=Category.INFO,
        note="Shift handover briefing conducted.",
    )
    created_2 = sql_repo.create(event_in_2)
    sql_repo.create(event_in_other_shift)

    early_events = sql_repo.list_by_shift("2026-11-14-early")
    assert len(early_events) == 2
    assert [e.id for e in early_events] == [created.id, created_2.id]
    # Ensure chronological order
    assert early_events[0].created_at <= early_events[1].created_at

    # Empty list for shift with no events
    assert sql_repo.list_by_shift("2026-11-14-night") == []

    # 4. Delete
    deleted = sql_repo.delete(created.id)
    assert deleted is True
    assert sql_repo.get_by_id(created.id) is None
    assert len(sql_repo.list_by_shift("2026-11-14-early")) == 1

    # Delete non-existent ID
    assert sql_repo.delete(created.id) is False
    assert sql_repo.delete(uuid.uuid4()) is False


# ---------------------------------------------------------------------------
# Restart Survival Test (AC-1)
# ---------------------------------------------------------------------------


def test_event_persistence_across_engine_restart(
    test_db_url: str,
    migrated_db,
) -> None:
    """AC-1: Verify that events committed in one engine/session persist and can be re-read after a restart."""
    session_maker_1 = sessionmaker(bind=migrated_db, autocommit=False, autoflush=False)
    with session_maker_1() as session1:
        repo1 = SqlEventRepository(session1)
        event_in = EventCreate(
            shift_key="2026-11-14-night",
            machine="Laser-Weld-3",
            category=Category.SAFETY,
            note="Safety guard interlock sensor inspected and tested OK.",
        )
        created_event = repo1.create(event_in)
        event_id = created_event.id

    # Simulate application restart: dispose original engine and close sessions
    migrated_db.dispose()

    # Re-open database with a completely fresh engine and session
    fresh_engine = create_db_engine(test_db_url)
    session_maker_2 = sessionmaker(bind=fresh_engine, autocommit=False, autoflush=False)
    try:
        with session_maker_2() as session2:
            repo2 = SqlEventRepository(session2)
            persisted = repo2.get_by_id(event_id)

            assert persisted is not None
            assert persisted.id == event_id
            assert persisted.shift_key == "2026-11-14-night"
            assert persisted.machine == "Laser-Weld-3"
            assert persisted.category == Category.SAFETY
            assert persisted.note == "Safety guard interlock sensor inspected and tested OK."
            assert persisted.created_at.tzinfo is not None
    finally:
        fresh_engine.dispose()


# ---------------------------------------------------------------------------
# Database Constraints Tests
# ---------------------------------------------------------------------------


def test_event_check_constraint_invalid_category(db_session: Session) -> None:
    """Verify that inserting an event with an invalid category fails check constraint."""
    invalid_event = Event(
        shift_key="2026-11-14-early",
        machine="Press-1",
        category="critical_failure",  # Not in ('downtime', 'quality', 'safety', 'info')
        note="Valid note content.",
    )
    db_session.add(invalid_event)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_event_check_constraint_note_length(db_session: Session) -> None:
    """Verify that note length boundary constraints (1 <= length <= 2000) are enforced."""
    # 1. Empty note (length 0) should fail
    empty_note_event = Event(
        shift_key="2026-11-14-early",
        machine="Press-1",
        category="info",
        note="",
    )
    db_session.add(empty_note_event)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # 2. Note exceeding 2000 characters should fail
    excessive_note_event = Event(
        shift_key="2026-11-14-early",
        machine="Press-1",
        category="info",
        note="x" * 2001,
    )
    db_session.add(excessive_note_event)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # 3. Boundary values 1 and 2000 characters should succeed
    bound_min = Event(
        shift_key="2026-11-14-early",
        machine="Press-1",
        category="info",
        note="x",
    )
    bound_max = Event(
        shift_key="2026-11-14-early",
        machine="Press-1",
        category="info",
        note="y" * 2000,
    )
    db_session.add_all([bound_min, bound_max])
    db_session.commit()
    assert bound_min.id is not None
    assert bound_max.id is not None


def test_report_unique_constraint_shift_key_and_version(db_session: Session) -> None:
    """Verify unique constraint on (shift_key, version) prevents duplicate reports."""
    report1 = Report(
        shift_key="2026-11-14-early",
        version=1,
        summary="Initial early shift report summary.",
        open_actions=[{"action": "Check lubrication levels"}],
        safety_notes=[{"note": "No incidents reported"}],
        model_used="gemini-3.5-flash-lite",
        event_count=5,
    )
    db_session.add(report1)
    db_session.commit()

    # Duplicate (shift_key, version)
    duplicate_report = Report(
        shift_key="2026-11-14-early",
        version=1,
        summary="Conflicting report with same shift and version.",
        open_actions=[],
        safety_notes=[],
        model_used="gemini-3.1-flash-lite",
        event_count=5,
    )
    db_session.add(duplicate_report)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Different version on same shift should succeed
    report_v2 = Report(
        shift_key="2026-11-14-early",
        version=2,
        summary="Second revision for early shift.",
        open_actions=[],
        safety_notes=[],
        model_used="gemini-3.5-flash-lite",
        event_count=6,
    )
    # Same version on different shift should succeed
    report_late_v1 = Report(
        shift_key="2026-11-14-late",
        version=1,
        summary="Late shift version 1 report.",
        open_actions=[],
        safety_notes=[],
        model_used="gemini-3.5-flash-lite",
        event_count=3,
    )
    db_session.add_all([report_v2, report_late_v1])
    db_session.commit()
    assert report_v2.id is not None
    assert report_late_v1.id is not None


# ---------------------------------------------------------------------------
# AppSetting Read / Write Tests
# ---------------------------------------------------------------------------


def test_app_setting_persistence(db_session: Session) -> None:
    """Verify AppSetting key-value persistence, retrieval, and update."""
    setting = AppSetting(
        key="active_model",
        value="gemini-3.5-flash-lite",
    )
    db_session.add(setting)
    db_session.commit()

    # Read back
    retrieved = db_session.get(AppSetting, "active_model")
    assert retrieved is not None
    assert retrieved.key == "active_model"
    assert retrieved.value == "gemini-3.5-flash-lite"
    assert retrieved.updated_at.tzinfo is not None

    # Update
    retrieved.value = "gemini-1.5-pro"
    db_session.commit()

    updated = db_session.get(AppSetting, "active_model")
    assert updated is not None
    assert updated.value == "gemini-1.5-pro"


# ---------------------------------------------------------------------------
# FastAPI Router End-to-End Integration with SqlEventRepository
# ---------------------------------------------------------------------------


def test_api_events_with_sql_repository(
    db_session: Session,
) -> None:
    """Verify FastAPI event endpoints inject and operate against SqlEventRepository and a real DB."""
    test_app = create_app()
    # Override get_db to return our transactional test db_session
    test_app.dependency_overrides[get_db] = lambda: db_session

    with TestClient(test_app) as client:
        # 1. POST /api/events creates an event via SqlEventRepository
        post_res = client.post(
            "/api/events",
            json={
                "shift_key": "2026-11-14-early",
                "machine": "Robot-Arm-1",
                "category": "downtime",
                "note": "Gripper pneumatic pressure loss detected.",
            },
        )
        assert post_res.status_code == 201
        data = post_res.json()
        event_id = data["id"]
        assert data["shift_key"] == "2026-11-14-early"
        assert data["machine"] == "Robot-Arm-1"

        # 2. GET /api/events?shift_key=... lists persisted event
        list_res = client.get("/api/events?shift_key=2026-11-14-early")
        assert list_res.status_code == 200
        events_list = list_res.json()
        assert len(events_list) == 1
        assert events_list[0]["id"] == event_id

        # 3. DELETE /api/events/{id} removes it
        del_res = client.delete(f"/api/events/{event_id}")
        assert del_res.status_code == 204

        # 4. Verify removal
        list_after = client.get("/api/events?shift_key=2026-11-14-early")
        assert list_after.status_code == 200
        assert len(list_after.json()) == 0

    test_app.dependency_overrides.clear()
