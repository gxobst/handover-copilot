# Testing Guidelines — Shift Handover Copilot

## 1. Principles
- **No Cost / No Flakiness in CI:** Automated tests (unit, integration, frontend, E2E) run strictly with `LLM_BACKEND=fake` or mock services. Never call real Vertex AI in automated test runs.
- **Privacy & Telemetry Verification:** Ensure all tests assert zero PII (notes, user text, secrets) in logs or telemetry spans.
- **Acceptance Criteria Driven:** Every test corresponds to one or more Acceptance Criteria defined in `_docs/plan.md` (§4).

---

## 2. Test Tiers & Tools

| Tier | Tool | Execution Command | Scope |
|---|---|---|---|
| **Backend Unit** | `pytest` | `uv run pytest backend/tests/unit` | Pydantic schemas, prompt generation, settings validation, fallback logic, telemetry PII filter. |
| **Backend Integration** | `pytest` + test DB | `uv run pytest backend/tests/integration` | FastAPI routes, database repository (SQLite/PostgreSQL), Alembic migrations, error handling (RFC 9457 problem+json). |
| **Frontend Unit & Component** | `Vitest` + RTL | `npm test` / `pnpm test` (inside `frontend/`) | Form validation, shift selection, badge rendering, error toasts, mock service contract. |
| **End-to-End (E2E)** | `Playwright` | `npx playwright test` (inside `e2e/`) | Full user journey against Docker Compose: add events -> generate report -> reload -> verify history -> simulate model error fallback. |
| **Smoke (Post-Deploy)** | Shell script | `bash scripts/synthetic_check.sh` | Live dev/prod deployment check using real Vertex AI with backoff (up to 90s for cold starts). |

---

## 3. Mocking & Test Doubles
- **Backend LLM (`LLM_BACKEND=fake`):** Deterministic fake client returning valid `ReportContent`. Simulates `ModelNotFound` when `active_model` is set to invalid/deprecated model to test the fallback flow.
- **Frontend Services (`VITE_API_MODE=mock`):** Mock implementation of the API client layer mimicking network latency and cold-start wakeups without requiring a live backend.

---

## 4. Test Execution Conventions
- Run all tests: `make test`
- Run backend tests only: `uv run pytest`
- Run a single test file: `uv run pytest backend/tests/unit/test_prompt.py`
- Run frontend tests: `cd frontend && npm test`
- Run E2E tests: `make e2e`
