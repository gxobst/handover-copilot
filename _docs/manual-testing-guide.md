# Manual Testing Guide — Live Services on Swagger UI (`http://127.0.0.1:8000/docs`)

This guide provides an end-to-end walkthrough to manually test and verify the complete functionality and agentic workflows of the **Shift Handover Copilot** backend.

> [!IMPORTANT]
> **Real Live Services Only (No Mocks)**:
> This entire test suite runs exclusively against **live production-grade cloud and database services**:
> 1. **Live Google Cloud Vertex AI**: Calls the Google GenAI SDK against project `boxwood-scope-292916` in location `global` using model `google/gemini-3.5-flash-lite` (latency ~3.3s).
> 2. **Live Database Persistence**: Persists all records to SQLite (`handover.db`) using SQLAlchemy ORM with foreign keys, unique constraints, and transaction rollback.
> 3. **Live GitHub Repository Dispatch**: The incident webhook relay sends real HTTPS requests to GitHub REST API (`gxobst/handover-copilot`) using a GitHub PAT.
> 4. **Live Incident Fallback**: Verifies live automated failover when calling an unavailable model against Vertex AI.

---

## 1. Prerequisites & Starting the Live Server

### 1.1 Verify Google Cloud ADC Credentials
Ensure Application Default Credentials (ADC) are configured for your GCP project:
```bash
gcloud auth application-default set-quota-project boxwood-scope-292916
gcloud config set project boxwood-scope-292916
```

### 1.2 Verify Environment Configuration (`.env`)
Confirm your [.env](file:///E:/Project/AI%20Dev%20Tools%20Zoomcamp/shift-handover-copilot/.env) in the project root has the live settings enabled:
```dotenv
APP_ENV=local
APP_VERSION=0.1.0
PORT=8000

DATABASE_URL=sqlite:///./handover.db

GCP_PROJECT=boxwood-scope-292916
GCP_LOCATION=global

LLM_BACKEND=vertex
LLM_TIMEOUT_S=20
ACTIVE_MODEL=google/gemini-3.5-flash-lite
FALLBACK_MODEL=google/gemini-3.1-flash-lite

ADMIN_TOKEN=dev-admin-secret-key-12345
RELAY_WEBHOOK_TOKEN=dev-relay-token-secret-123
GITHUB_REPOSITORY=gxobst/handover-copilot
```

### 1.3 Launch the FastAPI Server
Open a terminal in the `backend/` directory:
```bash
cd "E:\Project\AI Dev Tools Zoomcamp\shift-handover-copilot\backend"
uv run uvicorn app.main:app --reload --port 8000
```

Open your browser to the interactive Swagger UI:
👉 **[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)**

---

## 2. Test Scenarios (Step-by-Step)

### Scenario 1: System Health Check (AC-9)
**Objective**: Verify the live server is operational and responding.

* **Method & URL**: `GET /api/healthz`
* **Swagger Step**: Expand `GET /api/healthz` -> Click **Try it out** -> Click **Execute**.
* **Request Input**: None.
* **Expected Output**:
  * **HTTP Status**: `200 OK`
  * **Response Body**:
    ```json
    {
      "status": "ok",
      "version": "0.1.0",
      "environment": "local"
    }
    ```

---

### Scenario 2: Live Shift Event Seeding (AC-1, AC-2)
**Objective**: Log structured shift events across downtime, safety, and quality categories into the live database.

* **Method & URL**: `POST /api/events`
* **Swagger Step**: Expand `POST /api/events` -> Click **Try it out**.

#### Case 2A: Log a Downtime Event
* **Request Body**:
  ```json
  {
    "shift_key": "2026-11-14-early",
    "machine": "Press-01",
    "category": "downtime",
    "note": "Hydraulic pressure dropped suddenly, main stamping line stopped for 45 minutes."
  }
  ```
* **Expected Output**:
  * **HTTP Status**: `201 Created`
  * **Response Body**:
    ```json
    {
      "id": "<generated-uuid>",
      "shift_key": "2026-11-14-early",
      "machine": "Press-01",
      "category": "downtime",
      "note": "Hydraulic pressure dropped suddenly, main stamping line stopped for 45 minutes.",
      "created_at": "2026-11-14T..."
    }
    ```

#### Case 2B: Log a Safety Event
* **Request Body**:
  ```json
  {
    "shift_key": "2026-11-14-early",
    "machine": "Conveyor-B",
    "category": "safety",
    "note": "Oil spill observed near emergency stop lever, area cordoned off with warning cones."
  }
  ```
* **Expected Output**:
  * **HTTP Status**: `201 Created` with `"category": "safety"`.

#### Case 2C: Log a Quality Event
* **Request Body**:
  ```json
  {
    "shift_key": "2026-11-14-early",
    "machine": "Packaging-Line",
    "category": "quality",
    "note": "Heat seal integrity test failed on batch 402; 50 units quarantined for re-inspection."
  }
  ```
* **Expected Output**:
  * **HTTP Status**: `201 Created` with `"category": "quality"`.

---

### Scenario 3: Event Input Boundary & Validation (RFC 9457 ProblemDetails)
**Objective**: Verify rejection of invalid event formats per RFC 9457 `application/problem+json`.

* **Method & URL**: `POST /api/events`

#### Case 3A: Invalid Category
* **Request Body**:
  ```json
  {
    "shift_key": "2026-11-14-early",
    "machine": "Press-01",
    "category": "hazard",
    "note": "Testing rejected category"
  }
  ```
* **Expected Output**:
  * **HTTP Status**: `422 Unprocessable Entity`
  * **Header**: `content-type: application/problem+json`
  * **Response Body**:
    ```json
    {
      "type": "about:blank",
      "title": "Validation Error",
      "status": 422,
      "detail": "body -> category: Input should be 'downtime', 'quality', 'safety' or 'info'",
      "trace_id": "<32-hex-trace-id>"
    }
    ```

#### Case 3B: Note Exceeds 2000 Characters
* **Request Body**: A note with 2001 characters.
* **Expected Output**: `422 Unprocessable Entity` with detail `String should have at most 2000 characters`.

#### Case 3C: Invalid Shift Key Window
* **Request Body**:
  ```json
  {
    "shift_key": "2026-11-14-afternoon",
    "machine": "Press-01",
    "category": "info",
    "note": "Invalid shift window test"
  }
  ```
* **Expected Output**: `422 Unprocessable Entity` (`pattern: ^\d{4}-\d{2}-\d{2}-(early|late|night)$`).

---

### Scenario 4: Querying Events & Shift Isolation (AC-2)
**Objective**: Verify chronological event retrieval from the live database and shift isolation.

* **Method & URL**: `GET /api/events`

#### Case 4A: Retrieve Populated Shift Events
* **Parameters**:
  * `shift_key`: `2026-11-14-early`
* **Expected Output**:
  * **HTTP Status**: `200 OK`
  * **Response Body**: Array containing all 3 created events ordered chronologically ascending by `created_at`.

#### Case 4B: Shift Isolation (Unpopulated Shift)
* **Parameters**:
  * `shift_key`: `2026-11-14-night`
* **Expected Output**:
  * **HTTP Status**: `200 OK`
  * **Response Body**: `[]` (empty array, zero leaks across shifts).

---

### Scenario 5: Event Deletion (AC-2)
**Objective**: Verify permanent deletion of an event from the live database.

* **Method & URL**: `DELETE /api/events/{id}`

#### Case 5A: Delete Quality Event
* **Parameter**: `id` = `<UUID of the Case 2C quality event>`
* **Expected Output**:
  * **HTTP Status**: `204 No Content` (Empty response body).

#### Case 5B: Verify Permanent Deletion
* Re-execute `DELETE /api/events/{id}` with the same UUID.
* **Expected Output**:
  * **HTTP Status**: `404 Not Found`
  * **Header**: `content-type: application/problem+json`
  * **Response Body**:
    ```json
    {
      "type": "about:blank",
      "title": "Not Found",
      "status": 404,
      "detail": "Event not found",
      "trace_id": "<32-hex-trace-id>"
    }
    ```

---

### Scenario 6: Handover Generation Guard on Zero Events (AC-6)
**Objective**: Verify that generating a report for a shift with 0 events is rejected before invoking the LLM.

* **Method & URL**: `POST /api/reports/generate`
* **Request Body**:
  ```json
  {
    "shift_key": "2026-11-14-night"
  }
  ```
* **Expected Output**:
  * **HTTP Status**: `422 Unprocessable Entity`
  * **Header**: `content-type: application/problem+json`
  * **Response Body**:
    ```json
    {
      "type": "about:blank",
      "title": "Unprocessable Entity",
      "status": 422,
      "detail": "No events found for shift",
      "trace_id": "<32-hex-trace-id>"
    }
    ```

---

### Scenario 7: Live Handover Report Generation via Vertex AI (AC-3, AC-4)
**Objective**: Generate an immutable shift handover report by calling **real Google Cloud Vertex AI** with `google/gemini-3.5-flash-lite` in `global` location.

* **Method & URL**: `POST /api/reports/generate`
* **Request Body**:
  ```json
  {
    "shift_key": "2026-11-14-early"
  }
  ```
* **Execution Time**: ~3–5 seconds (live Google Cloud API call).
* **Expected Output**:
  * **HTTP Status**: `201 Created`
  * **Live Response Body**:
    ```json
    {
      "id": "<generated-report-uuid>",
      "shift_key": "2026-11-14-early",
      "version": 1,
      "summary": "An oil spill was observed near the emergency stop lever of Conveyor-B, and the area has been cordoned off with warning cones. Additionally, Press-01 experienced a sudden hydraulic pressure drop, causing the main stamping line to stop for 45 minutes.",
      "open_actions": [
        {
          "action": "Clean up the oil spill near the emergency stop lever of Conveyor-B and remove warning cones once safe.",
          "owner": "Shift lead",
          "priority": "high"
        },
        {
          "action": "Investigate and resolve the hydraulic pressure drop issue on Press-01.",
          "owner": "Shift lead",
          "priority": "medium"
        }
      ],
      "safety_notes": [
        "Oil spill observed near Conveyor-B emergency stop lever; area cordoned off with warning cones."
      ],
      "model_used": "google/gemini-3.5-flash-lite",
      "event_count": 2,
      "created_at": "2026-11-14T..."
    }
    ```
  * **Live Verification Checks**:
    - [x] `"model_used": "google/gemini-3.5-flash-lite"` indicates live Vertex AI generation.
    - [x] `"version": 1` on initial shift report.
    - [x] Safety note specifically preserves the Conveyor-B oil spill (AC-4 zero-omission safety rule).
    - [x] Open actions are assigned structured priority (`high`, `medium`, `low`) and ownership.

> [!TIP]
> Save the returned `"id"` UUID — you will use it in Scenario 8 to inspect the immutable historical snapshot.

---

### Scenario 8: Report History & Snapshot Detail Retrieval (AC-5)
**Objective**: Browse persisted reports and fetch immutable snapshots from the live database.

#### Case 8A: List Reports for Shift
* **Method & URL**: `GET /api/reports?shift_key=2026-11-14-early`
* **Expected Output**:
  * **HTTP Status**: `200 OK`
  * **Response Body**:
    ```json
    [
      {
        "id": "<report-uuid>",
        "shift_key": "2026-11-14-early",
        "version": 1,
        "model_used": "gemini-3.5-flash",
        "event_count": 2,
        "created_at": "2026-11-14T..."
      }
    ]
    ```

#### Case 8B: Get Full Report by ID
* **Method & URL**: `GET /api/reports/{id}`
* **Parameter**: `id` = `<UUID from Scenario 7>`
* **Expected Output**:
  * **HTTP Status**: `200 OK`
  * **Response Body**: Full report payload with `summary`, `safety_notes`, and `open_actions`.

---

### Scenario 9: Report Regeneration & Version Increment (AC-5)
**Objective**: Add a new shift event and regenerate the report to verify version incrementing (`v1` $\rightarrow$ `v2`) while preserving `v1` immutably.

#### Step 1: Add a New Info Event
* **Method & URL**: `POST /api/events`
* **Request Body**:
  ```json
  {
    "shift_key": "2026-11-14-early",
    "machine": "Warehouse-Dock",
    "category": "info",
    "note": "Pallet delivery batch 881 received and checked into cold storage."
  }
  ```
* **Expected Output**: `201 Created`.

#### Step 2: Regenerate Report
* **Method & URL**: `POST /api/reports/generate`
* **Request Body**:
  ```json
  {
    "shift_key": "2026-11-14-early"
  }
  ```
* **Expected Output**:
  * **HTTP Status**: `201 Created`
  * **Response Body**:
    - `"version": 2`
    - `"event_count": 3`
    - `"summary"` incorporates the warehouse pallet delivery.

#### Step 3: Verify Version 1 Snapshot Immutability
* Call `GET /api/reports/{id_v1}` with the version 1 UUID from Scenario 7.
* **Expected Output**: Returns Version 1 unchanged (`"version": 1`, `"event_count": 2`).

---

### Scenario 10: Admin Settings Authentication (AC-10)
**Objective**: Verify Bearer token authorization on sensitive admin settings endpoints.

* **Method & URL**: `GET /api/admin/settings`

#### Case 10A: Unauthorized (No Token)
* Click **Execute** in Swagger without authorizing.
* **Expected Output**:
  * **HTTP Status**: `401 Unauthorized`
  * **Response Body**:
    ```json
    {
      "type": "about:blank",
      "title": "Unauthorized",
      "status": 401,
      "detail": "Invalid or missing bearer token",
      "trace_id": "<32-hex-trace-id>"
    }
    ```

#### Case 10B: Authorized with Admin Token
* Click the green **Authorize 🔓** button at the top right of the Swagger UI.
* In the **HTTPBearer (apiKey)** field, enter:
  `dev-admin-secret-key-12345`
* Click **Authorize** -> Click **Close**.
* Re-execute `GET /api/admin/settings`.
* **Expected Output**:
  * **HTTP Status**: `200 OK`
  * **Response Body**:
    ```json
    {
      "active_model": "google/gemini-3.5-flash-lite",
      "fallback_model": "google/gemini-3.1-flash-lite"
    }
    ```

---

### Scenario 11: Dynamic Admin Model Update (AC-10)
**Objective**: Update the active model dynamically at runtime without requiring a server restart.

* **Method & URL**: `PUT /api/admin/settings`
* **Swagger Auth**: Authorized with `dev-admin-secret-key-12345`.
* **Request Body**:
  ```json
  {
    "active_model": "google/gemini-3.1-flash-lite",
    "fallback_model": "google/gemini-3.5-flash-lite"
  }
  ```
* **Expected Output**:
  * **HTTP Status**: `200 OK`
  * **Response Body**:
    ```json
    {
      "active_model": "google/gemini-3.1-flash-lite",
      "fallback_model": "google/gemini-3.5-flash-lite"
    }
    ```
* Call `GET /api/admin/settings` to verify the settings updated in memory immediately.

---

### Scenario 12: Live Incident Injection & Automatic Fallback Retry (AC-7)
**Objective**: Simulate a retired-model outage against live Vertex AI and verify automatic fallback retry.

#### Step 1: Inject Outage via Admin API
* **Method & URL**: `PUT /api/admin/settings`
* Set `active_model` to an unavailable/retired model (e.g. `google/gemini-2.5-flash-lite-retired`) that causes a 404 from Vertex AI, and `fallback_model` to `google/gemini-3.1-flash-lite` (which is healthy):
  ```json
  {
    "active_model": "google/gemini-2.5-flash-lite-retired",
    "fallback_model": "google/gemini-3.1-flash-lite"
  }
  ```
* **Expected Output**: `200 OK`.

#### Step 2: Trigger Report Generation
* **Method & URL**: `POST /api/reports/generate`
* **Request Body**:
  ```json
  {
    "shift_key": "2026-11-14-early"
  }
  ```
* **Live Fallback Mechanism**:
  1. The backend calls Vertex AI with `google/gemini-2.5-flash-lite-retired`.
  2. Vertex AI returns `404 NOT_FOUND` (`Publisher model ... not found`).
  3. The backend logs a warning: `Primary model generation failed, falling back`.
  4. The backend automatically retries with `fallback_model`: `google/gemini-3.1-flash-lite`.
  5. The fallback request succeeds in ~3.5 seconds.
* **Expected Output**:
  * **HTTP Status**: `201 Created`
  * **Key Verification**:
    ```json
    {
      "version": 3,
      "model_used": "google/gemini-3.1-flash-lite"
    }
    ```
  * Notice that `"model_used"` is recorded as `"google/gemini-3.1-flash-lite"`!

#### Step 3: Restore Default Models
* **Method & URL**: `PUT /api/admin/settings`
* **Request Body**:
  ```json
  {
    "active_model": "google/gemini-3.5-flash-lite",
    "fallback_model": "google/gemini-3.1-flash-lite"
  }
  ```
* **Expected Output**: `200 OK`.

---

### Scenario 13: Live Webhook Relay & Real GitHub Dispatch (Plan §18)
**Objective**: Verify receiving a Grafana alert, verifying webhook token, triggering a live GitHub repository dispatch, and deduplicating alert storms.

* **Method & URL**: `POST /api/relay/webhook`
* **Swagger Step**: Expand `POST /api/relay/webhook` -> Click **Try it out**.
* **Header Parameter (`X-Webhook-Token`)**:
  `dev-relay-token-secret-123`

#### Case 13A: Firing Alert Payload (Live GitHub Dispatch)
* **Request Body**:
  ```json
  {
    "receiver": "handover-relay",
    "status": "firing",
    "alerts": [
      {
        "status": "firing",
        "labels": {
          "alertname": "HandoverGenerationFailureRateHigh",
          "environment": "prod",
          "severity": "critical"
        },
        "annotations": {
          "dashboardURL": "https://grafana.example.com/d/handover",
          "runbookURL": "https://github.com/gxobst/handover-copilot/blob/main/_docs/runbook.md"
        },
        "fingerprint": "alert-fp-live-001"
      }
    ]
  }
  ```
* **Live Action**: The relay router transforms the alert and sends an authenticated HTTPS request to GitHub's REST API (`https://api.github.com/repos/gxobst/handover-copilot/dispatches`) using `GITHUB_DISPATCH_PAT`.
* **Expected Output**:
  * **HTTP Status**: `200 OK`
  * **Response Body**:
    ```json
    {
      "status": "dispatched",
      "event_type": "grafana-alert",
      "fingerprint": "alert-fp-live-001"
    }
    ```

#### Case 13B: Live Alert Deduplication
* Re-execute the exact same request within the 30-minute cooldown window.
* **Expected Output**:
  * **HTTP Status**: `200 OK`
  * **Response Body**:
    ```json
    {
      "status": "deduplicated",
      "event_type": "grafana-alert",
      "fingerprint": "alert-fp-live-001"
    }
    ```
  *(Suppresses redundant GitHub Actions runs during alert storms while returning `200 OK` to Grafana).*

---

## 3. Quick Test Checklist

| # | Scenario | Method & Endpoint | Live Expectation | AC / Architecture Reference |
|---|---|---|---|---|
| 1 | Health Check | `GET /api/healthz` | `200 OK` (`status: "ok"`) | AC-9 (liveness probe) |
| 2 | Seed Events | `POST /api/events` | `201 Created` (written to `handover.db`) | AC-1, AC-2 |
| 3 | Validation Rules | `POST /api/events` (bad input) | `422` (`application/problem+json`) | RFC 9457 ProblemDetails |
| 4 | Shift Query | `GET /api/events?shift_key=...` | `200 OK` (sorted chronological) | AC-2 |
| 5 | Event Deletion | `DELETE /api/events/{id}` | `204 No Content` $\rightarrow$ `404 Not Found` | AC-2 |
| 6 | Zero Events Guard | `POST /api/reports/generate` (0 events) | `422 Unprocessable Entity` | AC-6 |
| 7 | **Live LLM Handover** | `POST /api/reports/generate` | **`201 Created`** (Vertex AI `google/gemini-3.5-flash-lite`) | AC-3, AC-4 |
| 8 | Report History | `GET /api/reports?shift_key=...` | `200 OK` (list summaries) | AC-5 |
| 9 | Version Increment | `POST /api/reports/generate` (after add) | `201 Created` (`version: 2`) | AC-5 |
| 10 | Admin Auth | `GET /api/admin/settings` | `401 Unauthorized` without Bearer | AC-10 |
| 11 | Dynamic Settings | `PUT /api/admin/settings` | `200 OK` (effective immediately) | AC-10 |
| 12 | **Live Incident Fallback** | `POST /api/reports/generate` (404 model) | **`201 Created`** (failover to fallback) | AC-7 |
| 13 | **Live GitHub Dispatch** | `POST /api/relay/webhook` | **`200 OK`** (`dispatched` $\rightarrow$ `deduplicated`) | Plan §18 Relay |
