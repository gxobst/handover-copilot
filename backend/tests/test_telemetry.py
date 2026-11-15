"""Unit and integration tests for OpenTelemetry instrumentation and privacy filter."""

import io
import json
from pathlib import Path
from typing import Generator
from unittest.mock import patch
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.db.models import AppSetting
from app.db.session import create_db_engine, get_db
from app.main import create_app
from app.schemas.events import Category
from app.telemetry import (
    FORBIDDEN_METRIC_LABELS,
    SENSITIVE_KEYS,
    PrivacyFilterSpanProcessor,
    TelemetryMiddleware,
    force_flush_telemetry,
    get_in_memory_metric_reader,
    get_in_memory_span_exporter,
    get_logger,
    get_meter_provider,
    get_telemetry_resource,
    get_tracer,
    get_tracer_provider,
    init_telemetry,
    is_sensitive_key,
    record_event_created,
    record_fallback_used,
    record_generation_duration,
    record_report_generated,
    reset_telemetry_for_tests,
    sanitize_data,
    sanitize_string,
    trace_span,
    validate_metric_attributes,
)
from tests.test_generation import seed_event


# -----------------------------------------------------------------------------
# Test Fixtures for Database and TestClient
# -----------------------------------------------------------------------------

@pytest.fixture
def test_db_path(tmp_path: Path) -> Path:
    """Provide a path for an isolated temporary SQLite database."""
    return tmp_path / "test_telemetry.db"


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


# -----------------------------------------------------------------------------
# Privacy Filter Unit Tests
# -----------------------------------------------------------------------------

def test_is_sensitive_key_detection():
    """Verify is_sensitive_key flags user notes, report text, tokens, and credentials case-insensitively."""
    assert is_sensitive_key("note") is True
    assert is_sensitive_key("Note") is True
    assert is_sensitive_key("NOTE") is True
    assert is_sensitive_key("notes") is True
    assert is_sensitive_key("user_notes") is True
    assert is_sensitive_key("user_text") is True
    assert is_sensitive_key("raw_text") is True
    assert is_sensitive_key("summary") is True
    assert is_sensitive_key("Summary") is True
    assert is_sensitive_key("open_actions") is True
    assert is_sensitive_key("safety_notes") is True
    assert is_sensitive_key("admin_token") is True
    assert is_sensitive_key("token") is True
    assert is_sensitive_key("authorization") is True
    assert is_sensitive_key("Authorization") is True
    assert is_sensitive_key("secret") is True
    assert is_sensitive_key("password") is True
    assert is_sensitive_key("api_key") is True
    assert is_sensitive_key("apikey") is True

    # Safe operational fields should not be flagged
    assert is_sensitive_key("shift_key") is False
    assert is_sensitive_key("report_id") is False
    assert is_sensitive_key("outcome") is False
    assert is_sensitive_key("model") is False
    assert is_sensitive_key("duration_ms") is False
    assert is_sensitive_key("tokens") is False  # LLM token count


def test_sanitize_string_scrubs_bearer_and_tokens():
    """Verify embedded Bearer headers and query/key-value tokens are masked in string values."""
    s1 = "Request failed with Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz"
    masked1 = sanitize_string(s1)
    assert "Bearer [REDACTED]" in masked1
    assert "eyJhbGciOi" not in masked1

    s2 = "Connecting with admin_token=dev-admin-secret-12345&other=ok"
    masked2 = sanitize_string(s2)
    assert "admin_token=[REDACTED]" in masked2
    assert "dev-admin-secret" not in masked2


def test_sanitize_data_nested_structures():
    """Verify recursive redaction on nested dicts and lists."""
    raw = {
        "shift_key": "2026-11-14-night",
        "note": "Operator noted hydraulic leak on Press-2",
        "summary": "Handover summary text",
        "open_actions": ["Tighten valve 4", "Inspect seals"],
        "safety_notes": ["Wear safety glasses near Press-2"],
        "admin_token": "secret-token-value-999",
        "Authorization": "Bearer secret-bearer-abc",
        "nested": {
            "user_notes": "Operator details",
            "password": "db_password_123",
            "safe_metric": 42,
        },
        "items": [
            {"note": "item note", "valid_field": "ok"},
            "Token is Bearer my-secret-token",
        ],
    }

    sanitized = sanitize_data(raw)

    assert sanitized["shift_key"] == "2026-11-14-night"
    assert sanitized["note"] == "[REDACTED]"
    assert sanitized["summary"] == "[REDACTED]"
    assert sanitized["open_actions"] == "[REDACTED]"
    assert sanitized["safety_notes"] == "[REDACTED]"
    assert sanitized["admin_token"] == "[REDACTED]"
    assert sanitized["Authorization"] == "[REDACTED]"
    assert sanitized["nested"]["user_notes"] == "[REDACTED]"
    assert sanitized["nested"]["password"] == "[REDACTED]"
    assert sanitized["nested"]["safe_metric"] == 42
    assert sanitized["items"][0]["note"] == "[REDACTED]"
    assert sanitized["items"][0]["valid_field"] == "ok"
    assert "Bearer [REDACTED]" in sanitized["items"][1]


def test_privacy_filter_log_output_scrubbing(capsys):
    """Verify serialized JSON log lines contain zero sensitive text, report content, or credentials."""
    logger = get_logger("test_privacy")

    logger.info(
        "Event recorded",
        shift_key="2026-11-14-early",
        note="Machine 1 had an overheat emergency shutdown",
        summary="Shift summary with sensitive operator actions",
        open_actions=["Cool down radiator", "Replace coolant"],
        safety_notes=["High heat warning on Machine 1"],
        admin_token="admin-secret-test-token",
        authorization="Bearer test-bearer-auth-secret",
        model="gemini-3.5-flash-lite",
        outcome="success",
        duration_ms=150,
    )

    captured = capsys.readouterr()
    log_line = captured.out.strip()
    assert log_line, "Log output should not be empty"

    # Must be valid JSON
    log_data = json.loads(log_line)

    # Standard fields must be present
    assert "timestamp" in log_data
    assert "level" in log_data
    assert log_data["level"] == "info"
    assert "msg" in log_data
    assert "trace_id" in log_data
    assert "span_id" in log_data
    assert "service" in log_data
    assert "env" in log_data
    assert "version" in log_data

    # Allowed metadata fields
    assert log_data["shift_key"] == "2026-11-14-early"
    assert log_data["model"] == "gemini-3.5-flash-lite"
    assert log_data["outcome"] == "success"
    assert log_data["duration_ms"] == 150

    # Sensitive values must NEVER appear in the serialized JSON
    assert "Machine 1 had an overheat" not in log_line
    assert "Shift summary with sensitive" not in log_line
    assert "Cool down radiator" not in log_line
    assert "High heat warning" not in log_line
    assert "admin-secret-test-token" not in log_line
    assert "test-bearer-auth-secret" not in log_line

    # Sensitive keys must be redacted
    assert log_data["note"] == "[REDACTED]"
    assert log_data["summary"] == "[REDACTED]"
    assert log_data["open_actions"] == "[REDACTED]"
    assert log_data["safety_notes"] == "[REDACTED]"
    assert log_data["admin_token"] == "[REDACTED]"
    assert log_data["authorization"] == "[REDACTED]"


def test_privacy_filter_trace_span_attributes():
    """Verify OpenTelemetry span attributes containing sensitive keys are scrubbed."""
    reset_telemetry_for_tests()
    tracer = get_tracer("test_trace_privacy")
    exporter = get_in_memory_span_exporter()
    assert exporter is not None
    exporter.clear()

    with tracer.start_as_current_span("test_sensitive_span") as span:
        span.set_attribute("note", "Operator dropped wrench in feeder")
        span.set_attribute("summary", "Complete handover report body text")
        span.set_attribute("admin_token", "secret-admin-pass-987")
        span.set_attribute("secret", "top-secret-val")
        span.set_attribute("authorization", "Bearer confidential-token-xyz")
        span.set_attribute("model", "gemini-3.5-flash-lite")
        span.set_attribute("handover.is_fallback", False)
        span.set_attribute("tokens", 188)

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    attrs = dict(spans[0].attributes)

    # Sensitive attributes must be redacted
    assert attrs["note"] == "[REDACTED]"
    assert attrs["summary"] == "[REDACTED]"
    assert attrs["admin_token"] == "[REDACTED]"
    assert attrs["secret"] == "[REDACTED]"
    assert attrs["authorization"] == "[REDACTED]"

    # Sensitive values must NOT appear anywhere in the attributes
    assert "Operator dropped wrench" not in str(attrs)
    assert "Complete handover report body" not in str(attrs)
    assert "secret-admin-pass" not in str(attrs)
    assert "confidential-token" not in str(attrs)

    # Safe attributes remain untouched
    assert attrs["model"] == "gemini-3.5-flash-lite"
    assert attrs["handover.is_fallback"] is False
    assert attrs["tokens"] == 188


# -----------------------------------------------------------------------------
# Metric Instruments & Cardinality Guard Tests
# -----------------------------------------------------------------------------

def test_metric_instruments_recording():
    """Verify all 4 metric instruments record data points with expected labels."""
    reset_telemetry_for_tests()
    reader = get_in_memory_metric_reader()
    assert reader is not None

    record_event_created(env="dev", version="0.1.0")
    record_report_generated(outcome="success", model="gemini-3.5-flash-lite")
    record_generation_duration(duration_seconds=1.45, outcome="success")
    record_fallback_used(reason="quota_exhausted")

    metrics_data = reader.get_metrics_data()
    assert metrics_data is not None

    metric_names = {
        m.name
        for rm in metrics_data.resource_metrics
        for sm in rm.scope_metrics
        for m in sm.metrics
    }

    assert "handover_events_created_total" in metric_names
    assert "handover_reports_generated_total" in metric_names
    assert "handover_generation_duration_seconds" in metric_names
    assert "handover_fallback_used_total" in metric_names


def test_cardinality_guard_rejects_forbidden_labels():
    """Verify metric recording raises ValueError when high-cardinality or user-provided labels are attempted."""
    # Forbidden labels: shift_key, report_id, machine, note, user_text
    for forbidden in ["shift_key", "report_id", "machine", "note", "notes", "user_text", "summary"]:
        with pytest.raises(ValueError, match="Cardinality guard violation"):
            validate_metric_attributes({forbidden: "forbidden_val", "outcome": "success"}, raise_on_violation=True)

        with pytest.raises(ValueError, match="Cardinality guard violation"):
            record_report_generated(
                outcome="success",
                model="gemini-3.5-flash-lite",
                extra_labels={forbidden: "leak_val"},
            )

        with pytest.raises(ValueError, match="Cardinality guard violation"):
            record_event_created(
                extra_labels={forbidden: "leak_val"},
            )


def test_cardinality_guard_excludes_forbidden_labels_when_non_raising():
    """Verify validate_metric_attributes safely filters out prohibited labels when raise_on_violation=False."""
    raw_labels = {
        "outcome": "success",
        "model": "gemini-3.5-flash-lite",
        "shift_key": "2026-11-14-night",
        "report_id": "123e4567-e89b-12d3-a456-426614174000",
        "machine": "Press-1",
        "note": "Operator note",
    }
    safe_labels = validate_metric_attributes(raw_labels, raise_on_violation=False)
    assert safe_labels == {
        "outcome": "success",
        "model": "gemini-3.5-flash-lite",
    }
    assert "shift_key" not in safe_labels
    assert "report_id" not in safe_labels
    assert "machine" not in safe_labels
    assert "note" not in safe_labels


# -----------------------------------------------------------------------------
# Trace Correlation & RFC 9457 ProblemDetails Tests
# -----------------------------------------------------------------------------

def test_trace_correlation_on_success(client: TestClient):
    """Verify incoming requests receive an X-Trace-ID header matching trace context."""
    res = client.get("/api/healthz")
    assert res.status_code == status.HTTP_200_OK
    trace_id = res.headers.get("X-Trace-ID")
    assert trace_id is not None
    assert len(trace_id) == 32  # 32-hex W3C trace ID


def test_trace_correlation_on_error_with_custom_trace_id(client: TestClient):
    """AC-8 & AC-11: Custom X-Trace-ID header is propagated in RFC 9457 ProblemDetails payload."""
    custom_trace = "00112233445566778899aabbccddeeff"
    res = client.get("/api/events?shift_key=invalid-shift-key", headers={"X-Trace-ID": custom_trace})
    assert res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert res.headers["content-type"] == "application/problem+json"
    assert res.headers.get("X-Trace-ID") == custom_trace

    data = res.json()
    assert data["trace_id"] == custom_trace
    assert data["status"] == 422
    assert "title" in data
    assert "detail" in data


def test_trace_correlation_on_error_generates_trace_id(client: TestClient):
    """Verify that error responses without an incoming trace header automatically generate a 32-hex trace_id in ProblemDetails."""
    non_existent_id = uuid4()
    res = client.get(f"/api/reports/{non_existent_id}")
    assert res.status_code == status.HTTP_404_NOT_FOUND
    assert res.headers["content-type"] == "application/problem+json"

    trace_id_header = res.headers.get("X-Trace-ID")
    assert trace_id_header is not None
    assert len(trace_id_header) == 32

    data = res.json()
    assert data["trace_id"] == trace_id_header


# -----------------------------------------------------------------------------
# Cloud Run Force Flush Middleware Tests
# -----------------------------------------------------------------------------

def test_cloud_run_force_flush_middleware_called_on_success(client: TestClient):
    """Verify force_flush_telemetry is executed when an HTTP request succeeds."""
    with patch("app.telemetry.force_flush_telemetry") as mock_flush:
        res = client.get("/api/healthz")
        assert res.status_code == status.HTTP_200_OK
        assert mock_flush.called


def test_cloud_run_force_flush_middleware_called_on_error(client: TestClient):
    """Verify force_flush_telemetry is executed even when request fails with 4xx or 5xx."""
    with patch("app.telemetry.force_flush_telemetry") as mock_flush:
        res = client.get(f"/api/reports/{uuid4()}")
        assert res.status_code == status.HTTP_404_NOT_FOUND
        assert mock_flush.called


# -----------------------------------------------------------------------------
# Handover Generation Pipeline Spans Integration Test
# -----------------------------------------------------------------------------

def test_handover_generation_pipeline_spans(client: TestClient, db_session: Session):
    """Verify report generation creates all specified pipeline spans:

    - http.server
    - handover.load_events
    - handover.build_prompt
    - gemini.generate (attrs: model, handover.is_fallback, tokens)
    - handover.validate
    - db.save_report
    """
    reset_telemetry_for_tests()
    exporter = get_in_memory_span_exporter()
    assert exporter is not None
    exporter.clear()

    shift_key = "2026-11-14-early"
    seed_event(
        db_session,
        shift_key=shift_key,
        machine="Press-1",
        category="safety",
        note="Emergency stop engaged due to safety gate breach.",
    )

    res = client.post("/api/reports/generate", json={"shift_key": shift_key})
    assert res.status_code == status.HTTP_201_CREATED
    trace_id = res.headers.get("X-Trace-ID")
    assert trace_id is not None

    spans = exporter.get_finished_spans()
    span_names = [s.name for s in spans]

    assert "http.server" in span_names
    assert "handover.load_events" in span_names
    assert "handover.build_prompt" in span_names
    assert "gemini.generate" in span_names
    assert "handover.validate" in span_names
    assert "db.save_report" in span_names

    # Check gemini.generate attributes
    gemini_spans = [s for s in spans if s.name == "gemini.generate"]
    assert len(gemini_spans) >= 1
    g_attrs = dict(gemini_spans[0].attributes)
    assert "model" in g_attrs
    assert "handover.is_fallback" in g_attrs
    assert g_attrs["handover.is_fallback"] is False


def test_handover_generation_fallback_metric_and_span(client: TestClient, db_session: Session):
    """AC-7: Verify fallback model execution records fallback metric and sets handover.is_fallback=True on span."""
    reset_telemetry_for_tests()
    exporter = get_in_memory_span_exporter()
    reader = get_in_memory_metric_reader()
    assert exporter is not None
    assert reader is not None
    exporter.clear()

    shift_key = "2026-11-14-early"
    seed_event(
        db_session,
        shift_key=shift_key,
        machine="Lathe-1",
        category="info",
        note="Normal startup sequence complete.",
    )

    # Set bad primary model to force fallback
    db_session.add_all([
        AppSetting(key="active_model", value="bad-primary-model"),
        AppSetting(key="fallback_model", value="gemini-3.1-flash-lite"),
    ])
    db_session.commit()

    res = client.post("/api/reports/generate", json={"shift_key": shift_key})
    assert res.status_code == status.HTTP_201_CREATED
    report = res.json()
    assert report["model_used"] == "gemini-3.1-flash-lite"

    # Verify fallback metric was incremented
    metrics_data = reader.get_metrics_data()
    assert metrics_data is not None
    fallback_metrics = [
        m for rm in metrics_data.resource_metrics
        for sm in rm.scope_metrics
        for m in sm.metrics
        if m.name == "handover_fallback_used_total"
    ]
    assert len(fallback_metrics) == 1
    point = fallback_metrics[0].data.data_points[0]
    assert point.value >= 1
    assert "reason" in point.attributes

    # Verify span recorded handover.is_fallback=True
    spans = exporter.get_finished_spans()
    fallback_spans = [
        s for s in spans
        if s.name == "gemini.generate" and s.attributes.get("handover.is_fallback") is True
    ]
    assert len(fallback_spans) == 1
    assert fallback_spans[0].attributes.get("model") == "gemini-3.1-flash-lite"


# -----------------------------------------------------------------------------
# Issue #34: OpenTelemetry Resource Attributes & Structlog Context Tests
# -----------------------------------------------------------------------------

def test_settings_service_name_and_aliases():
    """Verify Settings defines service_name defaulting to 'handover' with alias support."""
    default_settings = Settings()
    assert default_settings.service_name == "handover"
    assert default_settings.app_service_name == "handover"

    # Direct keyword argument
    custom = Settings(service_name="my-custom-service")
    assert custom.service_name == "my-custom-service"

    # Alias: OTEL_SERVICE_NAME
    otel_alias = Settings(OTEL_SERVICE_NAME="otel-service-alias")
    assert otel_alias.service_name == "otel-service-alias"

    # Alias: SERVICE_NAME
    service_alias = Settings(SERVICE_NAME="service-name-alias")
    assert service_alias.service_name == "service-name-alias"


def test_resource_attributes_configuration():
    """Verify TracerProvider, MeterProvider, and active Resource contain service.name, deployment.environment, and service.version."""
    reset_telemetry_for_tests()
    default_cfg = get_settings()

    tracer_provider = get_tracer_provider()
    meter_provider = get_meter_provider()
    resource = get_telemetry_resource()

    for target in (tracer_provider.resource, meter_provider.resource, resource):
        assert target.attributes["service.name"] == "handover"
        assert target.attributes["deployment.environment"] == default_cfg.environment
        assert target.attributes["service.version"] == default_cfg.version


def test_in_memory_span_exporter_contains_resource_attributes():
    """Verify spans captured in InMemorySpanExporter carry the configured resource attributes."""
    reset_telemetry_for_tests()
    default_cfg = get_settings()
    exporter = get_in_memory_span_exporter()
    assert exporter is not None
    exporter.clear()

    tracer = get_tracer("test_resource_attributes")
    with tracer.start_as_current_span("span_with_resource"):
        pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]

    assert span.resource is not None
    assert span.resource.attributes["service.name"] == "handover"
    assert span.resource.attributes["deployment.environment"] == default_cfg.environment
    assert span.resource.attributes["service.version"] == default_cfg.version


def test_custom_settings_propagation_to_resource_attributes():
    """Verify custom service_name, environment, and version passed via Settings propagate to resource attributes."""
    custom_settings = Settings(
        service_name="custom-svc",
        environment="staging",
        version="2.0.0",
    )
    reset_telemetry_for_tests(settings=custom_settings)

    try:
        tracer_provider = get_tracer_provider()
        meter_provider = get_meter_provider()
        resource = get_telemetry_resource()

        for target in (tracer_provider.resource, meter_provider.resource, resource):
            assert target.attributes["service.name"] == "custom-svc"
            assert target.attributes["deployment.environment"] == "staging"
            assert target.attributes["service.version"] == "2.0.0"

        # Verify exported span reflects custom resource attributes
        exporter = get_in_memory_span_exporter()
        assert exporter is not None
        exporter.clear()

        tracer = get_tracer("test_custom_settings")
        with tracer.start_as_current_span("custom_span"):
            pass

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].resource.attributes["service.name"] == "custom-svc"
        assert spans[0].resource.attributes["deployment.environment"] == "staging"
        assert spans[0].resource.attributes["service.version"] == "2.0.0"
    finally:
        reset_telemetry_for_tests()


def test_structlog_log_record_service_env_version(capsys):
    """Verify structlog JSON log records contain service, service.name, env, and version via _add_app_context."""
    reset_telemetry_for_tests()
    default_cfg = get_settings()
    logger = get_logger("test_structlog_context")

    logger.info("Application context test event", extra_key="test_val")
    captured = capsys.readouterr()
    log_line = captured.out.strip()
    assert log_line

    data = json.loads(log_line)
    assert data["service"] == "handover"
    assert data["service.name"] == "handover"
    assert data["env"] == default_cfg.environment
    assert data["version"] == default_cfg.version
    assert data["extra_key"] == "test_val"

    # Test with custom settings
    custom_cfg = Settings(
        service_name="custom-logger-svc",
        environment="production",
        version="3.5.1",
    )
    reset_telemetry_for_tests(settings=custom_cfg)
    try:
        logger.info("Custom application context test event")
        captured_custom = capsys.readouterr()
        log_line_custom = captured_custom.out.strip()
        assert log_line_custom

        data_custom = json.loads(log_line_custom)
        assert data_custom["service"] == "custom-logger-svc"
        assert data_custom["service.name"] == "custom-logger-svc"
        assert data_custom["env"] == "production"
        assert data_custom["version"] == "3.5.1"
    finally:
        reset_telemetry_for_tests()


def test_telemetry_middleware_attaches_service_env_version_span_attributes(client: TestClient):
    """Verify TelemetryMiddleware attaches service.name, deployment.environment, and service.version to http.server spans."""
    reset_telemetry_for_tests()
    default_cfg = get_settings()
    exporter = get_in_memory_span_exporter()
    assert exporter is not None
    exporter.clear()

    res = client.get("/api/healthz")
    assert res.status_code == 200

    spans = exporter.get_finished_spans()
    http_spans = [s for s in spans if s.name == "http.server"]
    assert len(http_spans) >= 1
    http_span = http_spans[0]

    assert http_span.attributes is not None
    assert http_span.attributes["service.name"] == "handover"
    assert http_span.attributes["deployment.environment"] == default_cfg.environment
    assert http_span.attributes["service.version"] == default_cfg.version

