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

---

## 7. Standalone GCP Observability Stack Deployment (Issue #37)

The self-contained observability stack runs on a dedicated Compute Engine VM host decoupled from the Cloud Run application stack in GCP region `europe-west2`:

- **Host Instance:** `handover-observability` (`e2-medium`, Ubuntu 24.04 LTS AMD64, zone `europe-west2-a`).
- **Network / Subnet:** VPC `default`, Subnet `default` (`10.154.0.0/20`).
- **Internal IP:** `10.154.0.3` (accessible via Direct VPC Egress from Cloud Run `handover-dev` and `handover-prod`).
- **External IP:** `34.153.185.34` (accessible from operator workstations and CI/CD pipelines).
- **Firewall Rule:** `allow-observability-ingress` attached via tag `observability-stack` allowing ports:
  - `tcp:3000` (Grafana UI & REST API)
  - `tcp:4317` (OTLP gRPC receiver)
  - `tcp:4318` (OTLP HTTP receiver)
  - `tcp:9090` (Prometheus web UI & API)
  - `tcp:3100` (Loki log ingestion & query)
  - `tcp:3200` (Tempo trace ingestion & query)
  - `tcp:13133` (Collector health check extension)

### Ingestion & Endpoints

| Component | Port | Health Endpoint | Purpose |
|---|---|---|---|
| OpenTelemetry Collector | `4318` (HTTP), `4317` (gRPC) | `http://<HOST>:13133/` | Unified telemetry ingestion for spans, metrics, and logs |
| Prometheus | `9090` | `http://<HOST>:9090/-/ready` | Metrics TSDB scraping collector `:8889` every 5s |
| Loki | `3100` | `http://<HOST>:3100/ready` | Standalone filesystem log storage |
| Tempo | `3200` | `http://<HOST>:3200/ready` | Distributed trace storage (OTLP gRPC) |
| Grafana | `3000` | `http://<HOST>:3000/api/health` | Unified dashboards with `$environment` and `$version` filtering |

### Cloud Run Direct VPC Egress Integration

Cloud Run services `handover-dev` and `handover-prod` are configured with:
- `--network=default --subnet=default --vpc-egress=private-ranges-only`
- `OTEL_EXPORTER_OTLP_ENDPOINT=http://10.154.0.3:4318`

Telemetry packets flow securely through private Google Cloud networking directly to the collector without traversing public internet routes.

### Automation Scripts

- Provisioning: `infra/08-observability-stack.sh` & `infra/08-observability-stack.ps1`
- Live Observability Verification: `scripts/verify_deployed_observability.py`
- Prometheus Alert Verification: `scripts/verify_alerts.py`

### User-Impact Failure Alerting Rules (Issue #38)

Alert rules are defined in `observability/alert.rules.yml` and mounted read-only (`:ro`) into the Prometheus container at `/etc/prometheus/alert.rules.yml`. Prometheus evaluates rules every 5 seconds. Rules focus on user impact (failed handovers, HTTP 5xx server errors) rather than raw machine saturation metrics (CPU, RAM).

#### Alert Rule Group: `handover-user-impact-alerts`

1. **`HandoverGenerationFailureRateHigh` (Critical)**
   - **Condition:** Report generation failure rate exceeds 20% (`> 0.2`) over a 10-minute sliding window, sustained for 5 minutes (`for: 5m`).
   - **PromQL:**
     ```promql
     (
       sum by (service, environment, version) (rate(handover_reports_generated_total{outcome="error"}[10m]))
       /
       sum by (service, environment, version) (rate(handover_reports_generated_total[10m]))
     ) > 0.2
     ```
   - **Labels:** `severity: critical`, `service: "{{ $labels.service }}"`, `environment: "{{ $labels.environment }}"`, `version: "{{ $labels.version }}"`, `owner: "shift-operations"`.
   - **Annotations:**
     - `summary`: "High report generation failure rate in {{ $labels.environment }}"
     - `description`: "Shift leads cannot generate handovers in environment {{ $labels.environment }} (version {{ $labels.version }}) — the incoming shift starts blind."
     - `dashboard_url`: `http://34.153.185.34:3000/d/handover-app-metrics/shift-handover-application-metrics?var-environment={{ $labels.environment }}&var-version={{ $labels.version }}`
     - `runbook_url`: `https://github.com/gxobst/handover-copilot/blob/main/_docs/manual-testing-guide.md`

2. **`HandoverHttpErrorRateHigh` (Warning)**
   - **Condition:** HTTP 5xx server error rate exceeds 10% (`> 0.1`) over a 5-minute sliding window, sustained for 5 minutes (`for: 5m`).
   - **PromQL:**
     ```promql
     (
       sum by (service, environment, version) (rate(handover_http_requests_total{status_code=~"5.."}[5m]))
       /
       sum by (service, environment, version) (rate(handover_http_requests_total[5m]))
     ) > 0.1
     ```
   - **Labels:** `severity: warning`, `service: "{{ $labels.service }}"`, `environment: "{{ $labels.environment }}"`, `version: "{{ $labels.version }}"`, `owner: "shift-operations"`.
   - **Annotations:**
     - `summary`: "High HTTP 5xx server error rate in {{ $labels.environment }}"
     - `description`: "Over 10% of HTTP requests to service {{ $labels.service }} in {{ $labels.environment }} (version {{ $labels.version }}) are returning 5xx server errors."
     - `dashboard_url`: `http://34.153.185.34:3000/d/handover-app-metrics/shift-handover-application-metrics?var-environment={{ $labels.environment }}&var-version={{ $labels.version }}`
     - `runbook_url`: `https://github.com/gxobst/handover-copilot/blob/main/_docs/manual-testing-guide.md`

#### Prometheus Live Rules API

Rule health and state can be queried directly via Prometheus HTTP API:
- Endpoint: `GET http://34.153.185.34:9090/api/v1/rules`
- Active health status: `{"status": "success", "data": {"groups": [...]}}` where rule health is `"ok"`.


