# Telemetry and Observability Specification — Shift Handover Copilot

This document specifies the OpenTelemetry instrumentation, structured logging, and telemetry privacy filters implemented in `backend/app/telemetry.py` pursuant to `plan.md` §4 (AC-8, AC-11), §16, and §22.

---

## 1. Resource Attributes

Every telemetry signal (traces, metrics, logs) is tagged with standard W3C / OpenTelemetry resource attributes dynamically configured from application settings (`Settings`):
- `service.name`: Set from `settings.service_name` (default: `"handover"`, with environment variable alias support for `OTEL_SERVICE_NAME`, `SERVICE_NAME`, and `service_name`).
- `deployment.environment`: Set from `settings.environment` (or `APP_ENV`: `local`, `dev`, `prod`).
- `service.version`: Set from `settings.version` (or `APP_VERSION`, matching container image tag).

---

## 2. Metric Instruments & Cardinality Rules

OpenTelemetry meters publish bounded, low-cardinality Prometheus-compatible metrics to avoid exceeding Grafana Cloud Free tier series limits (capped at 10,000 active series). All metric recording helpers automatically populate `environment` and `version` dimensions from active application settings (`Settings.environment`, `Settings.version`) unless explicitly overridden by caller arguments.

| Metric Name | Type | Description | Allowed Dimensions / Labels |
|---|---|---|---|
| `handover_events_created_total` | Counter | Total number of shift events created | `env`, `environment`, `version` |
| `handover_reports_generated_total` | Counter | Total number of handover reports generated | `outcome` (`"success"` \| `"error"`), `model`, `environment`, `version` |
| `handover_generation_duration_seconds` | Histogram | Handover report generation latency in seconds | `outcome` (`"success"` \| `"error"`), `environment`, `version` |
| `handover_fallback_used_total` | Counter | Total times the LLM fallback model was invoked | `reason`, `environment`, `version` |
| `handover_http_requests_total` | Counter | Total incoming HTTP requests | `method`, `route`, `status_code`, `environment`, `version` |

### Strict Cardinality Enforcement Guard
To protect series limits and maintain zero-PII guarantees, metric instruments **must never** accept high-cardinality or user-provided labels:
- **Prohibited:** `shift_key`, `report_id`, `machine`, `note`, `notes`, `user_text`, `summary`, or raw text.
- Enforced at runtime by `validate_metric_attributes()` in `app/telemetry.py`. Attempting to register prohibited dimensions raises a `ValueError` in recording helpers or strips them cleanly.

---

## 3. Tracing Spans & Lifecycle

Distributed traces follow the W3C TraceContext standard. The generation pipeline executes within standard nested spans:

1. **`http.server`**: Root span managed by `TelemetryMiddleware` for incoming FastAPI requests.
2. **`handover.load_events`**: Database query retrieving shift events for the requested `shift_key` (records `event_count`).
3. **`handover.build_prompt`**: User prompt construction and token-budget preparation.
4. **`gemini.generate`**: Vertex AI / Gemini LLM generation call:
   - Attributes: `model` (e.g. `gemini-3.5-flash-lite`), `handover.is_fallback` (`True` \| `False`), `tokens` (LLM token count integer).
5. **`handover.validate`**: Pydantic schema validation and AC-4 safety notes coverage verification.
6. **`db.save_report`**: Versioned persistence of the report snapshot in PostgreSQL / SQLite (records `report_id`, `version`).

---

## 4. Structured JSON Logging (`structlog`)

Logs are emitted as single-line JSON with standard fields:
- `timestamp`: ISO 8601 UTC timestamp
- `level`: Log level (`info`, `warning`, `error`, `debug`)
- `msg`: Log message
- `trace_id`: Correlated 32-hex W3C trace ID
- `span_id`: Correlated 16-hex W3C span ID
- `service` / `service.name`: Service name (`settings.service_name`, default: `"handover"`)
- `env`: Environment (`local`, `dev`, `prod`)
- `version`: Application version

**Allowed operational metadata:**
- `shift_key`, `report_id`, `outcome`, `model`, `duration_ms`.

---

## 5. Telemetry Privacy Filter (AC-11, plan.md §16, §22)

To ensure operators and shift workers can record incidents freely without exposing sensitive production details or secrets to third-party collectors or on-call LLM agents, an automated privacy filter is enforced:

### Blocked / Masked Fields
- **Event notes:** `note`, `notes`, `raw_text`, `user_notes`, `user_text`, `prompt`
- **Handover report text:** `summary`, `report_text`, `open_actions`, `safety_notes`, LLM generation outputs
- **Credentials & tokens:** `admin_token`, `authorization`, `token`, `secret`, `bearer`, `api_key`, `password`

### Scrubbing Mechanism
- `structlog_privacy_filter`: Applied in structlog's processor chain before JSON rendering. Recursively scans dictionaries and lists, replacing sensitive keys and regex-detected Bearer / parameter tokens with `"[REDACTED]"`.
- `PrivacyFilterSpanProcessor`: OpenTelemetry SpanProcessor that scrubs `span.attributes` on span end, ensuring no sensitive values reach exported trace spans.

---

## 6. Cloud Run Force Flush Middleware

Because Google Cloud Run throttles container CPU between HTTP requests (when instances scale down or go idle), background export threads could starve, stranding metrics and traces.

`TelemetryMiddleware` executes in `backend/app/main.py`:
- In a `finally` block guaranteed to execute upon request completion (even when exceptions or HTTP 5xx occur).
- Calls `force_flush()` on both the OpenTelemetry `TracerProvider` and `MeterProvider` with a 5000 ms timeout.
