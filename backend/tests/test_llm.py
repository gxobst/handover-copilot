"""Unit tests for LLM abstraction layer (Issue #5)."""

from datetime import datetime, timezone
import json
from unittest.mock import MagicMock, patch
import uuid

from google.genai import errors, types
import pytest

from app.config import Settings
from app.db.models import Event
from app.llm import (
    KNOWN_MODELS,
    FakeLLMClient,
    LLMClient,
    LLMError,
    ModelNotFound,
    SYSTEM_PROMPT,
    VertexLLMClient,
    build_user_prompt,
    get_llm_client,
)
from app.schemas.events import Category, EventResponse
from app.schemas.reports import ActionPriority, OpenAction, ReportContent

# Expected verbatim prompt from plan.md §9
EXPECTED_SYSTEM_PROMPT = """You are a shift handover assistant for a manufacturing plant.
From the raw shift events, produce a handover for the incoming shift lead.
Rules:
- Use only facts present in the events. Never invent machines, numbers, or causes.
- summary: max 5 sentences, most severe first (safety > downtime > quality > info).
- open_actions: only unfinished, concrete actions. owner = the role named in the events,
  otherwise "Shift lead". priority reflects urgency.
- safety_notes: every safety-category event must be represented here.
- If information is missing, state that explicitly instead of guessing.
Return JSON matching the provided schema."""


# -----------------------------------------------------------------------------
# System Prompt & User Prompt Builder Tests
# -----------------------------------------------------------------------------


def test_system_prompt_matches_plan_verbatim():
    """Verify SYSTEM_PROMPT exactly matches plan.md §9 text."""
    assert SYSTEM_PROMPT == EXPECTED_SYSTEM_PROMPT


def test_build_user_prompt_with_dicts_chronological():
    """Verify user prompt correctly formats and sorts dict events chronologically."""
    events = [
        {
            "time": "2026-11-14T10:00:00Z",
            "machine": "Press 01",
            "category": "downtime",
            "note": "Hydraulic pressure drop",
        },
        {
            "time": "2026-11-14T06:15:00Z",
            "machine": "Conveyor A",
            "category": "info",
            "note": "Shift startup completed",
        },
        {
            "time": "2026-11-14T08:30:00Z",
            "machine": "Robot Cell 3",
            "category": "safety",
            "note": "Safety curtain trip",
        },
    ]

    prompt = build_user_prompt("2026-11-14-early", events)
    lines = prompt.strip().split("\n")

    assert lines[0] == "Shift: 2026-11-14-early"
    assert len(lines) == 4

    parsed_events = [json.loads(line) for line in lines[1:]]
    assert parsed_events[0]["time"] == "2026-11-14T06:15:00Z"
    assert parsed_events[0]["machine"] == "Conveyor A"
    assert parsed_events[0]["category"] == "info"

    assert parsed_events[1]["time"] == "2026-11-14T08:30:00Z"
    assert parsed_events[1]["machine"] == "Robot Cell 3"
    assert parsed_events[1]["category"] == "safety"

    assert parsed_events[2]["time"] == "2026-11-14T10:00:00Z"
    assert parsed_events[2]["machine"] == "Press 01"
    assert parsed_events[2]["category"] == "downtime"


def test_build_user_prompt_with_pydantic_event_responses():
    """Verify user prompt formats EventResponse Pydantic models with enums."""
    now = datetime(2026, 11, 14, 7, 0, 0, tzinfo=timezone.utc)
    ev = EventResponse(
        id=uuid.uuid4(),
        shift_key="2026-11-14-early",
        machine="CNC-12",
        category=Category.SAFETY,
        note="Emergency stop engaged during tool change",
        created_at=now,
    )

    prompt = build_user_prompt("2026-11-14-early", [ev])
    lines = prompt.strip().split("\n")
    assert lines[0] == "Shift: 2026-11-14-early"
    assert len(lines) == 2

    parsed = json.loads(lines[1])
    assert parsed["time"] == now.isoformat()
    assert parsed["machine"] == "CNC-12"
    assert parsed["category"] == "safety"
    assert parsed["note"] == "Emergency stop engaged during tool change"


def test_build_user_prompt_with_orm_events():
    """Verify user prompt handles SQLAlchemy Event objects."""
    t1 = datetime(2026, 11, 14, 14, 30, 0, tzinfo=timezone.utc)
    orm_event = Event(
        id=uuid.uuid4(),
        shift_key="2026-11-14-late",
        machine="Packaging Line 2",
        category="quality",
        note="Label alignment offset detected",
        created_at=t1,
    )

    prompt = build_user_prompt("2026-11-14-late", [orm_event])
    lines = prompt.strip().split("\n")
    assert lines[0] == "Shift: 2026-11-14-late"
    parsed = json.loads(lines[1])
    assert parsed["machine"] == "Packaging Line 2"
    assert parsed["category"] == "quality"
    assert parsed["note"] == "Label alignment offset detected"


def test_build_user_prompt_empty_events():
    """Verify empty event sequence returns shift header only."""
    prompt = build_user_prompt("2026-11-14-night", [])
    assert prompt.strip() == "Shift: 2026-11-14-night"


# -----------------------------------------------------------------------------
# LLM Settings & Configuration Tests
# -----------------------------------------------------------------------------


def test_settings_default_model_values():
    """Verify Settings defaults for active_model and fallback_model."""
    settings = Settings(_env_file=None)
    assert settings.active_model == "google/gemini-3.5-flash-lite"
    assert settings.fallback_model == "google/gemini-3.1-flash-lite"
    assert settings.llm_backend == "fake"
    assert settings.gcp_project == ""
    assert settings.gcp_location in ("global", "europe-west2")
    assert settings.llm_timeout_s == 20.0


def test_fake_llm_client_recognizes_prefixed_and_unprefixed_models():
    """Verify FakeLLMClient accepts google/ prefixed and unprefixed flash-lite models."""
    client = FakeLLMClient()
    models = [
        "google/gemini-3.5-flash-lite",
        "google/gemini-3.1-flash-lite",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
    ]
    for model_name in models:
        assert model_name in KNOWN_MODELS
        res = client.generate_handover(prompt="Shift: 2026-11-14-early", model_name=model_name)
        assert isinstance(res, ReportContent)


def test_settings_model_env_aliases(monkeypatch):
    """Verify ACTIVE_MODEL and FALLBACK_MODEL environment variable aliases work."""
    monkeypatch.setenv("ACTIVE_MODEL", "custom-active-model")
    monkeypatch.setenv("FALLBACK_MODEL", "custom-fallback-model")
    settings = Settings()
    assert settings.active_model == "custom-active-model"
    assert settings.fallback_model == "custom-fallback-model"


def test_fake_llm_client_recognizes_default_models():
    """Verify FakeLLMClient accepts both default active and fallback models from Settings."""
    settings = Settings()
    client = FakeLLMClient()
    for model_name in [settings.active_model, settings.fallback_model]:
        assert model_name in KNOWN_MODELS
        res = client.generate_handover(prompt="Shift: 2026-11-14-early", model_name=model_name)
        assert isinstance(res, ReportContent)


# -----------------------------------------------------------------------------
# Factory Function Tests
# -----------------------------------------------------------------------------


def test_get_llm_client_returns_fake():
    """Verify factory returns FakeLLMClient when configured for fake backend."""
    settings = Settings(llm_backend="fake")
    client = get_llm_client(settings)
    assert isinstance(client, FakeLLMClient)
    assert isinstance(client, LLMClient)


def test_get_llm_client_returns_vertex():
    """Verify factory returns VertexLLMClient when configured for vertex backend."""
    settings = Settings(
        llm_backend="vertex",
        gcp_project="test-project",
        gcp_location="europe-west2",
    )
    with patch("google.genai.Client"):
        client = get_llm_client(settings)
        assert isinstance(client, VertexLLMClient)
        assert isinstance(client, LLMClient)
        assert client.project == "test-project"
        assert client.location == "europe-west2"


def test_get_llm_client_unsupported_backend():
    """Verify factory raises ValueError for invalid backend identifiers."""
    settings = Settings(llm_backend="openai")
    with pytest.raises(ValueError, match="Unsupported LLM backend: 'openai'"):
        get_llm_client(settings)


# -----------------------------------------------------------------------------
# FakeLLMClient Tests
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("model_name", list(KNOWN_MODELS))
def test_fake_llm_client_generates_valid_report_content(model_name: str):
    """Verify FakeLLMClient generates valid ReportContent for all recognized models."""
    client = FakeLLMClient()
    events = [
        {
            "time": "2026-11-14T06:30:00Z",
            "machine": "Press 01",
            "category": "downtime",
            "note": "Main drive motor stopped",
        },
        {
            "time": "2026-11-14T07:15:00Z",
            "machine": "Line 2",
            "category": "safety",
            "note": "Oil spill near feeder",
        },
    ]
    prompt = build_user_prompt("2026-11-14-early", events)
    result = client.generate_handover(prompt=prompt, model_name=model_name)

    assert isinstance(result, ReportContent)
    assert len(result.summary) > 0
    assert len(result.open_actions) >= 2
    assert len(result.safety_notes) == 1
    assert "Line 2" in result.safety_notes[0]
    assert "Oil spill" in result.safety_notes[0]


def test_fake_llm_client_satisfies_ac4_safety_notes():
    """Verify domain rule AC-4: every safety event is represented in safety_notes."""
    client = FakeLLMClient()
    events = [
        {"time": "08:00", "machine": "Lathe A", "category": "safety", "note": "Guard interlock failure"},
        {"time": "09:00", "machine": "Mill B", "category": "downtime", "note": "Spindle overheat"},
        {"time": "10:00", "machine": "Welder C", "category": "safety", "note": "Ventilation smoke alert"},
    ]
    prompt = build_user_prompt("2026-11-14-early", events)
    result = client.generate_handover(prompt=prompt, model_name="gemini-3.5-flash-lite")

    assert len(result.safety_notes) == 2
    assert any("Lathe A" in note and "Guard interlock" in note for note in result.safety_notes)
    assert any("Welder C" in note and "Ventilation smoke" in note for note in result.safety_notes)


def test_fake_llm_client_no_safety_events():
    """Verify safety_notes is empty when no safety events exist in input."""
    client = FakeLLMClient()
    events = [
        {"time": "08:00", "machine": "Packaging 1", "category": "info", "note": "Scheduled cleanup"},
    ]
    prompt = build_user_prompt("2026-11-14-early", events)
    result = client.generate_handover(prompt=prompt, model_name="gemini-3.5-flash-lite")

    assert result.safety_notes == []
    assert len(result.open_actions) >= 1
    assert len(result.summary) > 0


@pytest.mark.parametrize(
    "invalid_model",
    [
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "unknown-model-xyz",
        "",
        "claude-3-5-sonnet",
    ],
)
def test_fake_llm_client_raises_model_not_found(invalid_model: str):
    """Verify ModelNotFound is raised on unknown or retired models."""
    client = FakeLLMClient()
    with pytest.raises(ModelNotFound, match="not recognized, unavailable, or deprecated"):
        client.generate_handover("Shift: test", model_name=invalid_model)


# -----------------------------------------------------------------------------
# VertexLLMClient Tests (Mocked google-genai SDK)
# -----------------------------------------------------------------------------


def test_vertex_llm_client_configures_parameters_correctly():
    """Verify VertexLLMClient builds correct GenerateContentConfig without network calls."""
    mock_genai_client = MagicMock()
    mock_response = MagicMock()
    mock_response.parsed = ReportContent(
        summary="Shift summary from vertex.",
        open_actions=[
            OpenAction(action="Test action", owner="Maintenance", priority=ActionPriority.HIGH)
        ],
        safety_notes=["Safety note 1"],
    )
    mock_genai_client.models.generate_content.return_value = mock_response

    client = VertexLLMClient(
        project="test-proj",
        location="europe-west2",
        client=mock_genai_client,
    )

    result = client.generate_handover(
        prompt="Shift: 2026-11-14-early",
        model_name="gemini-3.5-flash-lite",
        timeout_s=15.0,
    )

    assert isinstance(result, ReportContent)
    assert result.summary == "Shift summary from vertex."

    # Assert SDK call arguments
    mock_genai_client.models.generate_content.assert_called_once()
    call_kwargs = mock_genai_client.models.generate_content.call_args.kwargs
    assert call_kwargs["model"] == "gemini-3.5-flash-lite"
    assert call_kwargs["contents"] == "Shift: 2026-11-14-early"

    config: types.GenerateContentConfig = call_kwargs["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_schema == ReportContent
    assert config.temperature == 0.2
    assert config.max_output_tokens == 2048
    assert config.system_instruction == SYSTEM_PROMPT
    assert config.thinking_config.thinking_level == types.ThinkingLevel.LOW
    assert config.http_options.timeout == 15000  # 15.0s in ms


def test_vertex_llm_client_parses_json_text_fallback():
    """Verify VertexLLMClient handles response when parsed is None but text is valid JSON."""
    mock_genai_client = MagicMock()
    mock_response = MagicMock()
    mock_response.parsed = None
    mock_response.text = json.dumps(
        {
            "summary": "Valid summary from JSON text.",
            "open_actions": [
                {
                    "action": "Check lubrication levels",
                    "owner": "Technician",
                    "priority": "low",
                }
            ],
            "safety_notes": [],
        }
    )
    mock_genai_client.models.generate_content.return_value = mock_response

    client = VertexLLMClient(client=mock_genai_client)
    result = client.generate_handover(
        prompt="Shift: test",
        model_name="gemini-3.5-flash-lite",
    )

    assert isinstance(result, ReportContent)
    assert result.summary == "Valid summary from JSON text."
    assert result.open_actions[0].action == "Check lubrication levels"
    assert result.open_actions[0].priority == ActionPriority.LOW


def test_vertex_llm_client_handles_404_as_model_not_found():
    """Verify VertexLLMClient converts 404 APIError into ModelNotFound."""
    mock_genai_client = MagicMock()
    api_error = errors.APIError(code=404, response_json={"message": "Model not found: gemini-retired"})
    mock_genai_client.models.generate_content.side_effect = api_error

    client = VertexLLMClient(client=mock_genai_client)
    with pytest.raises(ModelNotFound, match="not found"):
        client.generate_handover(
            prompt="Shift: test",
            model_name="gemini-retired",
        )


def test_vertex_llm_client_handles_generic_api_error_as_llm_error():
    """Verify non-404 API errors are wrapped as LLMError."""
    mock_genai_client = MagicMock()
    api_error = errors.APIError(code=500, response_json={"message": "Internal server error"})
    mock_genai_client.models.generate_content.side_effect = api_error

    client = VertexLLMClient(client=mock_genai_client)
    with pytest.raises(LLMError, match="Vertex AI API error \\(500\\)"):
        client.generate_handover(
            prompt="Shift: test",
            model_name="gemini-3.5-flash-lite",
        )


def test_vertex_llm_client_handles_invalid_schema_as_llm_error():
    """Verify invalid JSON text content raises LLMError."""
    mock_genai_client = MagicMock()
    mock_response = MagicMock()
    mock_response.parsed = None
    mock_response.text = '{"invalid_key": "not a report"}'
    mock_genai_client.models.generate_content.return_value = mock_response

    client = VertexLLMClient(client=mock_genai_client)
    with pytest.raises(LLMError, match="Failed to parse ReportContent"):
        client.generate_handover(
            prompt="Shift: test",
            model_name="gemini-3.5-flash-lite",
        )
