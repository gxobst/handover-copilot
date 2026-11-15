# plan.md — Shift Handover Copilot

**Canonical specification and delivery plan.** This file is the single source of truth for
what we build, how it is architected, and how the agent team works. The **canonical backlog
is GitHub Issues** (public repo + public Projects board), not this file. This document
defines the product and the constraints; issues define the executable work.

- Version: 1.0
- Language: English (all docs, code, comments, issues — reviewers cannot be assumed to read German)
- Repo: `handover-copilot` (public)
- Cloud: Google Cloud (GCP), region `europe-west2` (fallback `us-west1`)
- LLM: Gemini `gemini-3.5-flash-lite` (primary), `gemini-3.1-flash-lite` (fallback)
- Budget target: **≈ $0/month idle**, all components pay-per-use or free tier

---

## 0. How agents use this document

| Agent | Reads | Produces |
|---|---|---|
| PM | `plan.md`, `_docs/task-template.md`, the raw issue | Groomed issue: Goal / Acceptance criteria / Out of scope / Constraints |
| Software engineer | Groomed issue, `plan.md`, `AGENTS.md`, `_docs/process.md` | Code + tests + commits referencing `#issue` |
| QA engineer | Groomed issue + running system only | `PASS`/`FAIL` verdict comment per acceptance criterion |
| On-call | `_docs/runbook.md`, telemetry, `plan.md` §18 | Root-cause analysis, bounded fix, incident report |

Rules for every agent:
1. `plan.md` is authoritative for architecture and scope. If an issue contradicts it, comment on the issue instead of silently choosing.
2. Never invent requirements. Anything out of scope becomes a follow-up issue.
3. Never put real employer/plant data in the repo, demo, or telemetry. Synthetic data only.
4. Do not create a second specification file. Update `plan.md` via a normal issue/PR if the spec changes.

---

## 1. Problem

At shift change in a manufacturing plant, outgoing operators hand over scattered verbal notes
and paper logs about downtimes, quality problems and safety events. The incoming shift starts
without a reliable picture of open issues, and important actions get lost between shifts.

**Shift Handover Copilot** lets operators log structured shift events during the shift and
generates a consistent, structured handover report with an LLM at shift end. Reports are
persisted and browsable, so the incoming shift lead can read the current and past handovers.

### Why this application
- One CRUD entity + one GenAI action → small enough for ~20 hours.
- A crisp, meaningful user-impact failure mode: *"shift leads cannot generate a handover;
  the incoming shift starts blind."* This drives alerting and the on-call responder.

---

## 2. Users and journeys

| Persona | Journey |
|---|---|
| Operator | Select current shift → add events (machine, category, note) throughout the shift |
| Outgoing shift lead | Click **Generate Handover** → review Summary / Open Actions / Safety Notes → regenerate if events were added |
| Incoming shift lead | Open latest report or browse report history for previous shifts |

MVP is a shared single-team tool: **no user accounts**. Only the admin API is token-protected.

---

## 3. Scope

### In scope (MVP)
- Event CRUD scoped to a shift
- LLM-generated handover report with structured output, persisted and versioned
- Report history + detail view
- Admin settings API for the active/fallback model (this is the incident/fix surface)
- Full production workflow: tests, containers, CI/CD, dev/prod, observability, alert, on-call agent

### Non-goals (file as follow-up issues, do not implement)
User accounts / multi-tenant, report editing, streaming responses, PDF export, real-time
collaboration, mobile-optimised layout, multi-language UI, authentication beyond the admin token.

---

## 4. Global acceptance criteria

Issues reference these IDs. QA checks them against the running system.

| ID | Criterion |
|---|---|
| AC-1 | An operator can add an event (machine, category, note); it appears immediately and survives a backend restart |
| AC-2 | Events are filtered by the selected `shift_key`; deleting an event removes it permanently |
| AC-3 | With ≥1 event, *Generate* produces a report containing all three sections within 15 s **on a warm system** and it persists after reload. On a cold start the UI shows a progress hint, not an error |
| AC-4 | Every `safety` event of the shift is represented in Safety Notes (verified with the seeded demo shift) |
| AC-5 | Regenerating creates `version + 1`; earlier versions remain readable in history |
| AC-6 | With 0 events the button is disabled and the API returns `422` with a clear message |
| AC-7 | On primary-model failure the backend retries once on the fallback model; success records `model_used = fallback` and increments the fallback metric |
| AC-8 | If both models fail: clear error toast, **no partial report stored**, error metric incremented, response contains `trace_id` |
| AC-9 | `GET /api/healthz` returns 200 with version + environment and does **not** touch the database |
| AC-10 | `PUT /api/admin/settings` without a valid bearer token returns 401; with token it updates the models and takes effect on the next generation |
| AC-11 | For one generation request, metrics, traces and logs share the same `trace_id`; no user text or credentials appear in telemetry |
| AC-12 | `docker compose up` starts the full system; `make test` runs unit + integration + frontend tests and passes |

---

## 5. Domain model

- **`shift_key`**: `YYYY-MM-DD-{early|late|night}`, e.g. `2026-11-14-night`.
- **Shift windows** (Europe/Berlin): early 06:00–14:00, late 14:00–22:00, night 22:00–06:00.
  A night shift belongs to the date it **starts**. The UI selects date + shift explicitly;
  the timezone only drives the default selection.
- **Categories**: `downtime`, `quality`, `safety`, `info`.
- **Report**: immutable snapshot per generation, versioned per `shift_key`, records the model
  used and the number of events covered.
- **Limits** (cost/abuse guards): note ≤ 2000 chars, ≤ 200 events per shift.

---

## 6. Architecture

### 6.1 Principle
**Every component must be pay-per-use or free-tier. No VMs, no always-on database, no idle
pollers.** Cold starts are accepted and handled in the UX, not fought with keep-alive pings.

### 6.2 Local development

```
Dev mode:  Browser → Vite (5173) → FastAPI (8000) → SQLite
           frontend services layer: mock ⇄ real client (VITE_API_MODE)

Compose:   docker compose up
           ┌──────────────────────────┐    ┌────────────────────┐
           │ app (single container)   │───▶│ postgres:18        │
           │ FastAPI serves React     │    │ volume + healthcheck│
           │ static build + /api      │    └────────────────────┘
           └──────────────────────────┘
           LLM_BACKEND=fake for tests/CI, vertex for real runs
```

### 6.3 Cloud architecture

```
GitHub ── Actions (WIF/OIDC, no stored cloud keys)
  │  build once → Artifact Registry (cleanup: keep last 5 tags)
  │  deploy ────────────┐        promote (manual approval, same image)
  ▼                     ▼                   ▼
                      Cloud Run           Cloud Run
                      handover-dev        handover-prod ◄── Users (HTTPS, built-in URL)
                      min-instances=0     min-instances=0, max-instances=2
                        │                   │
                        ├─► AlloyDB Express (PostgreSQL 18, scale-to-zero,
                        │     public DNS + Python language connector + IAM auth)
                        ├─► Vertex AI: gemini-3.5-flash-lite → fallback gemini-3.1-flash-lite
                        ├─► Secret Manager (admin token, OTLP token, relay secret, GitHub PAT)
                        └─► OTLP/HTTPS ──► Grafana Cloud Free
                                           (Mimir metrics · Loki logs · Tempo traces)
                                           dashboards + alert rules
                                                │ alert fires → webhook
                                                ▼
                                     Cloud Run: handover-relay (same image, scale-to-zero)
                                                │ repository_dispatch
                                                ▼
                                     GitHub Actions: responder workflow
                                       └─ headless coding agent + incident-response skill
                                            ├─ read: Grafana Cloud Loki/Tempo/Prometheus APIs
                                            ├─ write: PUT /api/admin/settings (the fix)
                                            ├─ verify: synthetic generation → 201
                                            └─ write: incident issue + incidents/*.md

Also: Cloud Run Job handover-migrate (Alembic upgrade head), executed by CI before deploy.
```

### 6.4 Component decisions

| Layer | Choice | Rationale |
|---|---|---|
| Compute | Cloud Run, 2 services + relay + migrate job | Scale-to-zero, free HTTPS URL, immutable revisions → instant rollback |
| Database | **AlloyDB Express** (preview, PG18) | GCP-native serverless Postgres: pauses after 15 min idle, $0 compute while paused, billed per second when active; keeps the course's SQLAlchemy/Alembic/Postgres flow intact |
| Registry | Artifact Registry + cleanup policy | Build once, promote the identical image |
| CI auth | Workload Identity Federation | No long-lived cloud keys in GitHub |
| Observability | Grafana Cloud Free (managed Prometheus/Loki/Tempo/Grafana) | Same stack the course teaches; the course explicitly permits a managed OTel-compatible service; removes the observability VM |
| Responder trigger | Grafana webhook → relay → `repository_dispatch` → Actions | Event-driven, $0 on a public repo, no polling VM |
| LLM | `gemini-3.5-flash-lite` via `google-genai` (Vertex AI mode) | Latest Flash-Lite; runtime service account auth → no API keys |

**AlloyDB Express facts that constrain the design**
- Regions: `europe-west2` is the only EU region; others are `us-west1` and Asia-Pacific. Everything is deployed in `europe-west2`.
- 1 vCPU (4 GB) or 2 vCPU (8 GB); 1 vCPU = 1 compute unit. Storage auto-grows to 20 GB max, billed on used bytes.
- No public IP: connectivity via **public DNS endpoint** or Private Service Connect; AlloyDB Auth Proxy and language connectors (Python) are supported.
- No Terraform support → infrastructure is created with **gcloud scripts** in `infra/`.
- Preview: no SLA, no HA, no automated backups. Reproducibility comes from Alembic + `scripts/seed_demo.py`.
- Pricing: $0.115/CU-hour active (per-second billing), $0.00 while paused, $0.30/GB-month used storage. Free tier: 50 CU + 2 GB per month per billing account for the first 12 months.

### 6.5 Cold-start policy (explicit trade-off)
- Cloud Run cold start ≈ 1–3 s; AlloyDB Express resume ≈ 20 s after the 15-minute idle pause.
- Frontend shows: *"Waking up the database — the first request after a break can take ~20 s."*
- SQLAlchemy: `pool_pre_ping=True`, short `pool_recycle`, so connections stale after a DB pause recover cleanly.
- CI smoke checks, Playwright first hit, and the responder's synthetic check retry with backoff up to 90 s.
- This trade-off is documented in the README as a deliberate cost decision.

---

## 7. Data model (PostgreSQL 18, Alembic migrations)

```sql
CREATE TABLE events (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  shift_key   TEXT NOT NULL,
  machine     TEXT NOT NULL,
  category    TEXT NOT NULL CHECK (category IN ('downtime','quality','safety','info')),
  note        TEXT NOT NULL CHECK (length(note) BETWEEN 1 AND 2000),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_events_shift ON events(shift_key, created_at);

CREATE TABLE reports (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  shift_key    TEXT NOT NULL,
  version      INT  NOT NULL,
  summary      TEXT NOT NULL,
  open_actions JSONB NOT NULL,
  safety_notes JSONB NOT NULL,
  model_used   TEXT NOT NULL,
  event_count  INT  NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (shift_key, version)
);

CREATE TABLE app_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- seed: active_model='gemini-3.5-flash-lite', fallback_model='gemini-3.1-flash-lite'
```

- Settings are read **per request** (no cache) so an admin/responder change takes effect immediately.
- Version race: on `UNIQUE(shift_key, version)` conflict, re-read max version and retry once.

---

## 8. API contract (`openapi.yaml` is generated from the frontend services layer)

| Method & path | Request | Success | Errors |
|---|---|---|---|
| `GET /api/healthz` | — | 200 `{status, version, environment}` (no DB access) | — |
| `POST /api/events` | `{shift_key, machine, category, note}` | 201 `Event` | 422 |
| `GET /api/events?shift_key=` | — | 200 `[Event]` | 422 |
| `DELETE /api/events/{id}` | — | 204 | 404 |
| `POST /api/reports/generate` | `{shift_key}` | 201 `Report` | 422 no events · 429 rate limited · 502 generation_failed |
| `GET /api/reports?shift_key=&limit=` | — | 200 `[ReportSummary]` | — |
| `GET /api/reports/{id}` | — | 200 `Report` | 404 |
| `GET /api/admin/settings` | Bearer admin token | 200 `{active_model, fallback_model}` | 401 |
| `PUT /api/admin/settings` | `{active_model?, fallback_model?}` | 200 | 401 · 422 |

```
Event   {id, shift_key, machine, category, note, created_at}
Report  {id, shift_key, version, summary,
         open_actions: [{action, owner, priority: high|medium|low}],
         safety_notes: [string], model_used, event_count, created_at}
Error   RFC 9457 problem+json {type, title, status, detail, trace_id}
```

**Admin model validation is pattern-only (non-empty string), deliberately not an allowlist** —
otherwise the retired-model incident could not be injected. Model existence is discovered at
call time, which is exactly the realistic failure being simulated.

---

## 9. GenAI design

- SDK: `google-genai` in Vertex AI mode (`vertexai=True, project=…, location=…`).
  Auth: Cloud Run runtime service account (local: Application Default Credentials). **No API keys.**
- Primary `gemini-3.5-flash-lite`, `thinking_level="low"`, `temperature=0.2`,
  `max_output_tokens=2048`, timeout 20 s. Fallback `gemini-3.1-flash-lite`.
- Structured output: `response_mime_type="application/json"` + `response_json_schema`
  generated from the Pydantic `ReportContent` model. Pydantic validation gates every DB write.

**System prompt** (`backend/app/llm/prompt.py`, version-controlled):

```
You are a shift handover assistant for a manufacturing plant.
From the raw shift events, produce a handover for the incoming shift lead.
Rules:
- Use only facts present in the events. Never invent machines, numbers, or causes.
- summary: max 5 sentences, most severe first (safety > downtime > quality > info).
- open_actions: only unfinished, concrete actions. owner = the role named in the events,
  otherwise "Shift lead". priority reflects urgency.
- safety_notes: every safety-category event must be represented here.
- If information is missing, state that explicitly instead of guessing.
Return JSON matching the provided schema.
```

User content: `shift_key` + events as compact JSON lines (time, machine, category, note).

**Failure policy**

| Failure | Behavior |
|---|---|
| Model not found / retired (404/400) | Immediately try fallback once |
| Timeout / 429 / 5xx | Try fallback once |
| Schema validation failure | Try fallback once |
| Fallback also fails | 502 problem+json, error metric, no DB write, log with `trace_id` |

**Cost:** ~30 events ≈ 1.5k input + 500 output tokens ≈ **$0.002 per report**.

**Test double:** `LLM_BACKEND=vertex|fake`. The fake returns a deterministic valid report and
raises `ModelNotFound` when `active_model` is not in its known list — so CI exercises the real
fallback logic and the error path without API calls, cost, or flakiness.

---

## 10. Frontend design

- React + TypeScript + Vite. **All backend calls centralised in one services layer** with a
  mock implementation (`VITE_API_MODE=mock|real`), so the app runs before the backend exists.
- Pages: **Shift Board** (shift selector, event list, add-event form, Generate button, latest
  report panel), **Report History**, **Report Detail**.
- Components: `ShiftSelector`, `EventForm`, `EventList`, `GenerateButton`, `ReportView`, `ErrorToast`.
- Cold-start-aware loading state; error toast surfaces `trace_id` from the problem+json body.
- Render report text as text (React default escaping). **Never** `dangerouslySetInnerHTML`.
- Tests: Vitest + React Testing Library (form validation, report sections, error toast, mock contract).

---

## 11. Backend design

```
backend/app/
  main.py            # app factory, static serving, OTel init, force_flush middleware
  config.py          # pydantic-settings
  routers/           # events.py reports.py admin.py health.py
  services/handover.py  # load events → prompt → LLM → fallback → validate → save
  llm/               # client.py (vertex|fake) prompt.py schema.py
  db/                # models.py session.py repo.py + alembic/
  settings_store.py  # app_settings read/write
  telemetry.py       # OTel providers, structlog, metric handles, PII filter
```

FastAPI + SQLAlchemy + Alembic, dependency management with `uv`.
Database URL configurable; SQLite locally, Postgres 18 in Compose and in the cloud.

---

## 12. Testing strategy

| Level | Tool | Scope | LLM |
|---|---|---|---|
| Unit | pytest | prompt builder, schema gate, fallback decision logic, settings validation, telemetry PII filter | fake |
| Integration | pytest + Compose | API→Postgres flows, generation, 422/502 paths, version increment, admin auth | fake (honors settings → real fallback path) |
| Frontend | Vitest + RTL | components + mock service contract | mock |
| E2E | Playwright + Compose (`e2e/`) | log 3 events → generate → verify sections → reload → history → error path via bad model setting | fake |
| Smoke | script post-deploy | `/healthz` + one real generation on dev | **real Vertex** |

Single commands: `make test` (unit + integration + frontend), `make e2e`, `make run`.

---

## 13. Containerization

- Two-stage Dockerfile: Node builds the frontend → Python image copies `dist/`; FastAPI serves it.
  **One container** for the whole app.
- `docker-compose.yaml`: app + `postgres:18` with healthcheck and a named volume.
- `observability/` is a **separate** Compose project (OTel Collector, Prometheus, Loki, Tempo,
  Grafana) for local development, matching the course; production uses Grafana Cloud.

---

## 14. GCP infrastructure (`infra/`, gcloud scripts — no Terraform)

Resources:
1. Artifact Registry repo `handover` + cleanup policy (keep last 5 tags, purge untagged > 7 days).
2. WIF pool + provider restricted to this repository.
3. Service accounts: **deployer** (Run Admin, AR Writer, SA User) and **runtime**
   (AlloyDB Client + Database User, Vertex AI User, Secret Accessor).
4. Secret Manager: admin token, Grafana OTLP token, relay shared secret, GitHub PAT.
5. AlloyDB Express cluster + 1 vCPU instance in `europe-west2`, IAM database auth, public DNS endpoint.
6. Cloud Run: `handover-dev`, `handover-prod`, `handover-relay` (same image, command override).
7. Cloud Run Job `handover-migrate` (Alembic `upgrade head`).

Deploy flags: `--min-instances=0 --max-instances=2 --cpu=1 --memory=512Mi --timeout=120`.

**Connectivity:** AlloyDB Python language connector over the public DNS endpoint with IAM
authentication — no VPC required, no DB password in env vars. Fallback if the connector path
fails: Private Service Connect + Direct VPC egress.

**Migrations cannot run from the GitHub runner** (no public IP, dynamic runner IPs). CI executes
the `handover-migrate` Cloud Run Job with `--wait` before shifting traffic to a new revision.

---

## 15. CI/CD

| Workflow | Trigger | Steps |
|---|---|---|
| `ci.yml` | pull request | pytest unit ∥ Vitest → build Compose → integration + Playwright e2e (`LLM_BACKEND=fake`) |
| `deploy-dev.yml` | push to `main` | WIF auth → build image, tag `YYYYMMDD-HHMMSS-<shortsha>` → push to AR → run migrate job (`--wait`) → deploy to `handover-dev` → healthz + real-Vertex smoke → tag in job summary |
| `promote-prod.yml` | manual dispatch, GitHub `production` environment with required reviewer | read image tag currently on dev → migrate job → deploy **same image** to `handover-prod` → smoke |
| `rollback.yml` | manual dispatch, input = revision | `gcloud run services update-traffic handover-prod --to-revisions=<prev>=100` → health check |
| `responder.yml` | `repository_dispatch: [grafana-alert]` | see §18 |

Build and deploy are separate stages; promotion reuses the identical artifact.
Rollback is a seconds-long traffic switch between immutable Cloud Run revisions — record it once.

---

## 16. Observability

Resource attributes on all signals: `service.name=handover`,
`deployment.environment=dev|prod`, `service.version=<image tag>`.

**Metrics**

| Name | Type | Labels |
|---|---|---|
| `handover_events_created_total` | counter | env, version |
| `handover_reports_generated_total` | counter | outcome=`success\|error`, model |
| `handover_generation_duration_seconds` | histogram | outcome |
| `handover_fallback_used_total` | counter | reason |
| FastAPI RED metrics | auto-instrumentation | route, status |

**Cardinality rule:** never label metrics with `shift_key`, `report_id`, or user input
(Grafana free tier caps at 10k active series).

**Trace spans:** `http.server` → `handover.load_events` → `handover.build_prompt` →
`gemini.generate` (attrs: model, token usage, `handover.is_fallback`) → `handover.validate` → `db.save_report`.

**Logs:** structlog JSON `{timestamp, level, msg, trace_id, span_id, env, version, shift_key,
report_id, outcome, model, duration_ms}`.

**Privacy rule (graded):** event notes, report text, tokens and credentials never enter telemetry.
Enforced by a unit test on the log processor and documented in `_docs/telemetry.md`.
This also means the on-call agent never reads untrusted user text (prompt-injection defense).

**Cloud Run caveat:** CPU is throttled between requests → a middleware calls `force_flush()`
on tracer/meter/logger providers at the end of every request so nothing is stranded.

**Transport:** OTLP/HTTPS directly to Grafana Cloud (instance ID + token from Secret Manager).
Free tier: 10k active series, 50 GB logs / 50 GB traces, 3 users, 14-day retention.

**Dashboard** (provisioned as code in `observability/provisioning/`): success/error rate by
env+version, p50/p95 generation latency, fallback usage, events created, error logs with
clickable trace IDs.

---

## 17. Alerting and incident injection

**Alert: user impact, not CPU.**

```promql
sum(rate(handover_reports_generated_total{outcome="error",environment="prod"}[10m]))
/
sum(rate(handover_reports_generated_total{environment="prod"}[10m])) > 0.2
```

Guard: ≥ 5 attempts in the window. `for: 5m`, evaluation interval 1m → time-to-alert ≈ 6–11 min.
Annotations: *"Shift leads cannot generate handovers — the incoming shift starts blind"*,
owner, service, environment, version, dashboard URL, runbook URL.
Optional second alert: p95 generation latency > 20 s for 10 m.

**Injection:** `scripts/inject-incident.sh` sets `active_model=gemini-2.5-flash-lite`
(a model genuinely retired in October 2026 — realistic "someone pinned a deprecated model").
**Traffic is required:** `scripts/generate_traffic.sh` loops generation requests so the
≥ 5 attempts / 10 min threshold is actually crossed.
`scripts/restore-settings.sh` is the break-glass reset for the live demo.

---

## 18. On-call responder

**Why a relay exists:** Grafana's webhook posts its own fixed alert JSON, but GitHub's
`repository_dispatch` requires `{"event_type": ..., "client_payload": ...}`. Direct wiring fails.
The relay is a ~40-line FastAPI module shipped in the **same image**, deployed as
`handover-relay` (scale-to-zero, $0). If your Grafana version supports custom webhook payload
templating, the relay may be dropped — verify in the Phase 0.5 spike, do not assume.

Flow:
1. Grafana alert → webhook with header `X-Webhook-Token` → relay validates the shared secret,
   dedupes by alert fingerprint (30-min cooldown), reshapes the payload, POSTs:
   ```json
   {"event_type":"grafana-alert",
    "client_payload":{"alertname":"...","fingerprint":"...","status":"firing",
                      "environment":"prod","dashboard_url":"...","runbook_url":"..."}}
   ```
2. `responder.yml` (`concurrency: incident-response`, no cancel-in-progress) checks out the repo
   and runs a headless coding agent with the `incident-response` skill and the alert payload.
3. **Bounded credentials:** read-only Grafana Cloud token + app `ADMIN_TOKEN`.
   **No GCP credentials at all** — the agent cannot touch infrastructure.
4. Runbook decision tree (`_docs/runbook.md`):
   - Query Loki for generation errors in the alert window → error class + `trace_id` → confirm in Tempo.
   - `ModelNotFound` / retired model → `GET /api/admin/settings` → `PUT active_model = fallback_model` → verify.
   - Persistent 429 quota → switch to fallback; if both exhausted → escalate.
   - DB / infra errors → **escalate only** (open issue, change nothing).
   - Real code bug → smallest fix + tests on a branch → **PR, never auto-merge**.
   - False positive → document reasoning, change nothing.
5. **Verification:** `scripts/synthetic_check.sh` seeds a demo event, generates a report, expects
   201, **retrying with backoff up to 90 s** (AlloyDB resume + Cloud Run cold start). Without this
   the agent would misread a successful fix as still broken.
6. **Output:** `incidents/YYYYMMDD-HHMM-<slug>.md` (timeline, user impact = failed generation count,
   root cause, trace links, action, verification, follow-ups) + a GitHub issue; closed with a
   resolution comment once the alert resolves.
7. `--dry-run` mode replays a recorded alert payload so the loop can be iterated without waiting
   for a real alert each time.

---

## 19. Agent team, tracker and process

### 19.1 Tracker (graded criterion)
- **Public GitHub repo + public Projects board.** Board columns: `Backlog → Groomed → In Progress → QA → Done`.
- Issues are created from the raw backlog in §25. **GitHub Issues are the canonical backlog**;
  `_docs/tasks.md` is temporary scaffolding and is deleted once issues exist.
- Labels: `phase-0…phase-7`, `area:frontend|backend|infra|observability|agents`, `type:feature|test|chore|docs`, `priority`.
- Every issue links back to the relevant `plan.md` section and acceptance-criteria IDs.

### 19.2 Roles (`_docs/team/`)
- **PM (`pm.md`)** — grooms a raw issue before anyone implements it: rewrites it using
  `_docs/task-template.md` (**Goal / Acceptance criteria / Out of scope / Constraints**), makes
  every criterion checkable ("someone can point at the screen and say yes or no"), adds edge
  cases, files follow-up issues for anything moved out of scope. **Writes no code.**
- **Software engineer (`software-engineer.md`)** — implements one groomed issue against its
  acceptance criteria, stays inside the named constraints, writes tests, commits regularly
  (`feat: … (#12)`), comments a summary on the issue, **does not close it**.
- **QA (`qa-engineer.md`)** — fresh session, never sees the implementer's context. Checks each
  criterion against the running system, runs the tests and names them, posts a verdict comment
  starting with `PASS` or `FAIL` with a per-criterion checklist. **Fixes nothing.**
- **On-call (`on-call.md`)** — the responder role in §18.

### 19.3 Process (`_docs/process.md`)
`PM → SWE → QA`, each in a fresh context; `FAIL` loops back to SWE; `PASS` → orchestrator closes
the issue and moves the card. The main session is the **orchestrator** and never implements
issues itself. Optional: run independent issues in parallel in isolated **git worktrees**.

Example prompts:
```
You're the PM agent. Your role is _docs/team/pm.md. Groom issue #12 against plan.md.
Launch a software-engineer subagent for #12. Follow _docs/process.md.
Start a QA engineer subagent. Role: _docs/team/qa-engineer.md. Review work for #12.
```

### 19.4 Evidence that agents used the tracker (what reviewers must see)
Groomed issues with the four sections · SWE summary comments · QA `PASS`/`FAIL` verdict comments ·
commits and PRs referencing `#issue` · board movement · `_docs/ai-workflow.md` describing tools,
prompts and session workflow.

### 19.5 Skills and subagents (`.agents/`)
- `skills/implement-task/SKILL.md`, `skills/incident-response/SKILL.md`,
  `skills/deploy-gcp/SKILL.md`, `skills/release/SKILL.md` — frontmatter with `name` + `description`.
- `agents/{pm,software-engineer,qa-engineer,on-call}.md` pointing at `_docs/team/*`.
- Symlink `.claude/skills/` → `.agents/skills/` and `.claude/agents/` → `.agents/agents/`.
- Create skills by doing the task once with the agent, then: *"Save this as a skill, keep my
  corrections, project-specific."*

---

## 20. Repository layout

```
handover-copilot/
├── plan.md                      # ← this file: canonical specification
├── AGENTS.md                    # commands + rules + links to plan.md and _docs/*
├── CLAUDE.md                    # single line: @AGENTS.md
├── openapi.yaml  Makefile  Dockerfile  docker-compose.yaml
├── backend/                     # FastAPI app + tests + alembic
├── frontend/                    # React+TS+Vite, services layer (mock|real)
├── e2e/                         # Playwright
├── observability/               # local compose + provisioning (dashboards, alert rules as code)
├── relay/                       # webhook → repository_dispatch (shipped in the same image)
├── scripts/                     # inject-incident.sh generate_traffic.sh restore-settings.sh
│                                # synthetic_check.sh seed_demo.py cleanup-gcp.sh
├── infra/                       # gcloud scripts: AR, WIF, SAs, secrets, AlloyDB, Run, jobs
├── _docs/
│   ├── process.md  task-template.md  decisions.md  telemetry.md  runbook.md  ai-workflow.md
│   └── team/{pm,software-engineer,qa-engineer,on-call}.md
├── .agents/{skills,agents}/
├── incidents/                   # responder-written postmortems
└── .github/workflows/{ci,deploy-dev,promote-prod,rollback,responder}.yml
```

---

## 21. Configuration

| Variable | Where | Purpose |
|---|---|---|
| `APP_ENV`, `APP_VERSION` | Cloud Run env (version = image tag) | telemetry dimensions |
| `DATABASE_URL` / AlloyDB instance + IAM user | env / Secret Manager | persistence |
| `GCP_PROJECT`, `GCP_LOCATION` | env | Vertex client |
| `ADMIN_TOKEN` | Secret Manager | admin API |
| `LLM_BACKEND` | `vertex` in dev/prod, `fake` in CI | test double switch |
| `LLM_TIMEOUT_S=20` | env | generation budget |
| `OTEL_EXPORTER_OTLP_ENDPOINT` / `_HEADERS` | env + secret | Grafana Cloud export |
| `RELAY_WEBHOOK_TOKEN`, `GITHUB_DISPATCH_PAT` | Secret Manager | relay auth + dispatch |
| `VITE_API_MODE` | build time | mock ⇄ real services layer |

---

## 22. Security and abuse guards

The demo is public and unauthenticated, so it must not become an open LLM proxy:
- Per-IP rate limit on `/api/reports/generate` (e.g. 10/hour) → `429`.
- Input caps: note ≤ 2000 chars, ≤ 200 events per shift (bounds prompt size and cost).
- `--max-instances=2` on Cloud Run; **Vertex AI per-day request quota override** (the hard spend cap).
- Admin token: long random value in Secret Manager, constant-time comparison.
- Prompt injection: untrusted event notes → structured-output schema gate + React text rendering;
  telemetry contains no user text, so the responder cannot be injected through event notes.
- Grafana tokens scoped: write-only for the app, read-only for the responder.
- WIF instead of stored cloud keys; responder holds **no** GCP credentials.

---

## 23. Cost model

| Service | Billing model | Expected monthly |
|---|---|---|
| Cloud Run (dev, prod, relay, jobs) | per request + vCPU/RAM-seconds; free tier 240k vCPU-s + 450k GiB-s, 2M requests | $0 |
| AlloyDB Express (1 vCPU = 1 CU) | $0.115/CU-hr active, $0 paused, $0.30/GB-mo used; free 50 CU + 2 GB/mo (first 12 months per billing account) | $0 (≈$1–2 if the free tier does not apply) |
| Vertex AI Flash-Lite | per token (~$0.002/report) | < $1 |
| Grafana Cloud Free | capped free tier | $0 |
| Artifact Registry | $0.10/GB-mo, cleanup keeps ~1 GB | ~$0.10–0.30 |
| Secret Manager | $0.06/secret-version/mo | ~$0.20 |
| GitHub Actions | free on public repos | $0 |

Guards: GCP budget alert at $10, Vertex daily quota override, AR cleanup policy, Grafana hard caps.
**Verify free-tier eligibility in Phase 0.5** — the AlloyDB allowance is per billing account for
its first 12 months.

---

## 24. Delivery plan (~20 hours)

| Phase | Hours | Deliverable / definition of done |
|---|---|---|
| 0 — Spec & agent setup | 1.5 | `plan.md` committed; `AGENTS.md`, `_docs/process.md`, `_docs/task-template.md`, team docs; public repo + board; issues created from §25; issue #1 (scaffold + passing test) done |
| 0.5 — De-risking spikes | 1 | Four checks logged in `_docs/decisions.md`: (a) AlloyDB Express created + connected via connector/IAM, free-tier eligibility; (b) one structured-output call to `gemini-3.5-flash-lite` in the chosen region; (c) Grafana Cloud OTLP hello-world visible; (d) Grafana test alert reaches a request bin |
| 1 — Frontend first | 3 | React app with mock services layer, 3 pages, cold-start UX, `openapi.yaml` derived, Vitest green |
| 2 — Backend + GenAI + DB | 3 | FastAPI from contract, in-memory → SQLite → Postgres 18, Alembic, LLM service with fallback, admin API, unit + integration green |
| 3 — Containerize + e2e | 2 | Two-stage Dockerfile, Compose full stack, Playwright e2e, `make run/test/e2e` |
| 4 — Infra + CI/CD | 3 | gcloud infra scripts, WIF, migrate job, all four workflows, dev deployed, prod promoted with approval, rollback recorded, cost guards set |
| 5 — Observability + alert | 2 | OTel + force_flush, PII test, dashboard + alert as code, traffic script, trace-ID correlation demonstrated |
| 6 — Responder + incident | 2.5 | Relay + dispatch + responder workflow, runbook, skill, dry-run, **live incident demo recorded**, agent-written incident report committed |
| 7 — Submission polish | 2 | README + rubric map + reviewer path, seed data, `ai-workflow.md`, Grafana viewer access, cleanup script tested, peer reviews scheduled |

**Cut order if behind:** git worktrees → second latency alert → nightly `pg_dump` job →
contract test → history filtering.
**Never cut:** incident video, QA verdicts in issues, English docs, the three peer reviews.

---

## 25. Initial backlog (raw — the PM agent grooms each into an issue)

Create one GitHub issue per row, in order, with the listed labels and a link to the `plan.md`
section. They are intentionally raw: **PM turns them into Goal / Acceptance criteria /
Out of scope / Constraints before implementation.**

| # | Title | Goal | Phase | plan.md |
|---|---|---|---|---|
| 1 | Scaffold repo with a passing test | Empty backend + frontend skeleton, `make test` green | 0 | §20 |
| 2 | Tracker + agent context setup | Board, labels, `AGENTS.md`, `CLAUDE.md`, process/team docs | 0 | §19 |
| 3 | Spike: AlloyDB Express connectivity | Create cluster, connect via Python connector + IAM, record eligibility | 0.5 | §14 |
| 4 | Spike: Gemini structured output | One validated `ReportContent` call in the chosen region | 0.5 | §9 |
| 5 | Spike: Grafana Cloud OTLP + test alert | Metric/log/trace visible; test webhook received | 0.5 | §16 |
| 6 | Frontend prototype with mock services layer | 3 pages, centralised services + mock, cold-start UX | 1 | §10 |
| 7 | Derive `openapi.yaml` | Contract matches the services layer exactly | 1 | §8 |
| 8 | Frontend component tests | Vitest + RTL for form, report view, error toast | 1 | §12 |
| 9 | FastAPI from contract (in-memory) | All endpoints, seeded data, problem+json errors | 2 | §8, §11 |
| 10 | Persistence: SQLite → Postgres 18 + Alembic | DB-agnostic SQLAlchemy, migrations, restart-safe | 2 | §7 |
| 11 | Gemini service with structured output + fallback | `vertex\|fake`, schema gate, timeout, fallback policy | 2 | §9 |
| 12 | Admin settings API | Bearer auth, pattern-only validation, effective next request | 2 | §8 |
| 13 | Unit + integration test suite | Fallback logic, schema gate, PII filter, API→DB flows | 2 | §12 |
| 14 | Two-stage Dockerfile + Compose | Single container, `postgres:18`, one-command startup | 3 | §13 |
| 15 | Playwright e2e | Full journey + reload + error path against Compose | 3 | §12 |
| 16 | GCP infra scripts | AR + cleanup, WIF, SAs, secrets, AlloyDB, Run services, migrate job | 4 | §14 |
| 17 | CI workflow | PR: unit ∥ frontend → integration + e2e | 4 | §15 |
| 18 | Deploy-dev workflow | Build/tag/push → migrate job → deploy → smoke | 4 | §15 |
| 19 | Promote-prod + rollback workflows | Manual approval, same image, traffic-switch rollback | 4 | §15 |
| 20 | Cost & abuse guards | Rate limit, input caps, max-instances, Vertex quota, budget alert | 4 | §22, §23 |
| 21 | OTel instrumentation | Metrics, spans, logs, shared trace ID, force_flush, PII test | 5 | §16 |
| 22 | Dashboard + alert as code | Panels, error-ratio alert with annotations, provisioning committed | 5 | §16, §17 |
| 23 | Incident scripts | inject / traffic / restore / synthetic check with backoff | 5 | §17, §18 |
| 24 | Webhook relay | Token check, dedupe, reshape, `repository_dispatch` | 6 | §18 |
| 25 | Responder workflow + runbook + skill | Headless agent, bounded creds, decision tree, dry-run | 6 | §18 |
| 26 | Live incident demo + report | Record inject→alert→fix→verify; commit `incidents/*.md` | 6 | §18 |
| 27 | Skills + subagents | `.agents/` skills and agents, Claude symlinks | 6 | §19.5 |
| 28 | README + reviewer path + docs | Rubric map, seed data, `ai-workflow.md`, Grafana access | 7 | §27 |
| 29 | Cleanup script + final QA pass | `cleanup-gcp.sh` tested; full suite green on clean clone | 7 | §28 |

---

## 26. Known risks and gotchas (already designed around)

1. **Grafana webhook body ≠ GitHub dispatch body** → relay required (§18).
2. **Migrations can't run from the runner** → Cloud Run migrate job (§14).
3. **An alert needs traffic** → `generate_traffic.sh` is a required artifact (§17).
4. **Public demo = potential open LLM proxy** → rate limit, caps, quota override (§22).
5. **Prompt injection via event notes** → schema gate, text rendering, telemetry without user text (§22).
6. **Admin allowlist would block the incident injection** → pattern-only validation (§8).
7. **AlloyDB free tier is per billing account, first 12 months** → verify in Phase 0.5 (§23).
8. **Preview: no SLA/HA/backups** → migrations + seed script; optional `pg_dump` job; Neon free tier as a zero-code-change fallback.
9. **Cold starts break naive verification** → 90 s backoff in the synthetic check (§18).
10. **CPU throttling strands telemetry** → `force_flush()` middleware (§16).
11. **Metric cardinality** → no per-entity labels (§16).
12. **Timezone semantics of night shifts** → explicit rules (§5).
13. **Reviewer access** → seeded demo shift + Grafana viewer/public dashboard + videos (§27).
14. **Peer reviews are a pass/fail gate** → three reviews, scheduled (§27).

---

## 27. Submission checklist

- [ ] Public repo; English README and docs; public issue board with agent evidence
- [ ] `plan.md` (this file) + `AGENTS.md` linking modular docs; `.agents/` skills and subagents
- [ ] `docker compose up` and `make test` work on a clean clone
- [ ] Public prod URL + seeded demo shift
- [ ] CI on PRs; dev auto-deploy; manual prod promotion; **rollback recorded**
- [ ] Grafana dashboard with trace-ID-correlated metrics/logs/traces, no PII; user-impact alert as code
- [ ] Incident video: inject → alert → agent fix → verification → agent-written report in `incidents/`
- [ ] Cost table + cleanup script (the serverless story is a differentiator — tell it)
- [ ] **Three peer reviews completed**

**Five-minute reviewer path (put this in the README):** open prod URL → seeded demo shift →
click *Generate Handover* → open the public Grafana dashboard → watch the 2–3 min incident video →
watch the 30 s rollback clip → browse the issue board and a QA verdict comment.

---

## 28. Cleanup and re-deployment

After peer review (or between attempts): run `scripts/cleanup-gcp.sh` to delete Cloud Run
services/jobs, the AlloyDB Express cluster, AR images, secrets and the WIF pool; remove the
budget alert. Keep `infra/`, `plan.md`, dashboards/alert provisioning and the videos —
re-deploying for a second attempt then costs minutes, not hours.

---

## 29. Decision log (fill during Phase 0.5)

| Question | Status | Answer |
|---|---|---|
| Frontend UI & styling stack | resolved | Tailwind CSS + shadcn/ui component primitives for industrial high-contrast UX |
| Frontend data-fetching & cache layer | resolved | TanStack Query (`@tanstack/react-query`) over typed services layer |
| Database contingency plan | resolved | Primary: AlloyDB Express; Fallback: Neon serverless PostgreSQL (zero code change via standard `DATABASE_URL`) |
| Is `gemini-3.5-flash-lite` available in `europe-west2`? If not, which Vertex region? | resolved | Tested against live Vertex AI: in `europe-west2` and `us-central1`, `gemini-3.5-flash-lite` returns 404 from regional publisher endpoints. However, in the `global` location (`aiplatform.googleapis.com`), `google/gemini-3.5-flash-lite` and `google/gemini-3.1-flash-lite` are fully available, responsive, and generate reports in ~3.3 seconds. For private/unrestricted data residency, `GCP_LOCATION=global` is selected with `ACTIVE_MODEL=google/gemini-3.5-flash-lite` and `FALLBACK_MODEL=google/gemini-3.1-flash-lite`. (For strict EU residency, `europe-west2` with `gemini-3.5-flash` remains the regional alternative). |
| Does the billing account qualify for the AlloyDB Express free tier? | open | |
| Does the AlloyDB Python connector work from Cloud Run over public DNS with IAM auth? | open | |
| Can Grafana template the webhook body (relay droppable)? | open | |
| Grafana Cloud stack URL + reviewer access mode (viewer user vs public dashboard)? | open | |

---

## 30. Implementation Decisions & Specifications (Backend Phase)

The following architectural and design decisions were made during backend implementation to ensure complete reliability, zero-cost CI, and seamless incident simulation:

1. **Vertex AI Model Naming & Regional Binding**:
   - In `europe-west2`, live testing verified that model `gemini-3.5-flash` is available and responsive for structured outputs.
   - Fallback model is set to `gemini-4-argon`.
   - Simulated incident model: `gemini-2.5-flash-lite` (a retired model) generates an authentic 404/not-found from Vertex AI, cleanly exercising the automated fallback retry logic.
2. **Offline & Test-Double Architecture (`LLM_BACKEND=fake`)**:
   - Full automated test suite (216 tests) runs with `LLM_BACKEND=fake` in ~10 seconds with zero external network calls, zero GCP spend, and 100% deterministic test assertions.
   - OpenTelemetry provider defaults to in-memory span and metric readers when `OTEL_EXPORTER_OTLP_ENDPOINT` is omitted.
   - Injectable `GitHubDispatcher` protocol enables offline webhook relay testing without live calls to GitHub API.
3. **Telemetry Privacy Redaction (AC-11, §16, §22)**:
   - Automated recursive sanitization in both structlog JSON logging and OpenTelemetry span processors blocks or masks user notes, report text, tokens, and authorization credentials as `"[REDACTED]"`.
   - W3C hex `trace_id` is automatically propagated into response headers (`X-Trace-ID`) and RFC 9457 `ProblemDetails.trace_id` payloads.
4. **Webhook Relay Deduplication**:
   - In-memory fingerprint tracking with a 30-minute cooldown window (`RELAY_DEDUPE_COOLDOWN_SECONDS=1800`) prevents webhook storms from repeatedly firing downstream GitHub Actions.
   - Cache pruning automatically cleans up expired entries to prevent memory growth.
5. **Admin Model Name Validation**:
   - Validation on `active_model` and `fallback_model` in `PUT /api/admin/settings` is strictly pattern-based (`^[a-zA-Z0-9._-]+$`, 1–128 characters) and deliberately avoids an allowlist or enum so that deprecated models can be dynamically configured during incident tests.

---

## 13. Dual-Naming Compatibility & Docker Container Serving (Issue #23)

### Decision Context
When running in Docker or standalone production deployments where FastAPI directly serves frontend static files (without the Vite development proxy), discrepancies between OpenAPI camelCase conventions (`shiftKey`, `modelUsed`, `createdAt`, `activeModel`) and FastAPI snake_case schemas (`shift_key`, `model_used`, `created_at`, `active_model`) caused `422 Unprocessable Entity` validation errors on query parameters and request bodies.

### Architecture & Resolution
1. **Pydantic Validation Aliases (`AliasChoices`)**:
   - In `backend/app/schemas/`:
     - `EventCreate.shift_key` supports `validation_alias=AliasChoices("shift_key", "shiftKey")`.
     - `ReportGenerateRequest.shift_key` supports `validation_alias=AliasChoices("shift_key", "shiftKey")`.
     - `AdminSettingsUpdate` supports `validation_alias=AliasChoices("active_model", "activeModel")` and `validation_alias=AliasChoices("fallback_model", "fallbackModel")`.
2. **Query Parameter Dual-Support in Routers**:
   - `GET /api/events` and `GET /api/reports` accept either `shift_key` or `shiftKey` as query parameters.
3. **Pydantic Computed Fields for Dual Serialization**:
   - `EventResponse`, `ReportSummary`, `ReportResponse`, and `AdminSettingsResponse` use `@computed_field` to serialize both camelCase and snake_case properties simultaneously.
4. **Frontend Defensive Normalization**:
   - `eventsApi.ts`, `reportsApi.ts`, and `adminApi.ts` normalize response payloads to ensure safe property access in both development (mock/proxy) and production (Docker direct).

---

## 14. Docker Compose & Integration Test Suite Architecture (Issue #24)

### Decision Context
To enable deterministic local evaluation, production-grade container orchestration, and automated verification of end-to-end deployment behaviors without cloud dependencies or manual intervention, `docker-compose.yaml` and a 7-scenario integration test suite were introduced.

### Architecture & Resolution
1. **Compose v2 Specification (`docker-compose.yaml`)**:
   - Service `app` built from `./Dockerfile` with standard port binding `${PORT:-8000}:8000`.
   - Environment defaults configured for zero-cost offline validation: `APP_ENV=production`, `LLM_BACKEND=fake`, `ADMIN_TOKEN=dev-admin-secret-key-12345`, `RELAY_WEBHOOK_TOKEN=dev-relay-token-secret-123`, `DATABASE_URL=sqlite:///./data/handover.db`.
   - Named Docker volume `handover_data:/app/data` mounted to `/app/data` ensuring SQLite persistence across container lifecycle events (stop/start/restart/recreate).
   - Container healthcheck configured via Python standard library `urllib.request` (`python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/healthz')"`) transitioning container to `healthy` state in environments lacking `curl`.
2. **Database Directory Auto-Creation**:
   - Ensured `/app/data` directory creation in `Dockerfile`, `backend/app/db/session.py`, and `backend/alembic/env.py` so SQLite connection initialization never fails on clean volumes.
3. **Automated Integration Test Suite**:
   - Implemented in `scripts/test_compose_integration.py` (standalone zero-dependency runner) and `backend/tests/test_compose_scenarios.py` (pytest-compatible suite) validating 7 core deployment scenarios:
     - **Scenario 1:** Container boot & static SPA serving (`/api/healthz`, `/` HTML with `<div id="root">`, `/assets/*` bundles, `/reports` and `/reports/:id` SPA routing, `/docs` Swagger UI, `/openapi.json`).
     - **Scenario 2:** Shift events lifecycle & dual-naming compatibility (`POST /api/events` with camelCase/snake_case, `GET /api/events` with `shiftKey`/`shift_key`, 422 ProblemDetails with `traceId`, 204 deletion).
     - **Scenario 3:** Handover report generation & zero-omission gate (422 ProblemDetails on empty shift, 201 generation with executive summary, safety notes, open actions, event count matching, and `X-Trace-ID` header).
     - **Scenario 4:** Version progression & report history (increment to version 2 on new event, descending history list, immutable version 1 snapshot).
     - **Scenario 5:** Dynamic model settings & admin security (401 without Bearer token, GET settings with dual-naming keys, PUT runtime reconfiguration without restart).
     - **Scenario 6:** Database persistence across container restart (`docker compose restart app`, verifying events, reports, snapshots, and updated settings persist).
     - **Scenario 7:** Webhook relay module & incident ingestion (401 on missing/invalid token, 422 on malformed body, non-firing alert ignored, deduplication of firing alerts within cooldown window, incident event creation in shift log).
4. **Automated Orchestration Runners**:
   - `scripts/run-integration-tests.ps1` (Windows PowerShell) and `scripts/run-integration-tests.sh` (POSIX bash) automate building stack via `docker compose up -d --build`, waiting for healthy status, executing test scenarios, testing persistence across restart, and clean teardown via `docker compose down -v`.

---

## 15. Playwright Browser End-to-End Test Suite Architecture (Issue #26)

### Decision Context
To verify full-stack user journeys through an actual browser running against the production container stack (`docker-compose.yaml`), an automated Playwright test suite was introduced in the `e2e/` folder at the repository root.

### Architecture & Resolution
1. **Playwright Configuration (`e2e/playwright.config.ts`)**:
   - Configured with `baseURL: process.env.BASE_URL || 'http://127.0.0.1:8000'`.
   - Uses headless Chromium by default with desktop viewport (1440x900).
   - Single-worker serial execution (`fullyParallel: false`, `workers: 1`) to guarantee deterministic step sequencing.
   - Captures screenshots and W3C trace artifacts on failure (`screenshot: 'only-on-failure'`, `trace: 'retain-on-failure'`).
2. **End-to-End User Journeys (`e2e/handover.spec.ts`)**:
   - **Journey 1: Navigation & Initial Render**: Verifies application title, industrial edition badge, shift key indicator format `YYYY-MM-DD-(early|late|night)`, and dynamic data reloading on shift toggles.
   - **Journey 2: Event Logging & Real-Time List Updates**: Verifies client-side validation blocking empty submissions without network requests, valid form submission, input clearing, transient success feedback, immediate DOM list updates, and category badge styling (amber for downtime, red for safety).
   - **Journey 3: Handover Report Generation & Rendering**: Verifies the zero-events disabled state with helper message, generation loading state with animated spinner, and report card rendering containing metadata bar (version, shift key, event count, model used), synthesized Executive Summary, Safety Notes section, and Open Actions table with priority badges (`high`/`medium`/`low`), action descriptions, and assigned owners.
   - **Journey 4: Report History Navigation & Version Snapshots**: Verifies tab switching to Report History, listing of generated reports with version and timestamp, inspection of immutable past snapshots, and version incrementing upon regeneration ("Version 1" -> "Version 2").
   - **Journey 5: Admin & Model Settings View**: Verifies Admin Settings header trigger, RFC 9457 error banner (401 Unauthorized) on invalid token keeping modal locked, unlocking with valid token `dev-admin-secret-key-12345`, model configuration cards, regex pattern validation on model identifiers, and successful saving with transient confirmation.
3. **Orchestration Runner Scripts**:
   - `scripts/run-e2e-tests.ps1` (PowerShell) and `scripts/run-e2e-tests.sh` (Bash) automate detecting or starting the container stack, waiting for healthy status via `/api/healthz`, running the Playwright test suite, and cleaning up container resources via `docker compose down -v`.
   - Accessible via root `npm run test:e2e` and frontend `npm run test:e2e`.

---

## 16. Cloud Run Deployment, Database Persistence & CI/CD Architecture (Issue #25)

### Decision Context
Phase 4 deployment transitions the Shift Handover Copilot from local Docker Compose containers to Google Cloud Platform, provisioning immutable serverless compute (`europe-west2`), managed database persistence across scale-to-zero, Secret Manager configuration, live Vertex AI Gemini integration, and automated GitHub Actions CI/CD workflows.

### Architecture & Resolution
1. **Cloud Run Serverless Compute (`europe-west2`)**:
   - `handover-dev`: Development service automatically deployed on every push to `main`.
     - URL: `https://handover-dev-budwggf4rq-nw.a.run.app`
   - `handover-prod`: Production service deployed via promotion of verified dev image artifact with required manual approval gate.
     - URL: `https://handover-prod-budwggf4rq-nw.a.run.app`
   - `handover-relay`: Lightweight webhook-to-dispatch relay service.
     - URL: `https://handover-relay-budwggf4rq-nw.a.run.app`
   - Runtime configuration: `--min-instances=0 --max-instances=2 --cpu=1 --memory=512Mi --timeout=120`, runtime service account `handover-runtime@boxwood-scope-292916.iam.gserviceaccount.com`.
2. **Database Persistence Across Scale-to-Zero**:
   - Managed PostgreSQL database `handover-db` provisioned in `europe-west2` with database `handover`.
   - Connected via Cloud Run native Cloud SQL Unix socket `/cloudsql/boxwood-scope-292916:europe-west2:handover-db` with connection string stored securely in Secret Manager (`DATABASE_URL`).
   - `handover-migrate` Cloud Run Job applies Alembic migrations (`uv run alembic upgrade head`) with `--wait` prior to shifting traffic to any new container revision.
3. **Artifact Registry & Tag Management**:
   - Repository `handover` in `europe-west2` with tag immutability and cleanup policy keeping the last 5 tags and purging untagged images older than 7 days.
4. **Secret Manager Security**:
   - Centralized secrets (`ADMIN_TOKEN`, `RELAY_WEBHOOK_TOKEN`, `DATABASE_URL`, `GITHUB_DISPATCH_PAT`) mounted into Cloud Run container environments via `secretAccessor` IAM binding on `handover-runtime`.
5. **Live Vertex AI Gemini Integration**:
   - Operational in production using `LLM_BACKEND=vertex`, `GCP_PROJECT=boxwood-scope-292916`, `GCP_LOCATION=global`, `ACTIVE_MODEL=google/gemini-3.5-flash-lite`, `FALLBACK_MODEL=google/gemini-3.1-flash-lite`.
   - Verified live report synthesis in ~1.3–2.1s with structured output schema validation.
6. **Automated CI/CD Workflows (`.github/workflows/`)**:
   - `ci.yml`: Pull request quality gate running unit, integration, and Playwright tests.
   - `deploy-dev.yml`: Push to `main` pipeline authenticating via Workload Identity Federation (WIF), building, tagging, migrating, deploying dev, and verifying `/api/healthz`.
   - `promote-prod.yml`: Production promotion with required GitHub Environment review, reusing the identical tested dev container image artifact.
   - `rollback.yml`: Manual instant traffic shift between Cloud Run revisions (`--to-revisions=<prev>=100`).

---

## 17. Unified GCP CI/CD Pipeline Architecture (Issue #27)

### Decision Context
Issue #27 introduces a unified GitHub Actions CI/CD pipeline (`.github/workflows/gcp-pipeline.yml`) named `GCP CI/CD Pipeline`. It provides an end-to-end automated lifecycle: parallel backend and frontend unit test gates, a fully containerized Docker Compose integration and Playwright browser E2E test gate, followed by passwordless GCP OIDC (Workload Identity Federation) authentication, container image build and push to Google Artifact Registry, Cloud Run database migration execution, deployment to Google Cloud Run (`handover-dev`), and strict post-deployment health validation against `/api/healthz`.

### Architecture & Pipeline Structure
1. **Pipeline Triggers & Permissions (`.github/workflows/gcp-pipeline.yml`)**:
   - Triggers on `push` to branch `main` and manual trigger via `workflow_dispatch` with `target_env` selection (`dev`).
   - Concurrency control via `group: gcp-pipeline-${{ github.ref }}` with `cancel-in-progress: false` to ensure sequential delivery without abrupt aborts.
   - Zero static credentials: uses GitHub OIDC token minting (`id-token: write` and `contents: read`).
2. **Parallel Quality Gates**:
   - `backend-test`: runs on `ubuntu-latest`, installs Python 3.11 and `uv` v5, syncs dev dependencies, and runs `uv run pytest tests` with `LLM_BACKEND=fake` and `APP_ENV=test`.
   - `frontend-test`: runs concurrently in parallel on `ubuntu-latest`, sets up Node.js 22 with npm caching, installs dependencies via `npm ci`, and executes `npm test` (component tests and OpenAPI codegen checks).
3. **Containerized Integration & Playwright E2E Suite (`integration-and-e2e`)**:
   - Depends on `needs: [backend-test, frontend-test]`.
   - Provisions Python 3.11, Node.js 22, and Playwright Chromium browser binaries (`npx playwright install --with-deps chromium`).
   - Builds and starts production multi-stage container stack via `docker compose up -d --build --wait`.
   - Polls `http://127.0.0.1:8000/api/healthz` with retry loop (up to 30 attempts, 2s interval) until healthy.
   - Executes Docker Compose integration test scenarios via `python scripts/test_compose_integration.py --base-url http://127.0.0.1:8000`.
   - Executes browser end-to-end journeys via `npm run test:e2e` with `BASE_URL=http://127.0.0.1:8000`.
   - Guaranteed resource teardown via `docker compose down -v` under `if: always()`.
   - Uploads Playwright traces and failure screenshots as GitHub workflow artifacts under `if: failure()`.
4. **GCP OIDC Authentication, Artifact Registry & Cloud Run Deployment (`deploy-gcp`)**:
   - Depends on `needs: [integration-and-e2e]`.
   - Authenticates via Workload Identity Federation using `google-github-actions/auth@v2`.
   - Builds and tags multi-stage container image `${TIMESTAMP}-${SHORT_SHA}` and `:latest`, pushing to `europe-west2-docker.pkg.dev/boxwood-scope-292916/handover/app`.
   - Executes Cloud Run migration job `handover-migrate` with `--wait` to ensure database schema compatibility prior to traffic routing.
   - Deploys container image to Cloud Run service `handover-dev` with Cloud SQL connection, Secret Manager bindings, and runtime service account.
5. **Post-Deployment Health Validation (`validate-deploy`)**:
   - Step `id: validate-deploy` resolves live public service URL via `gcloud run services describe`.
   - Polls `${SERVICE_URL}/api/healthz` in a retry loop (12 attempts, 5s interval, 60s max).
   - Validates HTTP 200 and parses JSON payload verifying `status == "ok"`.
   - Publishes deployment metadata and direct links to `$GITHUB_STEP_SUMMARY`.
   - Exits with failure code immediately if the service fails health verification.
6. **Automated Verification Script (`scripts/verify_gcp_pipeline.py`)**:
   - Standalone Python validator verifying YAML syntax, triggers, parallel job execution, sequential dependency chains, Docker Compose / Playwright steps, WIF OIDC setup, health check loop, and zero occurrences of non-target cloud provider references.

---

## 16. Independent Production Environment Infrastructure Copy on GCP (#28)

Established a fully independent, isolated production environment infrastructure copy on GCP alongside the existing development environment to eliminate cross-environment contamination.

### Architecture & Isolation Matrix

| Component | Development (`dev`) | Production (`prod`) | Backwards-Compatible Legacy |
| :--- | :--- | :--- | :--- |
| **AlloyDB Database** | `handover_dev` on cluster `handover-cluster` | `handover_prod` on cluster `handover-cluster` | `postgres` |
| **Secret Manager DB URL** | `DATABASE_URL_DEV` | `DATABASE_URL_PROD` | `DATABASE_URL` (points to dev) |
| **Admin Token Secret** | `ADMIN_TOKEN_DEV` | `ADMIN_TOKEN_PROD` (distinct token) | `ADMIN_TOKEN` |
| **Relay Webhook Secret** | `RELAY_WEBHOOK_TOKEN_DEV` | `RELAY_WEBHOOK_TOKEN_PROD` (distinct token) | `RELAY_WEBHOOK_TOKEN` |
| **Cloud Run Migration Job** | `handover-migrate-dev` (`DATABASE_URL_DEV:latest`) | `handover-migrate-prod` (`DATABASE_URL_PROD:latest`) | `handover-migrate` |
| **Cloud Run Service** | `handover-dev` (`APP_ENV=dev`) | `handover-prod` (`APP_ENV=prod`) | — |
| **Network & Connectivity** | Direct VPC Egress (`--network=default --subnet=default --vpc-egress=private-ranges-only`) to AlloyDB PSC endpoint (`10.154.0.2` via `alloydb-psc-forwarding-rule` and Cloud DNS `alloydb-psc-zone`) | Direct VPC Egress (`--network=default --subnet=default --vpc-egress=private-ranges-only`) to AlloyDB PSC endpoint (`10.154.0.2` via `alloydb-psc-forwarding-rule` and Cloud DNS `alloydb-psc-zone`) | — |

### Verification & Automated Testing
- `scripts/verify_isolated_environments.py` verifies:
  1. Secret Manager isolation and distinct values for `*_DEV` vs `*_PROD`.
  2. Dedicated migration jobs `handover-migrate-dev` and `handover-migrate-prod` with respective secret bindings.
  3. Cloud Run services `handover-dev` and `handover-prod` configured with respective environment variables and secret bindings.
  4. Live `/api/healthz` responding HTTP 200 with matching `environment: dev` and `environment: prod`.
  5. Live data isolation: synthetic events created on dev do NOT appear in prod.
  6. Live auth & admin settings isolation: dev tokens are rejected on prod with 401, and admin setting mutations on dev do not contaminate prod.

---

## 17. Manual Production Promotion Workflow on GitHub Actions (#31)

Established a dedicated, manual promotion workflow (`.github/workflows/promote-prod.yml`) that safely promotes a verified container image artifact from development (`handover-dev`) to production (`handover-prod`).

### Architecture & Promotion Flow

1. **Trigger & Environment Isolation**:
   - Strictly manual trigger via `workflow_dispatch` with an optional `override_image_tag` input (defaults to empty to automatically resolve the currently running, verified image from `handover-dev`).
   - GitHub environment: `production` with URL binding dynamically resolved from the post-deploy smoke check (`steps.smoke-check.outputs.service_url`).
   - Concurrency group: `promote-prod` with `cancel-in-progress: false` to ensure atomic, non-overlapping production promotions.
   - Permissions: `id-token: write` and `contents: read` for zero-static-key Workload Identity Federation (WIF).

2. **Pre-flight Dev Verification**:
   - Dynamically resolves dev service URL via `gcloud run services describe handover-dev`.
   - Polls `GET ${DEV_URL}/api/healthz` (up to 12 retries, 5s interval) and validates HTTP 200 with payload `status: ok` before proceeding.
   - Aborts immediately if dev is unhealthy to protect production from bad builds.

3. **Artifact Resolution (Build Once, Promote Identical Artifact)**:
   - Queries `gcloud run services describe handover-dev --format 'value(spec.template.spec.containers[0].image)'` to extract verified `IMAGE_URI` and `IMAGE_TAG`.
   - Uses `override_image_tag` if explicitly provided by operator.
   - Reuses the identical container image artifact without rebuilding.

4. **Production Database Migration**:
   - Executes `gcloud run jobs execute handover-migrate-prod --region=europe-west2 --project=boxwood-scope-292916 --wait`.
   - Upgrades production AlloyDB schema to `head` prior to traffic routing.
   - Immediately aborts if the migration fails, preventing live production traffic from hitting incompatible code/schema.

5. **Cloud Run Production Deployment**:
   - Deploys the identical artifact to Cloud Run service `handover-prod`.
   - Sets isolated production secrets: `DATABASE_URL=DATABASE_URL_PROD:latest`, `ADMIN_TOKEN=ADMIN_TOKEN_PROD:latest`, `RELAY_WEBHOOK_TOKEN=RELAY_WEBHOOK_TOKEN_PROD:latest`.
   - Sets environment variables: `APP_ENV=prod`, `APP_VERSION=${IMAGE_TAG}`, `GCP_PROJECT=boxwood-scope-292916`, `GCP_LOCATION=global`, `LLM_BACKEND=vertex`, `ACTIVE_MODEL=google/gemini-3.5-flash-lite`, `FALLBACK_MODEL=google/gemini-3.1-flash-lite`, `LLM_TIMEOUT_S=20`.
   - Direct VPC Egress: `--network=default --subnet=default --vpc-egress=private-ranges-only` with `--clear-cloudsql-instances`.
   - Resource limits: `--min-instances=0 --max-instances=2 --cpu=1 --memory=512Mi --timeout=120 --port=8000 --allow-unauthenticated`.

6. **Production Smoke Check & Summary**:
   - Polls `GET ${PROD_URL}/api/healthz` (12 attempts, 5s interval).
   - Validates HTTP 200 and JSON response `status == "ok"` and `environment == "prod"`.
   - Generates promotion summary in `$GITHUB_STEP_SUMMARY` with promoted tag, revision, and URLs.

### Verification & Automated Testing
- `scripts/verify_promote_workflow.py` validates YAML structure, triggers, OIDC credentials, preflight check, dev image resolution, migration job execution, production deployment flags, smoke check assertions, step summary, and zero non-GCP cloud provider references.









## 18. Two-Stage Build & Deploy Pipeline Architecture and Workflow De-duplication (Issues #32 & #33)

To ensure build reproducibility, eliminate duplicate workflow execution, and uphold the "build once, deploy anywhere" principle, the CI/CD pipeline architecture has been refactored into distinct **Build** and **Deploy** stages with immutable container registry tagging:

### 1. Two-Stage CI/CD Pipeline (`.github/workflows/gcp-pipeline.yml`)
- **Stage Separation:**
  1. `build-image`:
     - Executes after automated test gates (`backend-test`, `frontend-test`, `integration-and-e2e`) succeed (`needs: [integration-and-e2e]`).
     - Computes an immutable image tag strictly matching `YYYYMMDD-HHMMSS-shortsha` (e.g., `20261115-132158-889c129`).
     - Authenticates via Workload Identity Federation (WIF) and pushes both the timestamped tag (`${TAG}`) and `:latest` to Google Artifact Registry (`europe-west2-docker.pkg.dev/boxwood-scope-292916/handover/app`).
     - Exports `image_tag` and `image_uri` as job outputs.
  2. `deploy-gcp`:
     - Depends directly on the build job (`needs: [build-image]`).
     - Pulls and deploys the container image `${{ needs.build-image.outputs.image_uri }}` directly without recompiling or rebuilding source code.
     - Executes database schema upgrades against AlloyDB via `gcloud run jobs execute handover-migrate-dev --wait`.
     - Excludes reserved `PORT=8000` from `--set-env-vars` (Cloud Run reserves `PORT` and manages it via `--port=8000`).
     - Performs health smoke validation against `${SERVICE_URL}/api/healthz`.

### 2. Workflow Trigger De-duplication
- **Single Automated Pipeline on `main`:**
  - Automated `on: push: branches: [main]` trigger was removed from `.github/workflows/deploy-dev.yml`.
  - `.github/workflows/deploy-dev.yml` now triggers exclusively via manual `workflow_dispatch` (for ad-hoc bypass redeployments).
  - `.github/workflows/gcp-pipeline.yml` is the sole automated CI/CD pipeline triggered on commits to `main`, eliminating duplicate parallel container builds, redundant compute expenses, and Cloud Run deployment race conditions.

### 3. Pipeline Resilience & Test Environment Adaptability (Issue #33)
- **Dynamic Health Check Assertions:**
  - `backend/tests/test_health.py` dynamically evaluates `response.json()["environment"] == get_settings().environment`, allowing unit tests to run cleanly in CI (`APP_ENV=test`) as well as local environments (`APP_ENV=local`).
- **Resilient Service Account Fallback:**
  - `infra/06-cloud-run-migrate-job.sh` enforces safe variable expansion:
    `RUNTIME_EMAIL="${RUNTIME_EMAIL:-${RUNTIME_SERVICE_ACCOUNT:-handover-runtime@${PROJECT_ID}.iam.gserviceaccount.com}}"`
    preventing `unbound variable` errors under bash strict mode (`set -euo pipefail`).


## 19. OpenTelemetry Instrumentation and Local LGTM Observability Stack (Issues #34 & #35)

### 1. Backend OpenTelemetry Instrumentation (#34)
The FastAPI backend is fully instrumented with standard W3C / OpenTelemetry semantic conventions across traces, metrics, root spans, and structured logs:
- **Resource Attributes (`backend/app/telemetry.py`):**
  - `service.name`: Configured from `Settings.service_name` (default `"handover"`, with aliases `OTEL_SERVICE_NAME` and `SERVICE_NAME`).
  - `deployment.environment`: Configured dynamically from `Settings.environment` (`APP_ENV`).
  - `service.version`: Configured dynamically from `Settings.version` (`APP_VERSION`).
- **TracerProvider & MeterProvider:** Both providers attach the unified `Resource` so all exported spans and metrics carry standard resource metadata.
- **Root HTTP Spans (`TelemetryMiddleware`):** Injects `service.name`, `deployment.environment`, and `service.version` onto root `http.server` spans.
- **Structured JSON Logs (`structlog`):** Injects `service`, `service.name`, `env`, and `version` into every log event dictionary.
- **Privacy Filter Preservation:** Zero-PII sanitization and metric cardinality limits remain strictly enforced.

### 2. Isolated Observability Stack in `observability/` (#35)
A standalone Docker Compose project named `handover-observability` is provided in `observability/docker-compose.yml`, completely decoupled from the root application Compose stack:
- **OpenTelemetry Collector Contrib (`otel-collector`):**
  - Ports: `4317` (OTLP gRPC), `4318` (OTLP HTTP), `8889` (Prometheus metrics exporter), `13133` (health check).
  - Pipelines for `traces` (to Tempo via OTLP gRPC), `metrics` (to Prometheus), and `logs` (to Loki).
- **Prometheus (`prometheus`):**
  - Port `9090`, scrapes OpenTelemetry Collector metrics on `otel-collector:8889`.
- **Loki (`loki`):**
  - Port `3100`, standalone filesystem storage for log aggregation.
- **Tempo (`tempo`):**
  - Port `3200` (HTTP query/status) and `4317` (internal OTLP gRPC ingestion), local filesystem block storage.
- **Grafana (`grafana`):**
  - Port `3000`, anonymous admin enabled (`GF_AUTH_ANONYMOUS_ENABLED=true`).
  - Pre-provisioned datasources for Prometheus, Loki, and Tempo.
  - Bidirectional correlation: Tempo `tracesToLogs` navigates from trace spans to correlated Loki logs, and Loki `derivedFields` extracts `trace_id` to jump directly into Tempo traces.
- **Verification Script:** `scripts/verify_observability_stack.py` provides automated schema, port, and live health verification across all 5 services.


## 20. Application Metrics Enrichment and Filtered Grafana Dashboard Panels (Issue #36)

### 1. Metric Enrichment with Environment and Version
All application metrics in `backend/app/telemetry.py` are enriched with `environment` and `version` labels derived dynamically from active application settings (`Settings.environment`, `Settings.version`) while supporting explicit caller overrides:
- `handover_events_created_total`: Labels `env`, `environment`, `version`.
- `handover_reports_generated_total`: Labels `outcome` (`success` | `error`), `model`, `environment`, `version`.
- `handover_generation_duration_seconds`: Histogram duration with labels `outcome`, `environment`, `version`.
- `handover_fallback_used_total`: Counter with labels `reason`, `environment`, `version`.
- `handover_http_requests_total`: Counter tracking all incoming HTTP requests via `TelemetryMiddleware` with labels `method`, `route`, `status_code`, `environment`, `version`.
- **Cardinality Guard:** `validate_metric_attributes` explicitly whitelists `environment`, `env`, and `version` while strictly enforcing rejection of high-cardinality/PII keys (`shift_key`, `report_id`, `machine`, `note`, `notes`, `user_text`, `summary`, tokens).

### 2. Provisioned Grafana Dashboard with Dynamic Multi-Filtering
- **Provisioning Structure:** `observability/dashboards.yaml` defines the Grafana dashboard provider mounting `observability/dashboards/` into `/etc/grafana/provisioning/dashboards/json`.
- **Dashboard Definition:** `observability/dashboards/application-metrics.json` (UID `handover-app-metrics`, title `"Shift Handover - Application Metrics"`).
- **Template Variables:**
  - `$environment`: Multi-select dropdown with options `dev`, `prod`, `local`, and `All` (regex `.*`).
  - `$version`: Multi-select dropdown with options for deployed versions and `All` (regex `.*`).
- **Filtered Panels:**
  1. Handover Reports Generated (Rate / Total, grouped by outcome and model).
  2. Shift Events Created (Rate / Total).
  3. Report Generation Latency (p95 histogram quantile).
  4. Fallback Model Invocations count (grouped by reason).
  5. HTTP Request Throughput & Error Rate (grouped by HTTP status code).
  - All PromQL panel queries strictly filter by `{environment=~"$environment", version=~"$version"}`.
- **Automated Verification:** `scripts/verify_observability_stack.py` validates dashboard syntax, mounts, template variables, PromQL queries, and live endpoint responsiveness.


## 21. Standalone Observability Stack Deployment and Dev/Prod Connection (Issue #37)

### 1. Dedicated Observability Stack Host on GCP
The observability stack is deployed on an independent, dedicated Compute Engine virtual machine instance decoupled from the Cloud Run application stack:
- **VM Instance:** `handover-observability`
- **Location & Network:** Zone `europe-west2-a`, attached to VPC `default` / subnet `default` (`10.154.0.0/20`).
- **Network Interfaces:**
  - **Internal IP:** `10.154.0.3` (accessible directly by Cloud Run services via Direct VPC Egress).
  - **External IP:** `34.153.185.34` (accessible for Grafana UI, Prometheus API, and verification).
- **VPC Firewall:** `allow-observability-ingress` configured on network tag `observability-stack` allowing ports `tcp:3000` (Grafana), `4317` & `4318` (OTLP ingestion), `9090` (Prometheus), `3100` (Loki), `3200` (Tempo), and `13133` (Collector health).
- **Provisioning Automation:** `infra/08-observability-stack.sh` and `infra/08-observability-stack.ps1` manage instance creation, startup script execution, and systemd service `observability-stack.service` persistence.
- **Service Endpoints (All HTTP 200 Verified):**
  - OpenTelemetry Collector: `http://34.153.185.34:13133/`
  - Prometheus: `http://34.153.185.34:9090/-/ready`
  - Loki: `http://34.153.185.34:3100/ready`
  - Tempo: `http://34.153.185.34:3200/ready`
  - Grafana: `http://34.153.185.34:3000/api/health`

### 2. Dual Connection: Development and Production
Both serverless Cloud Run environments are configured to export telemetry to the standalone collector over Direct VPC Egress without exposing internal telemetry traffic to the public internet:
- **`handover-dev`:**
  - Cloud Run service configured with `OTEL_EXPORTER_OTLP_ENDPOINT=http://10.154.0.3:4318` and Direct VPC Egress (`--network=default --subnet=default --vpc-egress=private-ranges-only`).
- **`handover-prod`:**
  - Cloud Run service configured with `OTEL_EXPORTER_OTLP_ENDPOINT=http://10.154.0.3:4318` and Direct VPC Egress (`--network=default --subnet=default --vpc-egress=private-ranges-only`).
- **Pipeline & Script Persistence:**
  - `infra/07-cloud-run-services.sh` / `.ps1` and `infra/deploy.sh` / `.ps1` persist `OTEL_EXPORTER_OTLP_ENDPOINT`.
  - `.github/workflows/gcp-pipeline.yml` preserves the endpoint on dev deployments.
  - `.github/workflows/promote-prod.yml` preserves the endpoint on production promotions.
- **Active Telemetry Ingestion & Isolation:**
  - Prometheus TSDB verified storing active series for both `environment="dev"` and `environment="prod"`.
  - Grafana dashboard `Shift Handover - Application Metrics` (`handover-app-metrics`) accessible on `http://34.153.185.34:3000/d/handover-app-metrics` with dynamic `$environment` and `$version` filtering.
- **Automated Verification:** `scripts/verify_deployed_observability.py` provides automated end-to-end verification of VM state, firewall rules, 5 health endpoints, Cloud Run configurations, Prometheus series presence, and Grafana dashboard REST API response.


## 22. Actionable User-Impact Failure Alerts as Code (Issue #38)

To ensure operational awareness reflects real user pain rather than arbitrary infrastructure/hardware spikes, Prometheus alerting rules are defined as code in `observability/alert.rules.yml`:

### 1. User-Impact Alert Definitions
- **`HandoverGenerationFailureRateHigh` (Critical):**
  - **Threshold & Duration:** Report generation failure rate exceeds 20% (> 0.2) over a 10-minute sliding window, sustained for 5 minutes (`for: 5m`).
  - **PromQL Expression:**
    ```promql
    (
      sum by (service, environment, version) (rate(handover_reports_generated_total{outcome="error"}[10m]))
      /
      sum by (service, environment, version) (rate(handover_reports_generated_total[10m]))
    ) > 0.2
    ```
  - **User Impact:** Shift leads cannot generate shift handovers, forcing incoming teams to start blind.
- **`HandoverHttpErrorRateHigh` (Warning):**
  - **Threshold & Duration:** HTTP 5xx server error rate exceeds 10% (> 0.1) over a 5-minute sliding window, sustained for 5 minutes (`for: 5m`).
  - **PromQL Expression:**
    ```promql
    (
      sum by (service, environment, version) (rate(handover_http_requests_total{status_code=~"5.."}[5m]))
      /
      sum by (service, environment, version) (rate(handover_http_requests_total[5m]))
    ) > 0.1
    ```

### 2. Actionable Labels and Annotation Contracts
All alerts maintain dimensional integrity via `sum by (service, environment, version)`:
- **Labels:**
  - `service`: `{{ $labels.service }}` (or `"handover"`)
  - `environment`: `{{ $labels.environment }}` (`dev` or `prod`)
  - `version`: `{{ $labels.version }}`
  - `owner`: `"shift-operations"`
  - `severity`: `"critical"` or `"warning"`
- **Annotations:**
  - `summary`: Human-readable summary of the alert condition.
  - `description`: Explains actual operational consequences on end users.
  - `dashboard_url`: Direct URL to the filtered Grafana application metrics dashboard:
    `http://34.153.185.34:3000/d/handover-app-metrics/shift-handover-application-metrics?var-environment={{ $labels.environment }}&var-version={{ $labels.version }}`
  - `runbook_url`: Link to operational triage guide.

### 3. Provisioning & Live Verification
- **Mount & Config:** `observability/prometheus.yml` specifies `rule_files: ['/etc/prometheus/alert.rules.yml']` and `observability/docker-compose.yml` mounts the file into `/etc/prometheus/alert.rules.yml:ro`.
- **Infrastructure Scripts:** `infra/08-observability-stack.sh` and `infra/08-observability-stack.ps1` include `alert.rules.yml` in configuration synchronization and reload Prometheus.
- **Live Deployment Status:** Verified active on `http://34.153.185.34:9090/api/v1/rules` with HTTP 200 `status: "success"` and health `"ok"`.
- **Automated Verification:** `scripts/verify_alerts.py` validates rule syntax, PromQL expressions, threshold/duration constraints, label contracts, annotations, and remote Prometheus API loading.


## 23. Autonomous On-Call Alert Polling and Headless Agent Dispatch (Issue #39)

To autonomously investigate and remediate operational incidents, an alert polling daemon and headless coding agent dispatcher are implemented in `on-call-engineer/`:

### 1. Architecture and Components
- **`on-call-engineer/poll_alerts.py`**: CLI entrypoint supporting daemon execution (`--interval`, default 60s), single-run poll mode (`--once`), dry-run simulation mode (`--dry-run`), mock alert fixtures (`--alert-file`), custom Prometheus/observability alert API URL (`--alert-url`, default `http://34.153.185.34:9090/api/v1/alerts`), and configurable cooldown (`--cooldown`, default 900s / 15m).
- **`on-call-engineer/poller.py` (`AlertPoller`)**: Queries the observability alert API endpoint (`/api/v1/alerts`), filters exclusively for `state: "firing"` alerts, tracks state transitions (`firing` ↔ `resolved`), deduplicates firing alerts across cycles, enforces cooldown windows, and safely locks against concurrent in-flight agent dispatches for the same alert.
- **`on-call-engineer/dispatcher.py` (`AgentDispatcher`)**: Formats structured incident context and invokes the headless coding agent runner with the mandatory verbatim system prompt:
  ```
  You are the on-call engineer for this repository. An alert just fired.

  Investigate the root cause. Read the code and reproduce the failure.
  If you find a real bug, make the smallest correction, run the backend tests,
  and commit the fix with a clear message.

  If the alert is a false positive, explain why and do not change the code.
  ```
- **`on-call-engineer/models.py`**: Models for structured alert context (`AlertContext`, `AlertTrackedState`) and deterministic SHA-256 fingerprinting based on alert labels.
- **`on-call-engineer/config.py`**: CLI arguments and environment variable fallbacks (`ALERT_API_URL`, `POLL_INTERVAL_SECONDS`, `ALERT_COOLDOWN_SECONDS`, `AGENT_CMD`, `ALERT_MOCK_FILE`).

### 2. Operational Contracts and Error Handling
- **Structured Telemetry Context**: Dispatched agents receive structured context via stdin and environment variables (`ON_CALL_ALERT_NAME`, `ON_CALL_ENVIRONMENT`, `ON_CALL_VERSION`, `ON_CALL_SEVERITY`, `ON_CALL_DASHBOARD_URL`, `ON_CALL_RUNBOOK_URL`, `ON_CALL_FIRING_TIMESTAMP`, `ON_CALL_FINGERPRINT`).
- **Resilience**: Gracefully handles network timeouts, unreachable API endpoints, HTTP non-200 responses, and malformed payloads without process crashes, logging warnings and cleanly retrying on subsequent ticks.
- **Deduplication**: Alerts are tracked by unique label fingerprints with a 15-minute cooldown window, preventing infinite dispatch loops while alerts remain active across poll cycles.

### 3. Verification & Testing
- **Unit & Integration Suite**: `on-call-engineer/tests/test_poller.py` (18 tests covering zero alerts, firing alerts, multiple simultaneous alerts, cooldown windows, unreachable API, malformed payloads, single-run, and dry-run modes).
- **End-to-End Verification**: `scripts/verify_on_call_poller.py` validates all 7 check suites with exit code 0.


## 24. On-Call Incident Resolution, Production Promotion Verification, and Vivid Documentation Styling (Issue #40)

To resolve the active incident, restore continuous integration and deployment pipelines to green status, establish production deployment verification, and elevate repository documentation presentation:

### 1. On-Call Incident Resolution & Verification
- **Root Cause & Surgical Correction**: A typo invoking `remove_prefix` instead of Python's standard `removeprefix` during report summary markdown cleanup in `backend/app/services/handover.py` caused both primary and fallback generation attempts to fail with `502 Bad Gateway`. The surgical correction changed line 86 to `content.summary = content.summary.removeprefix("# ").strip()`.
- **Pipeline Recovery**: Pushing the fix to `origin/main` automatically re-ran `.github/workflows/gcp-pipeline.yml` in GitHub Actions. All jobs passed cleanly (`Frontend Component Tests`, `Backend Unit Tests`, `Compose Integration and Playwright E2E`, `Build and Push Container Image`, and `Deploy to Cloud Run`), turning the CI/CD Pipeline badge green (`passing`).

### 2. Production Promotion Verification
- **Immutable Artifact Promotion**: `.github/workflows/promote-prod.yml` was executed via `workflow_dispatch`. The promotion verified Dev service health, resolved the verified container image tag, executed database migrations on the production database, and promoted the identical container artifact to `handover-prod`, establishing a successful execution history and turning the `Promote to Production` badge green (`passing`).

### 3. Vivid Documentation & UI Architecture
- **Vivid Mermaid Diagrams**: Custom `classDef` definitions, distinct tier palettes (Clients, Cloud Run, Application Container, Databases/AI, Observability Host, On-Call Agent), high-contrast borders, and clear subgraphs are implemented in both `README.md` and `on-call-engineer/README.md`.
- **Visual Production Walkthrough**: Real high-resolution UI captures are embedded under `## 📸 Visual Walkthrough & Production UI`, including Figure 2 showing the real AI-synthesized report (Executive Summary, Safety Notes, and Open Actions table with priority badges) distinct from Figure 1.
- **On-Call Integrity**: Retained `agy` as the default on-call agent runner (`DEFAULT_AGENT_CMD = "agy"` in `on-call-engineer/config.py` and `dispatcher.py`).


