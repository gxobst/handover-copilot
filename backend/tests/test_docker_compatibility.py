"""Integration tests verifying frontend and backend naming and parameter compatibility in Docker (Issue #23).

Tests verify:
- GET /api/events accepts shiftKey and shift_key query parameters
- POST /api/events accepts camelCase shiftKey and snake_case shift_key request payloads
- Event responses expose both shiftKey and shift_key, createdAt and created_at
- DELETE /api/events/{id} returns 204
- POST /api/reports/generate accepts camelCase shiftKey and snake_case shift_key payloads
- GET /api/reports accepts camelCase shiftKey and snake_case shift_key query parameters
- GET /api/reports without query parameters returns summaries bounded by limit
- Report responses and summaries expose both camelCase and snake_case properties
- PUT /api/admin/settings accepts camelCase and snake_case payloads (single and both fields)
- GET /api/admin/settings returns settings
"""

from pathlib import Path
from typing import Generator
from uuid import UUID

from alembic import command
from alembic.config import Config
from fastapi import status
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import AppSetting, Event, Report
from app.db.session import create_db_engine, get_db
from app.main import create_app
from app.schemas.events import Category

DEFAULT_ADMIN_TOKEN = "dev-admin-secret-key-12345"
AUTH_HEADER = {"Authorization": f"Bearer {DEFAULT_ADMIN_TOKEN}"}


@pytest.fixture
def test_db_path(tmp_path: Path) -> Path:
    """Provide a path for an isolated temporary SQLite database."""
    return tmp_path / "test_docker_compat.db"


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


# ===========================================================================
# 1. Shift Events API Compatibility (/api/events)
# ===========================================================================


def test_events_create_and_list_with_camel_case(client: TestClient) -> None:
    """POST /api/events with camelCase shiftKey and GET /api/events?shiftKey=..."""
    shift_key = "2026-11-14-early"
    create_payload = {
        "shiftKey": shift_key,
        "machine": "Press-01",
        "category": "downtime",
        "note": "Hydraulic line pressure dropped",
    }
    create_res = client.post("/api/events", json=create_payload)
    assert create_res.status_code == status.HTTP_201_CREATED
    event_data = create_res.json()

    # Verify both camelCase and snake_case properties are present in response
    assert event_data["shiftKey"] == shift_key
    assert event_data["shift_key"] == shift_key
    assert "createdAt" in event_data
    assert "created_at" in event_data
    assert event_data["createdAt"] == event_data["created_at"]
    assert event_data["machine"] == "Press-01"
    assert event_data["category"] == "downtime"
    assert event_data["note"] == "Hydraulic line pressure dropped"
    event_id = event_data["id"]

    # GET with camelCase shiftKey query parameter
    list_res = client.get(f"/api/events?shiftKey={shift_key}")
    assert list_res.status_code == status.HTTP_200_OK
    events = list_res.json()
    assert len(events) >= 1
    matched = next((e for e in events if e["id"] == event_id), None)
    assert matched is not None
    assert matched["shiftKey"] == shift_key
    assert matched["shift_key"] == shift_key
    assert matched["createdAt"] == matched["created_at"]

    # DELETE /api/events/{id}
    del_res = client.delete(f"/api/events/{event_id}")
    assert del_res.status_code == status.HTTP_204_NO_CONTENT


def test_events_create_and_list_with_snake_case(client: TestClient) -> None:
    """POST /api/events with snake_case shift_key and GET /api/events?shift_key=..."""
    shift_key = "2026-11-14-late"
    create_payload = {
        "shift_key": shift_key,
        "machine": "Conveyor-B",
        "category": "safety",
        "note": "Emergency pull cord checked",
    }
    create_res = client.post("/api/events", json=create_payload)
    assert create_res.status_code == status.HTTP_201_CREATED
    event_data = create_res.json()
    assert event_data["shift_key"] == shift_key
    assert event_data["shiftKey"] == shift_key
    assert event_data["created_at"] == event_data["createdAt"]

    # GET with snake_case shift_key query parameter
    list_res = client.get(f"/api/events?shift_key={shift_key}")
    assert list_res.status_code == status.HTTP_200_OK
    events = list_res.json()
    assert len(events) >= 1
    assert any(e["id"] == event_data["id"] for e in events)


# ===========================================================================
# 2. Handover Reports API Compatibility (/api/reports)
# ===========================================================================


def test_reports_generate_with_camel_case_shift_key(client: TestClient) -> None:
    """POST /api/reports/generate accepts camelCase { shiftKey: ... }."""
    shift_key = "2026-11-14-early"
    # Seed an event
    client.post(
        "/api/events",
        json={
            "shiftKey": shift_key,
            "machine": "Press-01",
            "category": "info",
            "note": "Routine inspection complete",
        },
    )

    gen_res = client.post("/api/reports/generate", json={"shiftKey": shift_key})
    assert gen_res.status_code == status.HTTP_201_CREATED
    report = gen_res.json()

    # Verify both camelCase and snake_case properties
    assert report["shiftKey"] == shift_key
    assert report["shift_key"] == shift_key
    assert "modelUsed" in report
    assert "model_used" in report
    assert report["modelUsed"] == report["model_used"]
    assert "eventCount" in report
    assert "event_count" in report
    assert report["eventCount"] == report["event_count"]
    assert "createdAt" in report
    assert "created_at" in report
    assert "openActions" in report
    assert "open_actions" in report
    assert "safetyNotes" in report
    assert "safety_notes" in report
    assert isinstance(report["openActions"], list)
    assert isinstance(report["safetyNotes"], list)
    assert "summary" in report
    assert "version" in report
    assert "id" in report

    # Test GET /api/reports/{id}
    report_id = report["id"]
    get_res = client.get(f"/api/reports/{report_id}")
    assert get_res.status_code == status.HTTP_200_OK
    detail = get_res.json()
    assert detail["shiftKey"] == shift_key
    assert detail["shift_key"] == shift_key
    assert detail["modelUsed"] == detail["model_used"]
    assert detail["openActions"] == detail["open_actions"]


def test_reports_generate_with_snake_case_shift_key(client: TestClient) -> None:
    """POST /api/reports/generate accepts snake_case { shift_key: ... }."""
    shift_key = "2026-11-14-late"
    client.post(
        "/api/events",
        json={
            "shift_key": shift_key,
            "machine": "Line-3",
            "category": "quality",
            "note": "Tolerance verification within 0.02mm",
        },
    )

    gen_res = client.post("/api/reports/generate", json={"shift_key": shift_key})
    assert gen_res.status_code == status.HTTP_201_CREATED
    report = gen_res.json()
    assert report["shift_key"] == shift_key
    assert report["shiftKey"] == shift_key


def test_reports_list_with_query_params(client: TestClient) -> None:
    """GET /api/reports accepts shiftKey, shift_key, and no filter with limit."""
    shift_key = "2026-11-14-night"
    client.post(
        "/api/events",
        json={
            "shiftKey": shift_key,
            "machine": "Packer-1",
            "category": "info",
            "note": "Night shift started smoothly",
        },
    )
    client.post("/api/reports/generate", json={"shiftKey": shift_key})

    # Filter with camelCase shiftKey and limit
    res_camel = client.get(f"/api/reports?shiftKey={shift_key}&limit=10")
    assert res_camel.status_code == status.HTTP_200_OK
    summaries_camel = res_camel.json()
    assert len(summaries_camel) >= 1
    s = summaries_camel[0]
    assert s["shiftKey"] == shift_key
    assert s["shift_key"] == shift_key
    assert s["modelUsed"] == s["model_used"]
    assert s["eventCount"] == s["event_count"]
    assert s["createdAt"] == s["created_at"]
    assert "version" in s
    assert "id" in s

    # Filter with snake_case shift_key
    res_snake = client.get(f"/api/reports?shift_key={shift_key}")
    assert res_snake.status_code == status.HTTP_200_OK
    summaries_snake = res_snake.json()
    assert len(summaries_snake) >= 1

    # Unfiltered listing bounded by limit
    res_all = client.get("/api/reports?limit=5")
    assert res_all.status_code == status.HTTP_200_OK
    summaries_all = res_all.json()
    assert len(summaries_all) <= 5


# ===========================================================================
# 3. Admin Settings API Compatibility (/api/admin/settings)
# ===========================================================================


def test_admin_settings_get(client: TestClient) -> None:
    """GET /api/admin/settings returns active and fallback models."""
    res = client.get("/api/admin/settings", headers=AUTH_HEADER)
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert "active_model" in data
    assert "activeModel" in data
    assert "fallback_model" in data
    assert "fallbackModel" in data
    assert data["activeModel"] == data["active_model"]
    assert data["fallbackModel"] == data["fallback_model"]


def test_admin_settings_put_camel_case(client: TestClient) -> None:
    """PUT /api/admin/settings accepts camelCase activeModel and fallbackModel."""
    # Update activeModel only
    res1 = client.put(
        "/api/admin/settings",
        headers=AUTH_HEADER,
        json={"activeModel": "gemini-test-active"},
    )
    assert res1.status_code == status.HTTP_200_OK
    data1 = res1.json()
    assert "active_model" in data1
    assert "activeModel" in data1
    assert "fallback_model" in data1
    assert "fallbackModel" in data1
    assert data1["active_model"] == "gemini-test-active"
    assert data1["activeModel"] == "gemini-test-active"

    # Update fallbackModel only
    res2 = client.put(
        "/api/admin/settings",
        headers=AUTH_HEADER,
        json={"fallbackModel": "gemini-test-fallback"},
    )
    assert res2.status_code == status.HTTP_200_OK
    data2 = res2.json()
    assert "active_model" in data2
    assert "activeModel" in data2
    assert "fallback_model" in data2
    assert "fallbackModel" in data2
    assert data2["fallback_model"] == "gemini-test-fallback"
    assert data2["fallbackModel"] == "gemini-test-fallback"

    # Update both simultaneously with camelCase
    res3 = client.put(
        "/api/admin/settings",
        headers=AUTH_HEADER,
        json={
            "activeModel": "gemini-dual-active",
            "fallbackModel": "gemini-dual-fallback",
        },
    )
    assert res3.status_code == status.HTTP_200_OK
    data3 = res3.json()
    assert "active_model" in data3
    assert "activeModel" in data3
    assert "fallback_model" in data3
    assert "fallbackModel" in data3
    assert data3["active_model"] == "gemini-dual-active"
    assert data3["activeModel"] == "gemini-dual-active"
    assert data3["fallback_model"] == "gemini-dual-fallback"
    assert data3["fallbackModel"] == "gemini-dual-fallback"


def test_admin_settings_put_snake_case(client: TestClient) -> None:
    """PUT /api/admin/settings accepts snake_case active_model and fallback_model."""
    # Update active_model only
    res1 = client.put(
        "/api/admin/settings",
        headers=AUTH_HEADER,
        json={"active_model": "gemini-snake-active"},
    )
    assert res1.status_code == status.HTTP_200_OK
    data1 = res1.json()
    assert "active_model" in data1
    assert "activeModel" in data1
    assert "fallback_model" in data1
    assert "fallbackModel" in data1
    assert data1["active_model"] == "gemini-snake-active"
    assert data1["activeModel"] == "gemini-snake-active"

    # Update fallback_model only
    res2 = client.put(
        "/api/admin/settings",
        headers=AUTH_HEADER,
        json={"fallback_model": "gemini-snake-fallback"},
    )
    assert res2.status_code == status.HTTP_200_OK
    data2 = res2.json()
    assert "active_model" in data2
    assert "activeModel" in data2
    assert "fallback_model" in data2
    assert "fallbackModel" in data2
    assert data2["fallback_model"] == "gemini-snake-fallback"
    assert data2["fallbackModel"] == "gemini-snake-fallback"

    # Update both simultaneously
    res3 = client.put(
        "/api/admin/settings",
        headers=AUTH_HEADER,
        json={
            "active_model": "gemini-both-active",
            "fallback_model": "gemini-both-fallback",
        },
    )
    assert res3.status_code == status.HTTP_200_OK
    data3 = res3.json()
    assert "active_model" in data3
    assert "activeModel" in data3
    assert "fallback_model" in data3
    assert "fallbackModel" in data3
    assert data3["active_model"] == "gemini-both-active"
    assert data3["activeModel"] == "gemini-both-active"
    assert data3["fallback_model"] == "gemini-both-fallback"
    assert data3["fallbackModel"] == "gemini-both-fallback"
