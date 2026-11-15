# On-Call Engineer: Alert Polling & Headless Agent Dispatch Daemon

The `on-call-engineer` package provides an autonomous daemon that continuously monitors observability alert APIs (Prometheus / Alertmanager), detects active user-impact firing alerts, and dispatches a headless coding agent configured with a mandatory verbatim system prompt to investigate, reproduce, fix, verify, and commit incident resolutions.

---

## Architecture Overview

```
                      ┌────────────────────────────────────────┐
                      │ Observability Alerts Endpoint          │
                      │ (Prometheus / Alertmanager / Mock File)│
                      └───────────────────┬────────────────────┘
                                          │ Poll tick (default: 60s)
                                          ▼
                      ┌────────────────────────────────────────┐
                      │ AlertPoller (poller.py)                │
                      │  - Filters state == "firing"           │
                      │  - Computes alert fingerprint          │
                      │  - Checks in-flight & cooldown state   │
                      │  - Sequential dispatch queue           │
                      │  - Detects resolution transitions      │
                      └───────────────────┬────────────────────┘
                                          │ Firing alert ready
                                          ▼
                      ┌────────────────────────────────────────┐
                      │ AgentDispatcher (dispatcher.py)        │
                      │  - Exact verbatim system prompt        │
                      │  - Structured incident context         │
                      │  - Subprocess execution or dry-run     │
                      └───────────────────┬────────────────────┘
                                          │
                                          ▼
                      ┌────────────────────────────────────────┐
                      │ Headless Coding Agent                  │
                      │ (e.g. agy, gemini, claude)             │
                      │  - Reads code & reproduces incident    │
                      │  - Makes minimal bug fix               │
                      │  - Runs backend tests to verify        │
                      │  - Commits fix or explains false +ve   │
                      └────────────────────────────────────────┘
```

---

## Directory Structure

```
on-call-engineer/
├── __init__.py           # Package exports
├── __main__.py           # CLI invocation entrypoint (python -m on-call-engineer)
├── config.py             # CLI argument parsing and environment variable configuration
├── models.py             # Data classes: AlertContext, AlertTrackedState, fingerprinting
├── dispatcher.py         # Verbatim system prompt and agent subprocess dispatch
├── poller.py             # Main AlertPoller loop, deduplication, cooldown, error handling
├── poll_alerts.py        # Primary CLI executable script
├── README.md             # Architecture, configuration, and operational guide
└── tests/
    ├── __init__.py
    ├── test_poller.py    # Comprehensive unit and integration test suite
    └── fixtures/         # Local mock payloads for offline testing
        ├── firing_single.json
        ├── firing_multiple.json
        ├── pending_alert.json
        ├── resolved_alert.json
        ├── empty_alerts.json
        └── malformed.json
```

---

## Mandatory On-Call System Prompt

Whenever an incident triggers an agent dispatch, the dispatched process receives the exact verbatim system prompt required by the on-call runbook:

```
You are the on-call engineer for this repository. An alert just fired.

Investigate the root cause. Read the code and reproduce the failure.
If you find a real bug, make the smallest correction, run the backend tests,
and commit the fix with a clear message.

If the alert is a false positive, explain why and do not change the code.
```

---

## Structured Incident Context

In addition to the verbatim system prompt, the agent receives structured incident details via standard input and child process environment variables:

| Context Field | Description | Source / Example |
|---|---|---|
| `alertname` | Prometheus alert rule name | `HandoverGenerationFailureRateHigh` |
| `environment` | Deployment environment | `prod`, `dev`, `staging` |
| `version` | Application version tag | `v1.2.3` |
| `severity` | Alert severity level | `critical`, `warning` |
| `summary` | Concise incident summary | `High report generation failure rate in prod` |
| `description` | Human-readable user impact description | `Shift leads cannot generate handovers...` |
| `dashboard_url` | Direct link to Grafana application dashboard | `http://34.153.185.34:3000/...` |
| `runbook_url` | Direct link to incident triage runbook | `https://github.com/.../_docs/runbook.md` |
| `firing_timestamp` | ISO timestamp when alert transitioned to firing | `2026-11-15T18:00:00Z` |
| `labels` | Dictionary of all active Prometheus labels | `service`, `owner`, `environment`, etc. |
| `annotations` | Dictionary of alert annotations | `summary`, `description`, etc. |
| `fingerprint` | Deterministic unique alert fingerprint | `a1b2c3d4e5f60718` |

### Environment Variables Passed to Child Agent
- `ON_CALL_SYSTEM_PROMPT`
- `ON_CALL_ALERT_CONTEXT` (JSON representation)
- `ON_CALL_ALERT_NAME`
- `ON_CALL_ENVIRONMENT`
- `ON_CALL_VERSION`
- `ON_CALL_SEVERITY`
- `ON_CALL_DASHBOARD_URL`
- `ON_CALL_RUNBOOK_URL`
- `ON_CALL_FIRING_TIMESTAMP`
- `ON_CALL_FINGERPRINT`

---

## Deduplication & Cooldown Mechanism

To prevent infinite dispatch loops while an alert remains in `firing` state across consecutive polling cycles:
1. **Fingerprint Tracking:** Each alert is identified by its monitoring system `fingerprint` or a deterministic SHA-256 hash derived from `alertname` and sorted key labels.
2. **In-Flight Lock:** If an agent process is currently running for an alert fingerprint, subsequent poll ticks detect the active state and do not spawn duplicate processes.
3. **Cooldown Window:** Configurable via `--cooldown` or `ALERT_COOLDOWN_SECONDS` (default: 900 seconds / 15 minutes). Once dispatched, the alert is suppressed until the cooldown window elapses.
4. **Resolution Tracking:** When an alert resolves or disappears from the active API response, the poller logs the resolution transition and marks the tracked alert as `resolved`.

---

## Configuration & CLI Options

The poller supports both CLI arguments and environment variable fallbacks:

| CLI Argument | Environment Variable | Default | Description |
|---|---|---|---|
| `--alert-url` | `ALERT_API_URL` | `http://34.153.185.34:9090/api/v1/alerts` | Observability alerts API endpoint |
| `--interval` | `POLL_INTERVAL_SECONDS` | `60` | Polling interval in seconds |
| `--cooldown` | `ALERT_COOLDOWN_SECONDS` | `900` | Cooldown period in seconds per alert |
| `--agent-cmd` | `AGENT_CMD` | `agy` | Command used to spawn coding agent |
| `--alert-file` | `ALERT_MOCK_FILE` | `None` | Local JSON fixture for offline testing |
| `--once` / `--single-run` | - | `False` | Execute a single cycle and exit 0 |
| `--dry-run` | - | `False` | Simulate dispatch without executing commands |
| `--timeout` | - | `300` | Timeout in seconds for agent subprocess |
| `-v` / `--verbose` | - | `False` | Enable debug logging |

---

## Usage Examples

### 1. Continuous Polling against Prometheus Server
```bash
python on-call-engineer/poll_alerts.py \
  --alert-url "http://34.153.185.34:9090/api/v1/alerts" \
  --interval 60 \
  --agent-cmd "agy"
```

### 2. Single Poll Dry-Run with Local Fixture
```bash
python on-call-engineer/poll_alerts.py \
  --alert-file "on-call-engineer/tests/fixtures/firing_single.json" \
  --once \
  --dry-run \
  -v
```

### 3. Running with a Custom Headless Agent Script
```bash
python on-call-engineer/poll_alerts.py \
  --agent-cmd "claude --headless" \
  --cooldown 600
```

---

## Error Resilience & Edge Cases

- **Unreachable API / Network Timeout:** Logged as a descriptive warning; daemon continues running safely and retries on the next interval tick.
- **HTTP Non-200 Responses:** Logged with HTTP status code and reason; daemon does not crash.
- **Malformed JSON / Unexpected Schema:** Logged with error details; daemon ignores malformed payload and continues on subsequent ticks.
- **Multiple Firing Alerts:** Evaluated in sequence, respecting per-alert deduplication and cooldown windows.

---

## Testing & Verification

Run the dedicated test suite:
```bash
pytest on-call-engineer/tests -v
```

Run the end-to-end verification script:
```bash
python scripts/verify_on_call_poller.py
```
