"""Integration tests for Event CRUD API endpoints and in-memory repository."""

from datetime import datetime, timezone
import time
from typing import Generator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.events_repo import (
    EventRepository,
    InMemoryEventRepository,
    get_event_repository,
)
from app.main import app, create_app
from app.schemas.errors import ProblemDetails
from app.schemas.events import Category, EventCreate, EventResponse


@pytest.fixture
def repo() -> InMemoryEventRepository:
    """Provide a fresh isolated InMemoryEventRepository for each test."""
    return InMemoryEventRepository()


@pytest.fixture
def client(repo: InMemoryEventRepository) -> Generator[TestClient, None, None]:
    """Provide a TestClient with dependency override using isolated repo."""
    test_app = create_app()
    test_app.dependency_overrides[get_event_repository] = lambda: repo
    with TestClient(test_app) as test_client:
        yield test_client
    test_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/events Tests
# ---------------------------------------------------------------------------


def test_create_event_success(client: TestClient) -> None:
    """AC-1 & Issue #3: POST /api/events creates an event with 201 status and valid EventResponse."""
    payload = {
        "shift_key": "2026-11-14-early",
        "machine": "Press-1",
        "category": "downtime",
        "note": "Hydraulic oil leak on main cylinder. Maintenance called.",
    }
    before_create = datetime.now(timezone.utc)
    response = client.post("/api/events", json=payload)
    after_create = datetime.now(timezone.utc)

    assert response.status_code == 201
    assert "application/json" in response.headers.get("content-type", "")

    data = response.json()
    assert UUID(data["id"])  # Valid UUID
    assert data["shift_key"] == payload["shift_key"]
    assert data["machine"] == payload["machine"]
    assert data["category"] == payload["category"]
    assert data["note"] == payload["note"]

    # Verify UTC timestamp
    created_at = datetime.fromisoformat(data["created_at"])
    assert created_at.tzinfo is not None
    assert before_create <= created_at <= after_create


@pytest.mark.parametrize("category", ["downtime", "quality", "safety", "info"])
def test_create_event_all_valid_categories(client: TestClient, category: str) -> None:
    """Verify POST /api/events accepts all four valid domain categories."""
    payload = {
        "shift_key": "2026-11-14-late",
        "machine": "CNC-4",
        "category": category,
        "note": f"Logging event for {category}",
    }
    response = client.post("/api/events", json=payload)
    assert response.status_code == 201
    assert response.json()["category"] == category


def test_create_event_boundary_note_lengths(client: TestClient) -> None:
    """Verify POST /api/events accepts 1-character and 2000-character notes."""
    # Min length boundary: 1 character
    res_min = client.post(
        "/api/events",
        json={
            "shift_key": "2026-11-14-early",
            "machine": "Oven-1",
            "category": "info",
            "note": "A",
        },
    )
    assert res_min.status_code == 201
    assert res_min.json()["note"] == "A"

    # Max length boundary: 2000 characters
    long_note = "X" * 2000
    res_max = client.post(
        "/api/events",
        json={
            "shift_key": "2026-11-14-early",
            "machine": "Oven-1",
            "category": "info",
            "note": long_note,
        },
    )
    assert res_max.status_code == 201
    assert res_max.json()["note"] == long_note


@pytest.mark.parametrize(
    "invalid_payload,expected_loc_part",
    [
        (
            {
                "shift_key": "2026-11-14-morning",
                "machine": "Press-1",
                "category": "downtime",
                "note": "Bad shift key",
            },
            "shift_key",
        ),
        (
            {
                "shift_key": "14-11-2026-early",
                "machine": "Press-1",
                "category": "downtime",
                "note": "Bad date format",
            },
            "shift_key",
        ),
        (
            {
                "machine": "Press-1",
                "category": "downtime",
                "note": "Missing shift_key",
            },
            "shift_key",
        ),
        (
            {
                "shift_key": "2026-11-14-early",
                "machine": "",
                "category": "downtime",
                "note": "Empty machine",
            },
            "machine",
        ),
        (
            {
                "shift_key": "2026-11-14-early",
                "machine": "   ",
                "category": "downtime",
                "note": "Whitespace machine",
            },
            "machine",
        ),
        (
            {
                "shift_key": "2026-11-14-early",
                "category": "downtime",
                "note": "Missing machine",
            },
            "machine",
        ),
        (
            {
                "shift_key": "2026-11-14-early",
                "machine": "Press-1",
                "category": "maintenance",
                "note": "Invalid category",
            },
            "category",
        ),
        (
            {
                "shift_key": "2026-11-14-early",
                "machine": "Press-1",
                "category": "downtime",
                "note": "",
            },
            "note",
        ),
        (
            {
                "shift_key": "2026-11-14-early",
                "machine": "Press-1",
                "category": "downtime",
                "note": "Y" * 2001,
            },
            "note",
        ),
        (
            {
                "shift_key": "2026-11-14-early",
                "machine": "Press-1",
                "category": "downtime",
            },
            "note",
        ),
    ],
)
def test_create_event_validation_errors(
    client: TestClient, invalid_payload: dict, expected_loc_part: str
) -> None:
    """Verify invalid payloads return 422 with RFC 9457 ProblemDetails and application/problem+json."""
    response = client.post("/api/events", json=invalid_payload)

    assert response.status_code == 422
    assert "application/problem+json" in response.headers.get("content-type", "")

    problem = ProblemDetails(**response.json())
    assert problem.type == "about:blank"
    assert problem.title == "Unprocessable Entity"
    assert problem.status == 422
    assert expected_loc_part in problem.detail


# ---------------------------------------------------------------------------
# GET /api/events Tests
# ---------------------------------------------------------------------------


def test_list_events_empty(client: TestClient) -> None:
    """Verify GET /api/events returns HTTP 200 with empty list [] when no events exist."""
    response = client.get("/api/events?shift_key=2026-11-14-night")
    assert response.status_code == 200
    assert response.json() == []


def test_list_events_chronological_order(client: TestClient) -> None:
    """Verify GET /api/events returns events ordered chronologically ascending by created_at."""
    shift = "2026-11-14-early"

    # Create 3 events with slight sleep to guarantee distinct timestamps
    created_ids = []
    for i in range(3):
        res = client.post(
            "/api/events",
            json={
                "shift_key": shift,
                "machine": f"Machine-{i+1}",
                "category": "info",
                "note": f"Sequential event {i+1}",
            },
        )
        assert res.status_code == 201
        created_ids.append(res.json()["id"])
        time.sleep(0.01)

    response = client.get(f"/api/events?shift_key={shift}")
    assert response.status_code == 200
    events = response.json()
    assert len(events) == 3

    # Verify chronological ascending order
    timestamps = [datetime.fromisoformat(e["created_at"]) for e in events]
    assert timestamps == sorted(timestamps)
    assert [e["id"] for e in events] == created_ids


def test_list_events_shift_isolation(client: TestClient) -> None:
    """Verify shift isolation: events for shift A do not appear in shift B."""
    shift_a = "2026-11-14-early"
    shift_b = "2026-11-14-late"
    shift_c = "2026-11-14-night"

    # Add 2 events to shift A
    client.post(
        "/api/events",
        json={
            "shift_key": shift_a,
            "machine": "Line-1",
            "category": "downtime",
            "note": "Shift A event 1",
        },
    )
    client.post(
        "/api/events",
        json={
            "shift_key": shift_a,
            "machine": "Line-1",
            "category": "quality",
            "note": "Shift A event 2",
        },
    )

    # Add 1 event to shift B
    client.post(
        "/api/events",
        json={
            "shift_key": shift_b,
            "machine": "Line-2",
            "category": "safety",
            "note": "Shift B event 1",
        },
    )

    # Fetch shift A
    res_a = client.get(f"/api/events?shift_key={shift_a}")
    assert res_a.status_code == 200
    events_a = res_a.json()
    assert len(events_a) == 2
    assert all(e["shift_key"] == shift_a for e in events_a)

    # Fetch shift B
    res_b = client.get(f"/api/events?shift_key={shift_b}")
    assert res_b.status_code == 200
    events_b = res_b.json()
    assert len(events_b) == 1
    assert events_b[0]["shift_key"] == shift_b

    # Fetch shift C (should be empty)
    res_c = client.get(f"/api/events?shift_key={shift_c}")
    assert res_c.status_code == 200
    assert res_c.json() == []


def test_list_events_missing_shift_key_returns_422_problem_details(
    client: TestClient,
) -> None:
    """Verify GET /api/events without shift_key returns 422 RFC 9457 ProblemDetails."""
    response = client.get("/api/events")
    assert response.status_code == 422
    assert "application/problem+json" in response.headers.get("content-type", "")

    problem = ProblemDetails(**response.json())
    assert problem.type == "about:blank"
    assert problem.title == "Unprocessable Entity"
    assert problem.status == 422
    assert "shift_key" in problem.detail


@pytest.mark.parametrize(
    "invalid_key",
    [
        "2026-11-14-morning",
        "2026-11-14",
        "14-11-2026-early",
        "invalid-shift-key",
        "",
    ],
)
def test_list_events_invalid_shift_key_returns_422_problem_details(
    client: TestClient, invalid_key: str
) -> None:
    """Verify GET /api/events with invalid shift_key format returns 422 ProblemDetails."""
    response = client.get(f"/api/events?shift_key={invalid_key}")
    assert response.status_code == 422
    assert "application/problem+json" in response.headers.get("content-type", "")

    problem = ProblemDetails(**response.json())
    assert problem.type == "about:blank"
    assert problem.title == "Unprocessable Entity"
    assert problem.status == 422
    assert "shift_key" in problem.detail


# ---------------------------------------------------------------------------
# DELETE /api/events/{id} Tests
# ---------------------------------------------------------------------------


def test_delete_event_success_and_permanent_removal(client: TestClient) -> None:
    """AC-2 & Issue #3: DELETE /api/events/{id} permanently removes the event and returns 204."""
    shift = "2026-11-14-early"

    # Create an event
    create_res = client.post(
        "/api/events",
        json={
            "shift_key": shift,
            "machine": "Press-2",
            "category": "downtime",
            "note": "Conveyor jam",
        },
    )
    assert create_res.status_code == 201
    event_id = create_res.json()["id"]

    # Verify event appears in list
    list_res_before = client.get(f"/api/events?shift_key={shift}")
    assert len(list_res_before.json()) == 1

    # Delete event: HTTP 204 No Content with empty body
    delete_res = client.delete(f"/api/events/{event_id}")
    assert delete_res.status_code == 204
    assert delete_res.content == b""

    # Verify subsequent GET excludes the deleted event
    list_res_after = client.get(f"/api/events?shift_key={shift}")
    assert list_res_after.status_code == 200
    assert list_res_after.json() == []

    # Repeated DELETE returns HTTP 404
    repeated_delete = client.delete(f"/api/events/{event_id}")
    assert repeated_delete.status_code == 404
    assert "application/problem+json" in repeated_delete.headers.get("content-type", "")
    problem = ProblemDetails(**repeated_delete.json())
    assert problem.type == "about:blank"
    assert problem.title == "Not Found"
    assert problem.status == 404
    assert event_id in problem.detail


def test_delete_non_existent_event_returns_404_problem_details(
    client: TestClient,
) -> None:
    """Verify deleting a non-existent UUID returns HTTP 404 RFC 9457 ProblemDetails."""
    non_existent_id = uuid4()
    response = client.delete(f"/api/events/{non_existent_id}")

    assert response.status_code == 404
    assert "application/problem+json" in response.headers.get("content-type", "")

    problem = ProblemDetails(**response.json())
    assert problem.type == "about:blank"
    assert problem.title == "Not Found"
    assert problem.status == 404
    assert str(non_existent_id) in problem.detail


def test_delete_invalid_uuid_returns_422_problem_details(client: TestClient) -> None:
    """Verify DELETE with malformed non-UUID path parameter returns HTTP 422 ProblemDetails."""
    response = client.delete("/api/events/not-a-valid-uuid")

    assert response.status_code == 422
    assert "application/problem+json" in response.headers.get("content-type", "")

    problem = ProblemDetails(**response.json())
    assert problem.type == "about:blank"
    assert problem.title == "Unprocessable Entity"
    assert problem.status == 422
    assert "id" in problem.detail


# ---------------------------------------------------------------------------
# Decoupling & Trace ID Tests
# ---------------------------------------------------------------------------


def test_trace_id_propagation_in_problem_details(client: TestClient) -> None:
    """Verify trace_id is extracted from request headers into ProblemDetails."""
    trace_id_val = "4bf92f3577b34da6a3ce929d0e0e4736"
    headers = {"x-trace-id": trace_id_val}

    # Request validation error with trace header
    res_val = client.get("/api/events", headers=headers)
    assert res_val.status_code == 422
    assert res_val.json()["trace_id"] == trace_id_val

    # HTTP 404 error with trace header
    res_404 = client.delete(f"/api/events/{uuid4()}", headers=headers)
    assert res_404.status_code == 404
    assert res_404.json()["trace_id"] == trace_id_val


def test_repository_dependency_injection_override() -> None:
    """Verify repository interface can be overridden via FastAPI Depends mechanism (Issue #4 prep)."""
    custom_repo = InMemoryEventRepository()
    test_app = create_app()
    test_app.dependency_overrides[get_event_repository] = lambda: custom_repo

    with TestClient(test_app) as custom_client:
        res = custom_client.post(
            "/api/events",
            json={
                "shift_key": "2026-11-14-night",
                "machine": "Custom-1",
                "category": "safety",
                "note": "Safety guard checked",
            },
        )
        assert res.status_code == 201
        event_id = UUID(res.json()["id"])
        # Verify stored in custom_repo
        assert custom_repo.get_by_id(event_id) is not None


def test_default_app_wiring_without_overrides() -> None:
    """Verify default global app wiring operates correctly without dependency overrides."""
    with TestClient(app) as global_client:
        shift = "2026-11-14-early"
        res = global_client.post(
            "/api/events",
            json={
                "shift_key": shift,
                "machine": "Default-Machine",
                "category": "info",
                "note": "Testing global app",
            },
        )
        assert res.status_code == 201
        event_id = res.json()["id"]

        list_res = global_client.get(f"/api/events?shift_key={shift}")
        assert list_res.status_code == 200
        assert any(e["id"] == event_id for e in list_res.json())

        # Clean up
        del_res = global_client.delete(f"/api/events/{event_id}")
        assert del_res.status_code == 204
