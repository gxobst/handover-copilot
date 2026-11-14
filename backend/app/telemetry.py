"""OpenTelemetry instrumentation, structlog structured logging, and telemetry privacy filter."""

from contextlib import contextmanager
import logging
import re
from typing import Any, Callable, Optional, Sequence
import uuid

from fastapi import Request
from opentelemetry import metrics, trace
from opentelemetry.metrics import Counter, Histogram, Meter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    InMemoryMetricReader,
    MetricReader,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, Tracer, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode, Status
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
import structlog

from app.config import Settings, get_settings


# -----------------------------------------------------------------------------
# Sensitive keys and patterns for Telemetry Privacy Filter (AC-11, plan.md §16, §22)
# -----------------------------------------------------------------------------

SENSITIVE_KEYS = {
    # Event notes & user input text
    "note",
    "notes",
    "raw_text",
    "user_notes",
    "user_note",
    "user_text",
    "prompt",
    "user_prompt",
    # Handover report text & LLM output
    "summary",
    "report_text",
    "open_actions",
    "safety_notes",
    "llm_output",
    "generated_text",
    "generated_report",
    # Tokens, secrets, credentials
    "token",
    "admin_token",
    "authorization",
    "secret",
    "bearer",
    "api_key",
    "apikey",
    "password",
    "credential",
    "credentials",
    "access_token",
    "refresh_token",
    "x_webhook_token",
}

# Metric cardinality guard: prohibited high-cardinality or user-provided labels (plan.md §16)
FORBIDDEN_METRIC_LABELS = {
    "shift_key",
    "report_id",
    "machine",
    "note",
    "notes",
    "summary",
    "open_actions",
    "safety_notes",
    "user_text",
    "raw_text",
    "user_notes",
    "prompt",
    "admin_token",
    "token",
    "authorization",
    "secret",
    "password",
}

BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*")
TOKEN_PARAM_PATTERN = re.compile(
    r"(?i)(token|admin_token|secret|password|api_key|authorization)=([^\s&,]+)"
)


def is_sensitive_key(key: Any) -> bool:
    """Return True if key represents sensitive user text, report content, or credentials."""
    if not isinstance(key, str):
        key = str(key)
    clean = key.lower().replace("-", "_").strip()
    if clean in SENSITIVE_KEYS:
        return True
    # Exception: "tokens" as a count (integer/number of LLM tokens) is allowed
    if clean == "tokens":
        return False

    sensitive_substrings = (
        "note",
        "secret",
        "password",
        "bearer",
        "apikey",
        "api_key",
        "admin_token",
        "auth_token",
        "authorization",
        "open_actions",
        "safety_notes",
        "raw_text",
        "user_text",
        "credential",
    )
    for sub in sensitive_substrings:
        if sub in clean:
            return True

    if clean.endswith("_token") or clean.startswith("token_") or clean == "token":
        return True

    return False


def sanitize_string(value: str) -> str:
    """Scrub tokens, secrets, and authorization values embedded in strings."""
    val = BEARER_PATTERN.sub("Bearer [REDACTED]", value)
    val = TOKEN_PARAM_PATTERN.sub(r"\1=[REDACTED]", val)
    return val


def sanitize_data(data: Any) -> Any:
    """Recursively scrub sensitive keys and credential patterns from nested structures."""
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            if is_sensitive_key(k):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_data(v)
        return sanitized
    elif isinstance(data, (list, tuple)):
        return [sanitize_data(item) for item in data]
    elif isinstance(data, str):
        return sanitize_string(data)
    else:
        return data


def validate_metric_attributes(
    attributes: dict[str, Any], raise_on_violation: bool = True
) -> dict[str, Any]:
    """Validate that metric dimensions never include prohibited high-cardinality keys.

    If raise_on_violation is True, raises ValueError if forbidden labels are present.
    Otherwise, returns attributes with forbidden labels excluded.
    """
    for key in attributes:
        if str(key).lower() in FORBIDDEN_METRIC_LABELS:
            if raise_on_violation:
                raise ValueError(
                    f"Cardinality guard violation: label '{key}' is prohibited on metric instruments "
                    "to stay within Grafana free-tier series limits and protect privacy."
                )
    return {k: v for k, v in attributes.items() if str(k).lower() not in FORBIDDEN_METRIC_LABELS}


# -----------------------------------------------------------------------------
# OpenTelemetry Span Processor for Privacy Filtering
# -----------------------------------------------------------------------------

class PrivacyFilterSpanProcessor(SpanProcessor):
    """OpenTelemetry SpanProcessor that sanitizes sensitive attributes before export."""

    def on_start(self, span: Span, parent_context: Optional[Any] = None) -> None:
        pass

    def on_end(self, span: ReadableSpan) -> None:
        if span._attributes is not None:
            sanitized = {}
            for k, v in span._attributes.items():
                if is_sensitive_key(k):
                    sanitized[k] = "[REDACTED]"
                elif isinstance(v, str):
                    sanitized[k] = sanitize_string(v)
                else:
                    sanitized[k] = v
            span._attributes = sanitized


# -----------------------------------------------------------------------------
# Structlog processors
# -----------------------------------------------------------------------------

def structlog_privacy_filter(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor that guarantees zero sensitive user notes, report text, or secrets in logs."""
    return sanitize_data(event_dict)


def _add_app_context(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Inject application environment and version metadata into structlog event dictionary."""
    settings = get_settings()
    event_dict.setdefault("env", settings.environment)
    event_dict.setdefault("version", settings.version)
    return event_dict


def _add_trace_context(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Inject active OpenTelemetry trace_id and span_id into structlog event dictionary."""
    current_span = trace.get_current_span()
    ctx = current_span.get_span_context() if current_span else None
    if ctx and ctx.is_valid:
        event_dict.setdefault("trace_id", format(ctx.trace_id, "032x"))
        event_dict.setdefault("span_id", format(ctx.span_id, "016x"))
    else:
        ctx_vars = structlog.contextvars.get_contextvars()
        event_dict.setdefault("trace_id", ctx_vars.get("trace_id", "0" * 32))
        event_dict.setdefault("span_id", ctx_vars.get("span_id", "0" * 16))
    return event_dict


# -----------------------------------------------------------------------------
# Global Telemetry State & Instruments
# -----------------------------------------------------------------------------

_tracer_provider: Optional[TracerProvider] = None
_meter_provider: Optional[MeterProvider] = None
_in_memory_span_exporter: Optional[InMemorySpanExporter] = None
_in_memory_metric_reader: Optional[InMemoryMetricReader] = None
_events_created_counter: Optional[Counter] = None
_reports_generated_counter: Optional[Counter] = None
_generation_duration_histogram: Optional[Histogram] = None
_fallback_used_counter: Optional[Counter] = None
_initialized: bool = False


def init_telemetry(
    settings: Optional[Settings] = None, force_reinit: bool = False
) -> None:
    """Initialize OpenTelemetry tracer, meter, and structlog JSON logging."""
    global _tracer_provider, _meter_provider
    global _in_memory_span_exporter, _in_memory_metric_reader
    global _events_created_counter, _reports_generated_counter
    global _generation_duration_histogram, _fallback_used_counter
    global _initialized

    if _initialized and not force_reinit:
        return

    cfg = settings or get_settings()

    # Resource attributes according to plan.md §16
    resource = Resource.create(
        {
            "service.name": "handover",
            "deployment.environment": cfg.environment,
            "service.version": cfg.version,
        }
    )

    # 1. Setup TracerProvider
    tracer_provider = TracerProvider(resource=resource)
    privacy_processor = PrivacyFilterSpanProcessor()
    tracer_provider.add_span_processor(privacy_processor)

    # 2. Setup Exporters / Readers
    if cfg.otel_exporter_otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter,
        )

        headers = {}
        if cfg.otel_exporter_otlp_headers:
            for pair in cfg.otel_exporter_otlp_headers.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    headers[k.strip()] = v.strip()

        otlp_span_exporter = OTLPSpanExporter(
            endpoint=cfg.otel_exporter_otlp_endpoint,
            headers=headers or None,
        )
        tracer_provider.add_span_processor(BatchSpanProcessor(otlp_span_exporter))

        otlp_metric_exporter = OTLPMetricExporter(
            endpoint=cfg.otel_exporter_otlp_endpoint,
            headers=headers or None,
        )
        metric_reader: MetricReader = PeriodicExportingMetricReader(otlp_metric_exporter)
        meter_provider = MeterProvider(
            resource=resource, metric_readers=[metric_reader]
        )
        _in_memory_span_exporter = None
        _in_memory_metric_reader = None
    else:
        # Offline in-memory mode for tests and local development
        _in_memory_span_exporter = InMemorySpanExporter()
        tracer_provider.add_span_processor(
            SimpleSpanProcessor(_in_memory_span_exporter)
        )

        _in_memory_metric_reader = InMemoryMetricReader()
        meter_provider = MeterProvider(
            resource=resource, metric_readers=[_in_memory_metric_reader]
        )

    _tracer_provider = tracer_provider
    _meter_provider = meter_provider
    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(meter_provider)

    # 3. Create metric instruments (plan.md §16)
    meter = meter_provider.get_meter("handover", cfg.version)
    _events_created_counter = meter.create_counter(
        name="handover_events_created_total",
        description="Total number of shift events created",
        unit="1",
    )
    _reports_generated_counter = meter.create_counter(
        name="handover_reports_generated_total",
        description="Total number of handover reports generated",
        unit="1",
    )
    _generation_duration_histogram = meter.create_histogram(
        name="handover_generation_duration_seconds",
        description="Duration of handover report generation in seconds",
        unit="s",
    )
    _fallback_used_counter = meter.create_counter(
        name="handover_fallback_used_total",
        description="Total number of times LLM fallback model was used",
        unit="1",
    )

    # 4. Configure structlog JSON output with standard fields
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", key="timestamp"),
            _add_app_context,
            _add_trace_context,
            structlog_privacy_filter,
            structlog.processors.EventRenamer(to="msg"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )

    _initialized = True


# Initialize telemetry on module import with default local/test configuration
init_telemetry()


# -----------------------------------------------------------------------------
# Telemetry Accessors & Helpers
# -----------------------------------------------------------------------------

def get_tracer(name: str = "handover") -> Tracer:
    """Return configured OpenTelemetry Tracer."""
    global _tracer_provider
    if _tracer_provider is None:
        init_telemetry()
    assert _tracer_provider is not None
    return _tracer_provider.get_tracer(name)


def get_meter(name: str = "handover") -> Meter:
    """Return configured OpenTelemetry Meter."""
    global _meter_provider
    if _meter_provider is None:
        init_telemetry()
    assert _meter_provider is not None
    return _meter_provider.get_meter(name)


def get_logger(name: Optional[str] = None) -> structlog.BoundLogger:
    """Return configured structlog logger."""
    return structlog.get_logger(name)


def get_in_memory_span_exporter() -> Optional[InMemorySpanExporter]:
    """Return the in-memory span exporter when running in local/test mode."""
    return _in_memory_span_exporter


def get_in_memory_metric_reader() -> Optional[InMemoryMetricReader]:
    """Return the in-memory metric reader when running in local/test mode."""
    return _in_memory_metric_reader


def reset_telemetry_for_tests() -> None:
    """Reset in-memory span exporter and metric reader for isolated test assertions."""
    init_telemetry(force_reinit=True)


def get_current_trace_id() -> Optional[str]:
    """Return current active 32-hex W3C trace_id."""
    span = trace.get_current_span()
    if span and span.get_span_context().is_valid:
        return format(span.get_span_context().trace_id, "032x")
    ctx_trace_id = structlog.contextvars.get_contextvars().get("trace_id")
    if ctx_trace_id:
        return str(ctx_trace_id)
    return None


def get_current_span_id() -> Optional[str]:
    """Return current active 16-hex W3C span_id."""
    span = trace.get_current_span()
    if span and span.get_span_context().is_valid:
        return format(span.get_span_context().span_id, "016x")
    ctx_span_id = structlog.contextvars.get_contextvars().get("span_id")
    if ctx_span_id:
        return str(ctx_span_id)
    return None


@contextmanager
def trace_span(name: str, attributes: Optional[dict[str, Any]] = None):
    """Context manager to create an active span with sanitization."""
    tracer = get_tracer()
    safe_attrs = sanitize_data(attributes) if attributes else None
    with tracer.start_as_current_span(name, attributes=safe_attrs) as span:
        yield span


# -----------------------------------------------------------------------------
# Metric Recording Helpers with Cardinality Enforcement
# -----------------------------------------------------------------------------

def record_event_created(
    env: Optional[str] = None,
    version: Optional[str] = None,
    extra_labels: Optional[dict[str, Any]] = None,
) -> None:
    """Increment handover_events_created_total counter."""
    settings = get_settings()
    actual_env = env or settings.environment
    actual_version = version or settings.version
    labels = {
        "env": actual_env,
        "environment": actual_env,
        "version": actual_version,
    }
    if extra_labels:
        labels.update(extra_labels)
    safe_labels = validate_metric_attributes(labels, raise_on_violation=True)
    if _events_created_counter:
        _events_created_counter.add(1, safe_labels)


def record_report_generated(
    outcome: str,
    model: str,
    extra_labels: Optional[dict[str, Any]] = None,
) -> None:
    """Increment handover_reports_generated_total counter (outcome: 'success' | 'error')."""
    labels = {
        "outcome": outcome,
        "model": model,
    }
    if extra_labels:
        labels.update(extra_labels)
    safe_labels = validate_metric_attributes(labels, raise_on_violation=True)
    if _reports_generated_counter:
        _reports_generated_counter.add(1, safe_labels)


def record_generation_duration(
    duration_seconds: float,
    outcome: str,
    extra_labels: Optional[dict[str, Any]] = None,
) -> None:
    """Record handover_generation_duration_seconds histogram."""
    labels = {
        "outcome": outcome,
    }
    if extra_labels:
        labels.update(extra_labels)
    safe_labels = validate_metric_attributes(labels, raise_on_violation=True)
    if _generation_duration_histogram:
        _generation_duration_histogram.record(duration_seconds, safe_labels)


def record_fallback_used(
    reason: str,
    extra_labels: Optional[dict[str, Any]] = None,
) -> None:
    """Increment handover_fallback_used_total counter."""
    labels = {
        "reason": reason,
    }
    if extra_labels:
        labels.update(extra_labels)
    safe_labels = validate_metric_attributes(labels, raise_on_violation=True)
    if _fallback_used_counter:
        _fallback_used_counter.add(1, safe_labels)


# -----------------------------------------------------------------------------
# Force Flush Helper (Cloud Run request completion)
# -----------------------------------------------------------------------------

def force_flush_telemetry(timeout_millis: int = 5000) -> None:
    """Force flush tracer and meter providers to prevent stranded telemetry during Cloud Run CPU throttling."""
    global _tracer_provider, _meter_provider
    if _tracer_provider and hasattr(_tracer_provider, "force_flush"):
        try:
            _tracer_provider.force_flush(timeout_millis=timeout_millis)
        except Exception:
            pass
    if _meter_provider and hasattr(_meter_provider, "force_flush"):
        try:
            _meter_provider.force_flush(timeout_millis=timeout_millis)
        except Exception:
            pass


# -----------------------------------------------------------------------------
# Cloud Run Force Flush and Trace Correlation Middleware
# -----------------------------------------------------------------------------

class TelemetryMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for W3C trace correlation and guaranteed force_flush on request completion."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        tracer = get_tracer()
        carrier = dict(request.headers)

        # Check for traceparent or incoming X-Trace-ID
        extracted_ctx = TraceContextTextMapPropagator().extract(carrier)
        incoming_trace_id = carrier.get("x-trace-id") or carrier.get("X-Trace-ID")
        if (
            incoming_trace_id
            and len(incoming_trace_id) == 32
            and not carrier.get("traceparent")
        ):
            # Synthesize W3C traceparent header from 32-hex trace-id
            carrier["traceparent"] = f"00-{incoming_trace_id}-0000000000000001-01"
            extracted_ctx = TraceContextTextMapPropagator().extract(carrier)

        # Start http.server span for request lifecycle
        span = tracer.start_span(
            name="http.server",
            context=extracted_ctx,
            kind=SpanKind.SERVER,
            attributes={
                "http.method": request.method,
                "http.route": request.url.path,
                "http.url": str(request.url),
            },
        )

        span_ctx = span.get_span_context()
        span_id = format(span_ctx.span_id, "016x")
        trace_id = incoming_trace_id or format(span_ctx.trace_id, "032x")

        # Expose trace context on request.state
        request.state.trace_id = trace_id
        request.state.span_id = span_id

        # Bind to structlog contextvars for correlated logging
        structlog.contextvars.bind_contextvars(trace_id=trace_id, span_id=span_id)

        try:
            with trace.use_span(span, end_on_exit=True):
                response = await call_next(request)
                span.set_attribute("http.status_code", response.status_code)
                response.headers["X-Trace-ID"] = trace_id
                return response
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        finally:
            force_flush_telemetry()
            structlog.contextvars.clear_contextvars()
