# Manual Testing Guide — Swagger UI (`http://127.0.0.1:8000/docs`)

This guide provides step-by-step test cases to manually verify the complete functionality and agentic workflows of the **Shift Handover Copilot** backend.

---

## 1. Prerequisites & Starting the Server

In your terminal, navigate to `backend/` and start the server:

```bash
cd "E:\Project\AI Dev Tools Zoomcamp\shift-handover-copilot\backend"
uv run uvicorn app.main:app --reload --port 8000
```

Open your browser to the interactive Swagger UI:
👉 **[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)**

> [!NOTE]
> - By default, with `.env` configured, `LLM_BACKEND=vertex` will use live Vertex AI (`gemini-3.5-flash`).
> - To test completely offline with deterministic mock responses, set `LLM_BACKEND=fake` in `.env` and restart uvicorn.

---

## 2. Test Scenarios

### Scenario 1: System Health Check (AC-9)
**Objective**: Verify the API is running and does not touch the database.

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

### Scenario 2: Shift Event Seeding (Happy Path) (AC-1, AC-2)
**Objective**: Log structured shift events across different categories.

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
* **Expected Output**: `201 Created` with category `"safety"`.

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
* **Expected Output**: `201 Created` with category `"quality"`.

---

### Scenario 3: Event Input Boundary & Validation (Error Paths)
**Objective**: Verify rejection of invalid event formats per RFC 9457 `ProblemDetails`.

* **Method & URL**: `POST /api/events`

#### Case 3A: Invalid Category
* **Request Body**:
  ```json
  {
    "shift_key": "2026-11-14-early",
    "machine": "Press-01",
    "category": "hazard",
    "note": "Invalid category test"
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
      "detail": "Input should be 'downtime', 'quality', 'safety' or 'info' (category)",
      "trace_id": "<32-hex-trace-id>"
    }
    ```

#### Case 3B: Note Exceeds 2000 Characters
* **Request Body**: A note with 2001 characters.
* **Expected Output**: `422 Unprocessable Entity` with detail `String should have at most 2000 characters`.

#### Case 3C: Invalid Shift Key Format
* **Request Body**:
  ```json
  {
    "shift_key": "2026-11-14-afternoon",
    "machine": "Press-01",
    "category": "info",
    "note": "Invalid shift window test"
  }
  ```
* **Expected Output**: `422 Unprocessable Entity` with detail indicating string must match `^\d{4}-\d{2}-\d{2}-(early|late|night)$`.

---

### Scenario 4: Querying Events & Shift Isolation (AC-2)
**Objective**: Verify chronological event retrieval and shift isolation.

* **Method & URL**: `GET /api/events`

#### Case 4A: Retrieve Logged Shift Events
* **Parameters**:
  * `shift_key`: `2026-11-14-early`
* **Expected Output**:
  * **HTTP Status**: `200 OK`
  * **Response Body**: Array containing all 3 created events ordered chronologically ascending by `created_at`.

#### Case 4B: Shift Isolation (Query Unpopulated Shift)
* **Parameters**:
  * `shift_key`: `2026-11-14-night`
* **Expected Output**:
  * **HTTP Status**: `200 OK`
  * **Response Body**: `[]` (empty array)

---

### Scenario 5: Event Deletion (AC-2)
**Objective**: Verify permanent deletion of an event.

* **Method & URL**: `DELETE /api/events/{id}`

#### Case 5A: Delete Existing Event
* **Parameter**: `id` = `<UUID of one of the created events>`
* **Expected Output**:
  * **HTTP Status**: `204 No Content`
  * **Response Body**: Empty.

#### Case 5B: Verify Permanent Deletion
* Re-execute `DELETE /api/events/{id}` with the same UUID.
* **Expected Output**:
  * **HTTP Status**: `404 Not Found`
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

### Scenario 6: Handover Generation on Zero Events (AC-6)
**Objective**: Verify that generating a report for a shift with 0 events is rejected.

* **Method & URL**: `POST /api/reports/generate`
* **Request Body**:
  ```json
  {
    "shift_key": "2026-11-14-night"
  }
  ```
* **Expected Output**:
  * **HTTP Status**: `422 Unprocessable Entity`
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

### Scenario 7: Live Handover Report Generation (AC-3, AC-4)
**Objective**: Generate a structured, immutable shift handover report via LLM.

* **Method & URL**: `POST /api/reports/generate`
* **Request Body**:
  ```json
  {
    "shift_key": "2026-11-14-early"
  }
  ```
* **Expected Output**:
  * **HTTP Status**: `201 Created`
  * **Response Time**: Typically 3–7 seconds.
  * **Response Body**:
    ```json
    {
      "id": "<generated-report-uuid>",
      "shift_key": "2026-11-14-early",
      "version": 1,
      "summary": "...",
      "open_actions": [
        {
          "action": "Clean up oil spill near Conveyor-B emergency stop lever...",
          "owner": "Shift lead",
          "priority": "high"
        },
        {
          "action": "Investigate hydraulic pressure drop on Press-01...",
          "owner": "Shift lead",
          "priority": "medium"
        }
      ],
      "safety_notes": [
        "Oil spill observed near emergency stop lever at Conveyor-B; area cordoned off."
      ],
      "model_used": "gemini-3.5-flash",
      "event_count": 2,
      "created_at": "2026-11-14T..."
    }
    ```
  * **Checks**:
    - [x] `version == 1`
    - [x] All safety events are present in `safety_notes` (AC-4)
    - [x] Actions have structured `action`, `owner`, and `priority` (`high`, `medium`, or `low`)
    - [x] `summary` highlights safety and downtime first

---

### Scenario 8: Report History & Snapshot Retrieval (AC-5)
**Objective**: Browse generated reports and view immutable report details.

#### Case 8A: List Reports for Shift
* **Method & URL**: `GET /api/reports?shift_key=2026-11-14-early`
* **Expected Output**:
  * **HTTP Status**: `200 OK`
  * **Response Body**: Array of `ReportSummary` items:
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
  * **Response Body**: Exact match of the full report generated in Scenario 7.

---

### Scenario 9: Report Regeneration & Version Increment (AC-5)
**Objective**: Add another event and regenerate to verify version incrementing.

#### Step 1: Add a New Event
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

#### Step 2: Regenerate Handover
* **Method & URL**: `POST /api/reports/generate`
* **Request Body**:
  ```json
  {
    "shift_key": "2026-11-14-early"
  }
  ```
* **Expected Output**:
  * **HTTP Status**: `201 Created`
  * **Response Body**: Contains:
    - `"version": 2`
    - `"event_count": 3`
    - Updated summary mentioning pallet delivery.

#### Step 3: Verify Version 1 Remains Intact
* Call `GET /api/reports/{id_v1}` with the version 1 UUID from Scenario 7.
* **Expected Output**: Version 1 is still returned with `"version": 1` and `"event_count": 2`.

---

### Scenario 10: Admin Settings Authentication (AC-10)
**Objective**: Verify token protection on admin settings endpoints.

* **Method & URL**: `GET /api/admin/settings`

#### Case 10A: No Token Provided
* Click **Execute** without clicking the top Swagger **Authorize** button.
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

#### Case 10B: Authorize with Valid Token
* Click the green **Authorize 🔓** button at the top of Swagger.
* Enter Value: `dev-admin-secret-key-12345` -> Click **Authorize** -> **Close**.
* Re-execute `GET /api/admin/settings`.
* **Expected Output**:
  * **HTTP Status**: `200 OK`
  * **Response Body**:
    ```json
    {
      "active_model": "gemini-3.5-flash",
      "fallback_model": "gemini-4-argon"
    }
    ```

---

### Scenario 11: Dynamic Admin Model Update & Immediate Effect (AC-10)
**Objective**: Update the active model dynamically without server restart.

* **Method & URL**: `PUT /api/admin/settings`
* **Swagger Auth**: Keep authorized with `dev-admin-secret-key-12345`.
* **Request Body**:
  ```json
  {
    "active_model": "gemini-4-argon",
    "fallback_model": "gemini-3.5-flash"
  }
  ```
* **Expected Output**:
  * **HTTP Status**: `200 OK`
  * **Response Body**:
    ```json
    {
      "active_model": "gemini-4-argon",
      "fallback_model": "gemini-3.5-flash"
    }
    ```
* **Verification**: Call `GET /api/admin/settings` -> returns the newly updated models immediately.

---

### Scenario 12: Incident Injection & Automatic Fallback (AC-7)
**Objective**: Simulate a retired-model outage and verify automatic fallback retry.

#### Step 1: Inject Outage via Admin API
* **Method & URL**: `PUT /api/admin/settings`
* Set `active_model` to a retired model that causes a 404/not found error:
  ```json
  {
    "active_model": "gemini-2.5-flash-lite",
    "fallback_model": "gemini-3.5-flash"
  }
  ```
* **Expected Output**: `200 OK` (Admin validation accepts pattern, intentionally not restricted by an allowlist).

#### Step 2: Trigger Generation
* **Method & URL**: `POST /api/reports/generate`
* **Request Body**:
  ```json
  {
    "shift_key": "2026-11-14-early"
  }
  ```
* **Expected Output**:
  * **HTTP Status**: `201 Created`
  * **Key Check**: Look at `"model_used"` in the response:
    ```json
    {
      "version": 3,
      "model_used": "gemini-3.5-flash"
    }
    ```
  * **Explanation**: The primary model (`gemini-2.5-flash-lite`) failed; the service automatically retried once on `fallback_model` (`gemini-3.5-flash`) and recorded `model_used = "gemini-3.5-flash"`!

#### Step 3: Restore Default Models
* **Method & URL**: `PUT /api/admin/settings`
* **Request Body**:
  ```json
  {
    "active_model": "gemini-3.5-flash",
    "fallback_model": "gemini-4-argon"
  }
  ```
* **Expected Output**: `200 OK`.

---

### Scenario 13: Incident Webhook Relay (Grafana -> GitHub Dispatch)
**Objective**: Verify alert payload transformation and fingerprint deduplication.

* **Method & URL**: `POST /api/relay/webhook`
* **Header**: Set `X-Webhook-Token`: `dev-relay-token-secret-123`

#### Case 13A: Firing Alert Payload
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
        "fingerprint": "abc-alert-fingerprint-001"
      }
    ]
  }
  ```
* **Expected Output**:
  * **HTTP Status**: `200 OK`
  * **Response Body**:
    ```json
    {
      "status": "dispatched",
      "event_type": "grafana-alert",
      "fingerprint": "abc-alert-fingerprint-001"
    }
    ```

#### Case 13B: Alert Deduplication
* Re-execute the exact same request within 30 minutes.
* **Expected Output**:
  * **HTTP Status**: `200 OK`
  * **Response Body**:
    ```json
    {
      "status": "deduplicated",
      "event_type": "grafana-alert",
      "fingerprint": "abc-alert-fingerprint-001"
    }
    ```
  *(Prevents repeated alert storms from triggering redundant GitHub Action runs).*

---

## 3. Quick Test Checklist

| # | Scenario | Expected Status | AC Reference |
|---|---|---|---|
| 1 | `GET /api/healthz` | `200 OK` | AC-9 |
| 2 | `POST /api/events` (Valid categories) | `201 Created` | AC-1 |
| 3 | `POST /api/events` (Invalid category/length) | `422 Unprocessable Entity` | ProblemDetails |
| 4 | `GET /api/events?shift_key=...` | `200 OK` (sorted) | AC-2 |
| 5 | `DELETE /api/events/{id}` | `204 No Content` $\rightarrow$ `404 Not Found` | AC-2 |
| 6 | `POST /api/reports/generate` (0 events) | `422 Unprocessable Entity` | AC-6 |
| 7 | `POST /api/reports/generate` ($\ge 1$ events) | `201 Created` (with safety notes) | AC-3, AC-4 |
| 8 | `GET /api/reports?shift_key=...` & `GET /api/reports/{id}` | `200 OK` | History & Detail |
| 9 | `POST /api/reports/generate` (Regenerate) | `201 Created` (`version + 1`) | AC-5 |
| 10 | `GET /api/admin/settings` (No token) | `401 Unauthorized` | AC-10 |
| 11 | `PUT /api/admin/settings` (Valid token) | `200 OK` (Effective immediately) | AC-10 |
| 12 | `POST /api/reports/generate` (With retired model) | `201 Created` (`model_used = fallback`) | AC-7 |
| 13 | `POST /api/relay/webhook` (Grafana Alert) | `200 OK` (`dispatched` $\rightarrow$ `deduplicated`) | Relay §18 |
