"""Unit tests for Pydantic domain schemas and RFC 9457 error models."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.schemas import (
    ActionPriority,
    Category,
    EventCreate,
    EventResponse,
    OpenAction,
    ProblemDetails,
    ReportContent,
    ReportResponse,
    ReportSummary,
    SHIFT_KEY_REGEX,
)


class MockORMObject:
    """Helper to simulate ORM models with attribute access."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


# ---------------------------------------------------------------------------
# Category Enum Tests
# ---------------------------------------------------------------------------


def test_category_enum_exact_values():
    """Verify Category enum values match plan.md domain definitions."""
    assert Category.DOWNTIME == "downtime"
    assert Category.QUALITY == "quality"
    assert Category.SAFETY == "safety"
    assert Category.INFO == "info"
    assert set(Category) == {
        Category.DOWNTIME,
        Category.QUALITY,
        Category.SAFETY,
        Category.INFO,
    }


def test_category_validation_in_event_create():
    """Verify all valid categories pass and invalid string categories are rejected."""
    for cat in ["downtime", "quality", "safety", "info"]:
        event = EventCreate(
            shift_key="2026-11-14-early",
            machine="Press-1",
            category=cat,
            note="Test note",
        )
        assert event.category == cat

    invalid_categories = ["maintenance", "other", "urgent", "INFO", "downtime "]
    for invalid_cat in invalid_categories:
        with pytest.raises(ValidationError):
            EventCreate(
                shift_key="2026-11-14-early",
                machine="Press-1",
                category=invalid_cat,
                note="Test note",
            )


# ---------------------------------------------------------------------------
# shift_key Format Regex Tests
# ---------------------------------------------------------------------------


def test_shift_key_valid_formats():
    """Verify valid shift_key formats across early, late, and night shifts."""
    valid_keys = [
        "2026-11-14-early",
        "2026-11-14-late",
        "2026-11-14-night",
        "2025-01-01-early",
        "1999-12-31-night",
    ]
    for key in valid_keys:
        event = EventCreate(
            shift_key=key,
            machine="Conveyor-2",
            category=Category.INFO,
            note="Shift started",
        )
        assert event.shift_key == key


def test_shift_key_invalid_formats():
    """Verify malformed shift_keys raise ValidationError."""
    invalid_keys = [
        "2026-11-14-morning",
        "2026-11-14-afternoon",
        "14-11-2026-early",
        "2026/11/14-early",
        "2026-11-14-early-extra",
        "2026-1-1-early",
        "invalid",
        "",
        " ",
    ]
    for key in invalid_keys:
        with pytest.raises(ValidationError):
            EventCreate(
                shift_key=key,
                machine="Conveyor-2",
                category=Category.INFO,
                note="Shift started",
            )


# ---------------------------------------------------------------------------
# EventCreate Schema & Boundary Conditions Tests
# ---------------------------------------------------------------------------


def test_event_create_valid():
    """Verify complete valid EventCreate instantiation."""
    event = EventCreate(
        shift_key="2026-11-14-late",
        machine="CNC-01",
        category=Category.DOWNTIME,
        note="Spindle overheat detected; cooling cycle initiated.",
    )
    assert event.shift_key == "2026-11-14-late"
    assert event.machine == "CNC-01"
    assert event.category == Category.DOWNTIME
    assert event.note == "Spindle overheat detected; cooling cycle initiated."


def test_event_create_note_boundary_conditions():
    """Verify note limits: 0 chars fails, 1 char passes, 2000 chars passes, 2001 chars fails."""
    # 0 chars (fail)
    with pytest.raises(ValidationError):
        EventCreate(
            shift_key="2026-11-14-early",
            machine="Press-1",
            category=Category.QUALITY,
            note="",
        )

    # 1 char boundary (pass)
    event_1 = EventCreate(
        shift_key="2026-11-14-early",
        machine="Press-1",
        category=Category.QUALITY,
        note="x",
    )
    assert len(event_1.note) == 1

    # 2000 chars boundary (pass)
    note_2000 = "a" * 2000
    event_2000 = EventCreate(
        shift_key="2026-11-14-early",
        machine="Press-1",
        category=Category.QUALITY,
        note=note_2000,
    )
    assert len(event_2000.note) == 2000

    # 2001 chars boundary (fail)
    note_2001 = "a" * 2001
    with pytest.raises(ValidationError):
        EventCreate(
            shift_key="2026-11-14-early",
            machine="Press-1",
            category=Category.QUALITY,
            note=note_2001,
        )


def test_event_create_machine_validation():
    """Verify machine cannot be empty or whitespace-only."""
    # empty string (fail)
    with pytest.raises(ValidationError):
        EventCreate(
            shift_key="2026-11-14-early",
            machine="",
            category=Category.SAFETY,
            note="Valid note",
        )

    # whitespace-only strings (fail)
    whitespace_inputs = ["   ", "\t", "\n", "  \t\n  "]
    for ws in whitespace_inputs:
        with pytest.raises(ValidationError):
            EventCreate(
                shift_key="2026-11-14-early",
                machine=ws,
                category=Category.SAFETY,
                note="Valid note",
            )

    # valid machine name (pass)
    event = EventCreate(
        shift_key="2026-11-14-early",
        machine="  Robot-Arm-4  ",
        category=Category.SAFETY,
        note="Valid note",
    )
    assert event.machine == "Robot-Arm-4"


def test_event_create_missing_required_fields():
    """Verify missing required fields raise ValidationError."""
    with pytest.raises(ValidationError):
        EventCreate.model_validate({"machine": "M1", "category": "info", "note": "ok"})
    with pytest.raises(ValidationError):
        EventCreate.model_validate({"shift_key": "2026-11-14-early", "category": "info", "note": "ok"})
    with pytest.raises(ValidationError):
        EventCreate.model_validate({"shift_key": "2026-11-14-early", "machine": "M1", "note": "ok"})
    with pytest.raises(ValidationError):
        EventCreate.model_validate({"shift_key": "2026-11-14-early", "machine": "M1", "category": "info"})


# ---------------------------------------------------------------------------
# EventResponse Schema Tests
# ---------------------------------------------------------------------------


def test_event_response_valid():
    """Verify valid EventResponse initialization and attributes."""
    event_id = uuid4()
    now = datetime.now(timezone.utc)
    event = EventResponse(
        id=event_id,
        shift_key="2026-11-14-night",
        machine="Packaging-Line-3",
        category=Category.SAFETY,
        note="Emergency stop triggered on seal unit.",
        created_at=now,
    )
    assert event.id == event_id
    assert event.shift_key == "2026-11-14-night"
    assert event.machine == "Packaging-Line-3"
    assert event.category == Category.SAFETY
    assert event.note == "Emergency stop triggered on seal unit."
    assert event.created_at == now


def test_event_response_from_attributes():
    """Verify EventResponse supports ORM object serialization via from_attributes=True."""
    event_id = uuid4()
    now = datetime.now(timezone.utc)
    mock_orm = MockORMObject(
        id=event_id,
        shift_key="2026-11-14-night",
        machine="Packaging-Line-3",
        category=Category.SAFETY,
        note="Emergency stop triggered on seal unit.",
        created_at=now,
    )
    response = EventResponse.model_validate(mock_orm)
    assert response.id == event_id
    assert response.shift_key == "2026-11-14-night"
    assert response.machine == "Packaging-Line-3"
    assert response.category == Category.SAFETY
    assert response.created_at == now


# ---------------------------------------------------------------------------
# ActionPriority & OpenAction Tests
# ---------------------------------------------------------------------------


def test_action_priority_enum():
    """Verify ActionPriority exact enum values."""
    assert ActionPriority.HIGH == "high"
    assert ActionPriority.MEDIUM == "medium"
    assert ActionPriority.LOW == "low"
    assert set(ActionPriority) == {
        ActionPriority.HIGH,
        ActionPriority.MEDIUM,
        ActionPriority.LOW,
    }


def test_open_action_valid():
    """Verify valid OpenAction model instantiation."""
    action = OpenAction(
        action="Replace sensor on line 2",
        owner="Maintenance lead",
        priority=ActionPriority.HIGH,
    )
    assert action.action == "Replace sensor on line 2"
    assert action.owner == "Maintenance lead"
    assert action.priority == ActionPriority.HIGH


def test_open_action_priority_validation():
    """Verify only 'high', 'medium', 'low' are accepted as priority."""
    for prio in ["high", "medium", "low"]:
        action = OpenAction(action="Task", owner="Lead", priority=prio)
        assert action.priority == prio

    invalid_priorities = ["urgent", "critical", "normal", "HIGH", "low ", ""]
    for prio in invalid_priorities:
        with pytest.raises(ValidationError):
            OpenAction(action="Task", owner="Lead", priority=prio)


def test_open_action_empty_and_whitespace_fields():
    """Verify action and owner reject empty and whitespace-only strings."""
    with pytest.raises(ValidationError):
        OpenAction(action="", owner="Lead", priority=ActionPriority.MEDIUM)
    with pytest.raises(ValidationError):
        OpenAction(action="   ", owner="Lead", priority=ActionPriority.MEDIUM)
    with pytest.raises(ValidationError):
        OpenAction(action="Valid action", owner="", priority=ActionPriority.MEDIUM)
    with pytest.raises(ValidationError):
        OpenAction(action="Valid action", owner="  \t  ", priority=ActionPriority.MEDIUM)


# ---------------------------------------------------------------------------
# ReportContent (LLM Structured Output Gate) Tests
# ---------------------------------------------------------------------------


def test_report_content_valid():
    """Verify ReportContent valid instantiation with open actions and safety notes."""
    report = ReportContent(
        summary="Shift proceeded normally with minor packaging line downtime.",
        open_actions=[
            OpenAction(
                action="Clean optical sensor on seal unit",
                owner="Maintenance",
                priority=ActionPriority.MEDIUM,
            )
        ],
        safety_notes=["LOTO tag applied to conveyor 4 during early shift."],
    )
    assert "normally" in report.summary
    assert len(report.open_actions) == 1
    assert report.open_actions[0].priority == ActionPriority.MEDIUM
    assert len(report.safety_notes) == 1


def test_report_content_empty_open_actions_and_safety_notes():
    """Verify ReportContent accepts empty lists for open_actions and safety_notes."""
    report = ReportContent(
        summary="Uneventful shift with zero incidents and zero open tasks.",
        open_actions=[],
        safety_notes=[],
    )
    assert report.open_actions == []
    assert report.safety_notes == []


def test_report_content_summary_validation():
    """Verify summary cannot be empty or whitespace-only."""
    with pytest.raises(ValidationError):
        ReportContent(summary="", open_actions=[], safety_notes=[])
    with pytest.raises(ValidationError):
        ReportContent(summary="   \n\t  ", open_actions=[], safety_notes=[])


def test_report_content_rejects_invalid_action_items():
    """Verify ReportContent rejects action items with invalid priority or missing fields."""
    # invalid priority in action item
    with pytest.raises(ValidationError):
        ReportContent(
            summary="Valid summary",
            open_actions=[
                {"action": "Check motor", "owner": "Electrician", "priority": "urgent"}
            ],
            safety_notes=[],
        )

    # missing owner in action item
    with pytest.raises(ValidationError):
        ReportContent(
            summary="Valid summary",
            open_actions=[{"action": "Check motor", "priority": "high"}],
            safety_notes=[],
        )

    # missing action in action item
    with pytest.raises(ValidationError):
        ReportContent(
            summary="Valid summary",
            open_actions=[{"owner": "Electrician", "priority": "high"}],
            safety_notes=[],
        )


def test_report_content_model_json_schema():
    """Verify model_json_schema produces clean schema compatible with Gemini response_json_schema."""
    schema = ReportContent.model_json_schema()
    assert isinstance(schema, dict)
    assert schema["type"] == "object"
    assert "properties" in schema

    # Required top-level keys for Gemini structured outputs
    assert set(schema["required"]) == {"summary", "open_actions", "safety_notes"}

    # Property definitions
    assert schema["properties"]["summary"]["type"] == "string"
    assert schema["properties"]["open_actions"]["type"] == "array"
    assert schema["properties"]["safety_notes"]["type"] == "array"
    assert schema["properties"]["safety_notes"]["items"]["type"] == "string"

    # Defs contains ActionPriority and OpenAction
    defs = schema["$defs"]
    assert "OpenAction" in defs
    assert "ActionPriority" in defs
    assert set(defs["ActionPriority"]["enum"]) == {"high", "medium", "low"}
    assert set(defs["OpenAction"]["required"]) == {"action", "owner", "priority"}


# ---------------------------------------------------------------------------
# ReportResponse Schema Tests
# ---------------------------------------------------------------------------


def test_report_response_valid():
    """Verify ReportResponse instantiation with complete domain fields."""
    report_id = uuid4()
    now = datetime.now(timezone.utc)
    report = ReportResponse(
        id=report_id,
        shift_key="2026-11-14-early",
        version=1,
        summary="Shift overview summary text.",
        open_actions=[
            OpenAction(action="Verify alignment", owner="Shift lead", priority=ActionPriority.LOW)
        ],
        safety_notes=["Guards inspected."],
        model_used="gemini-3.5-flash-lite",
        event_count=12,
        created_at=now,
    )
    assert report.id == report_id
    assert report.shift_key == "2026-11-14-early"
    assert report.version == 1
    assert report.model_used == "gemini-3.5-flash-lite"
    assert report.event_count == 12
    assert report.created_at == now


def test_report_response_from_attributes():
    """Verify ReportResponse supports ORM models via from_attributes=True."""
    report_id = uuid4()
    now = datetime.now(timezone.utc)
    mock_orm = MockORMObject(
        id=report_id,
        shift_key="2026-11-14-early",
        version=2,
        summary="Shift overview summary text.",
        open_actions=[
            {"action": "Verify alignment", "owner": "Shift lead", "priority": "low"}
        ],
        safety_notes=["Guards inspected."],
        model_used="gemini-3.5-flash-lite",
        event_count=5,
        created_at=now,
    )
    response = ReportResponse.model_validate(mock_orm)
    assert response.id == report_id
    assert response.version == 2
    assert len(response.open_actions) == 1
    assert response.open_actions[0].priority == ActionPriority.LOW


def test_report_response_numeric_boundaries():
    """Verify version must be >= 1 and event_count must be >= 0."""
    now = datetime.now(timezone.utc)
    base_kwargs = {
        "id": uuid4(),
        "shift_key": "2026-11-14-early",
        "summary": "Summary",
        "open_actions": [],
        "safety_notes": [],
        "model_used": "gemini-3.5-flash-lite",
        "created_at": now,
    }

    # version = 0 (fail)
    with pytest.raises(ValidationError):
        ReportResponse(version=0, event_count=0, **base_kwargs)

    # version = 1 (pass)
    resp_v1 = ReportResponse(version=1, event_count=0, **base_kwargs)
    assert resp_v1.version == 1

    # event_count = -1 (fail)
    with pytest.raises(ValidationError):
        ReportResponse(version=1, event_count=-1, **base_kwargs)

    # event_count = 0 (pass)
    resp_ec0 = ReportResponse(version=1, event_count=0, **base_kwargs)
    assert resp_ec0.event_count == 0


# ---------------------------------------------------------------------------
# ReportSummary Schema Tests
# ---------------------------------------------------------------------------


def test_report_summary_valid():
    """Verify ReportSummary valid instantiation and field values."""
    report_id = uuid4()
    now = datetime.now(timezone.utc)
    summary = ReportSummary(
        id=report_id,
        shift_key="2026-11-14-early",
        version=1,
        model_used="gemini-3.5-flash-lite",
        event_count=5,
        created_at=now,
    )
    assert summary.id == report_id
    assert summary.shift_key == "2026-11-14-early"
    assert summary.version == 1
    assert summary.model_used == "gemini-3.5-flash-lite"
    assert summary.event_count == 5
    assert summary.created_at == now
    dumped = summary.model_dump()
    assert "summary" not in dumped
    assert "open_actions" not in dumped
    assert "safety_notes" not in dumped


def test_report_summary_from_report_response_or_orm():
    """Verify ReportSummary can be validated from ORM object or full ReportResponse."""
    report_id = uuid4()
    now = datetime.now(timezone.utc)
    full_report = ReportResponse(
        id=report_id,
        shift_key="2026-11-14-late",
        version=3,
        summary="Complete shift summary",
        open_actions=[OpenAction(action="Fix valve", owner="Tech", priority=ActionPriority.HIGH)],
        safety_notes=["Guard replaced"],
        model_used="gemini-3.1-flash-lite",
        event_count=7,
        created_at=now,
    )
    summary = ReportSummary.model_validate(full_report)
    assert summary.id == report_id
    assert summary.shift_key == "2026-11-14-late"
    assert summary.version == 3
    assert summary.model_used == "gemini-3.1-flash-lite"
    assert summary.event_count == 7
    assert summary.created_at == now

    # Also from mock ORM
    mock_orm = MockORMObject(
        id=report_id,
        shift_key="2026-11-14-night",
        version=2,
        model_used="gemini-3.5-flash-lite",
        event_count=0,
        created_at=now,
    )
    summary_orm = ReportSummary.model_validate(mock_orm)
    assert summary_orm.shift_key == "2026-11-14-night"
    assert summary_orm.version == 2


def test_report_summary_validations():
    """Verify ReportSummary enforces shift_key pattern, version >= 1, event_count >= 0."""
    now = datetime.now(timezone.utc)
    base = {
        "id": uuid4(),
        "model_used": "gemini-3.5-flash-lite",
        "created_at": now,
    }

    # Invalid shift_key
    with pytest.raises(ValidationError):
        ReportSummary(shift_key="invalid-shift", version=1, event_count=1, **base)

    # Invalid version
    with pytest.raises(ValidationError):
        ReportSummary(shift_key="2026-11-14-early", version=0, event_count=1, **base)

    # Invalid event_count
    with pytest.raises(ValidationError):
        ReportSummary(shift_key="2026-11-14-early", version=1, event_count=-1, **base)


# ---------------------------------------------------------------------------
# ProblemDetails RFC 9457 Tests
# ---------------------------------------------------------------------------


def test_problem_details_defaults():
    """Verify ProblemDetails default values for type and trace_id."""
    problem = ProblemDetails(
        title="Validation Error",
        status=422,
        detail="The machine field cannot be empty.",
    )
    assert problem.type == "about:blank"
    assert problem.title == "Validation Error"
    assert problem.status == 422
    assert problem.detail == "The machine field cannot be empty."
    assert problem.trace_id is None


def test_problem_details_custom_type_and_trace_id():
    """Verify ProblemDetails with custom type URI and trace_id."""
    problem = ProblemDetails(
        type="https://example.com/probs/downtime-exceeded",
        title="Downtime Limit Exceeded",
        status=400,
        detail="Total recorded downtime exceeds 480 minutes.",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )
    assert problem.type == "https://example.com/probs/downtime-exceeded"
    assert problem.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"


def test_problem_details_serialization_without_trace_id():
    """Verify RFC 9457 serialization without trace_id."""
    problem = ProblemDetails(
        title="Not Found",
        status=404,
        detail="Event with specified ID does not exist.",
    )
    data = problem.model_dump()
    assert data["type"] == "about:blank"
    assert data["title"] == "Not Found"
    assert data["status"] == 404
    assert data["detail"] == "Event with specified ID does not exist."
    assert data["trace_id"] is None

    # Serialization with exclude_none=True omits trace_id entirely
    data_exclude_none = problem.model_dump(exclude_none=True)
    assert "trace_id" not in data_exclude_none

    json_str = problem.model_dump_json(exclude_none=True)
    assert '"trace_id"' not in json_str
    assert '"title":"Not Found"' in json_str


def test_problem_details_serialization_with_trace_id():
    """Verify RFC 9457 serialization with trace_id present."""
    trace = "0af7651916cd43dd8448eb211c80319c"
    problem = ProblemDetails(
        title="Bad Gateway",
        status=502,
        detail="LLM model unavailable and fallback exhausted.",
        trace_id=trace,
    )
    data = problem.model_dump()
    assert data["trace_id"] == trace
    assert data["status"] == 502

    json_str = problem.model_dump_json()
    assert f'"trace_id":"{trace}"' in json_str
