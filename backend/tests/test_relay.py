"""Unit and integration tests for Grafana alert webhook relay and GitHub repository dispatch.

Covers Issue #10 acceptance criteria:
- Route registration & configuration in Settings (RELAY_WEBHOOK_TOKEN, GITHUB_DISPATCH_PAT, GITHUB_REPOSITORY, RELAY_DEDUPE_COOLDOWN_SECONDS)
- Shared secret authentication via X-Webhook-Token or Authorization: Bearer
- Constant-time comparison using secrets.compare_digest
- 401 Unauthorized with RFC 9457 ProblemDetails on missing or invalid tokens
- Grafana alert payload parsing and validation with Pydantic schemas
- 422 Unprocessable Entity with RFC 9457 ProblemDetails on malformed payload or missing required fields
- Field extraction (alertname, fingerprint, status, environment, dashboard_url, runbook_url)
- Fingerprint deduplication and cooldown window
- Cooldown expiration allowing re-dispatch
- Cache pruning for expired entries
- Non-firing alerts handling (status="resolved" ignored without dispatch)
- GitHub repository_dispatch payload reshaping and delivery
- 502 Bad Gateway with RFC 9457 ProblemDetails on upstream GitHub failure without token leakage
- Injectable MockGitHubDispatcher and offline execution with zero external network calls
"""

import time
from typing import Generator
import unittest.mock

from fastapi import status
from fastapi.testclient import TestClient
import httpx
import pytest

from app.config import Settings, get_settings
from app.main import app
from app.schemas.relay import (
    GitHubDispatchClientPayload,
    GitHubDispatchPayload,
    GrafanaAlertItem,
    GrafanaAlertPayload,
    RelayResponse,
)
from app.services.relay import (
    GitHubDispatchError,
    HttpGitHubDispatcher,
    MockGitHubDispatcher,
    RelayService,
    get_github_dispatcher,
    get_shared_cooldown_cache,
)

VALID_TOKEN = "dev-relay-token-secret-123"
AUTH_HEADER = {"X-Webhook-Token": VALID_TOKEN}
BEARER_AUTH_HEADER = {"Authorization": f"Bearer {VALID_TOKEN}"}

SAMPLE_GRAFANA_ALERT: dict = {
    "receiver": "handover-relay",
    "status": "firing",
    "alerts": [
        {
            "status": "firing",
            "labels": {
                "alertname": "HandoverReportGenerationHighErrorRate",
                "environment": "prod",
                "severity": "critical",
            },
            "annotations": {
                "summary": "Shift leads cannot generate handovers",
                "description": "Error rate exceeds 20% over 10m window",
                "dashboard_url": "https://grafana.example.com/d/handover",
                "runbook_url": "https://github.com/gxobst/handover-copilot/blob/main/_docs/runbook.md",
            },
            "startsAt": "2026-11-14T03:00:00Z",
            "endsAt": "0001-01-01T00:00:00Z",
            "generatorURL": "https://grafana.example.com/alerting/123",
            "fingerprint": "a1b2c3d4e5f67890",
            "dashboardURL": "https://grafana.example.com/d/handover",
        }
    ],
    "groupLabels": {
        "alertname": "HandoverReportGenerationHighErrorRate",
    },
    "commonLabels": {
        "alertname": "HandoverReportGenerationHighErrorRate",
        "environment": "prod",
    },
    "commonAnnotations": {
        "summary": "Shift leads cannot generate handovers",
    },
    "externalURL": "https://grafana.example.com",
}


@pytest.fixture(autouse=True)
def reset_relay_dependencies() -> Generator[None, None, None]:
    """Reset dependency overrides and module-level cooldown cache between tests."""
    get_shared_cooldown_cache().clear()
    mock_dispatcher = MockGitHubDispatcher()
    app.dependency_overrides[get_github_dispatcher] = lambda: mock_dispatcher
    yield
    app.dependency_overrides.clear()
    get_shared_cooldown_cache().clear()


@pytest.fixture
def mock_dispatcher() -> MockGitHubDispatcher:
    """Fixture providing the active MockGitHubDispatcher instance."""
    dispatcher = MockGitHubDispatcher()
    app.dependency_overrides[get_github_dispatcher] = lambda: dispatcher
    return dispatcher


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient fixture."""
    return TestClient(app, raise_server_exceptions=False)


# =============================================================================
# 1. Configuration Settings Tests
# =============================================================================


def test_relay_settings_defaults_and_aliases() -> None:
    """Settings model includes relay configuration fields with correct defaults and aliases."""
    settings = Settings(_env_file=None)
    assert settings.relay_webhook_token == "dev-relay-token-secret-123"
    assert settings.github_dispatch_pat == ""
    assert settings.github_repository == "gxobst/handover-copilot"
    assert settings.relay_dedupe_cooldown_seconds == 1800

    custom_settings = Settings(
        RELAY_WEBHOOK_TOKEN="custom-secret",
        GITHUB_DISPATCH_PAT="ghp_test12345",
        GITHUB_REPOSITORY="custom-owner/custom-repo",
        RELAY_DEDUPE_COOLDOWN_SECONDS="600",
    )
    assert custom_settings.relay_webhook_token == "custom-secret"
    assert custom_settings.github_dispatch_pat == "ghp_test12345"
    assert custom_settings.github_repository == "custom-owner/custom-repo"
    assert custom_settings.relay_dedupe_cooldown_seconds == 600


# =============================================================================
# 2. Shared Secret Authentication Tests (AC-2)
# =============================================================================


def test_webhook_missing_token_returns_401_problem_details(client: TestClient) -> None:
    """Request without authentication token returns HTTP 401 with RFC 9457 ProblemDetails."""
    response = client.post("/api/relay/webhook", json=SAMPLE_GRAFANA_ALERT)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers.get("content-type") == "application/problem+json"
    data = response.json()
    assert data["status"] == 401
    assert data["title"] == "Unauthorized"
    assert "Missing webhook authentication token" in data["detail"]


def test_webhook_invalid_x_webhook_token_returns_401(client: TestClient) -> None:
    """Request with invalid X-Webhook-Token returns HTTP 401 with RFC 9457 ProblemDetails."""
    response = client.post(
        "/api/relay/webhook",
        json=SAMPLE_GRAFANA_ALERT,
        headers={"X-Webhook-Token": "invalid-secret-value"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers.get("content-type") == "application/problem+json"
    data = response.json()
    assert data["status"] == 401
    assert data["title"] == "Unauthorized"
    assert "Invalid webhook authentication token" in data["detail"]


def test_webhook_invalid_bearer_token_returns_401(client: TestClient) -> None:
    """Request with invalid Authorization: Bearer token returns HTTP 401."""
    response = client.post(
        "/api/relay/webhook",
        json=SAMPLE_GRAFANA_ALERT,
        headers={"Authorization": "Bearer wrong-token-xyz"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    data = response.json()
    assert data["status"] == 401
    assert data["title"] == "Unauthorized"


def test_webhook_valid_bearer_token_authenticates(
    client: TestClient, mock_dispatcher: MockGitHubDispatcher
) -> None:
    """Request with valid Authorization: Bearer token is authenticated successfully."""
    response = client.post(
        "/api/relay/webhook",
        json=SAMPLE_GRAFANA_ALERT,
        headers=BEARER_AUTH_HEADER,
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["status"] == "dispatched"
    assert len(mock_dispatcher.dispatches) == 1


# =============================================================================
# 3. Payload Validation Tests (AC-3)
# =============================================================================


def test_webhook_missing_body_returns_422_problem_details(client: TestClient) -> None:
    """Request with empty body returns HTTP 422 with RFC 9457 ProblemDetails."""
    response = client.post(
        "/api/relay/webhook",
        headers=AUTH_HEADER,
        json={},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert response.headers.get("content-type") == "application/problem+json"
    data = response.json()
    assert data["status"] == 422
    assert data["title"] == "Unprocessable Entity"


def test_webhook_empty_alerts_returns_422(client: TestClient) -> None:
    """Request with empty alerts list returns HTTP 422 ProblemDetails."""
    invalid_payload = {"status": "firing", "alerts": []}
    response = client.post(
        "/api/relay/webhook",
        headers=AUTH_HEADER,
        json=invalid_payload,
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    data = response.json()
    assert data["status"] == 422
    assert data["title"] == "Unprocessable Entity"


def test_webhook_missing_fingerprint_returns_422(client: TestClient) -> None:
    """Request with alert missing fingerprint returns HTTP 422 ProblemDetails."""
    invalid_payload = {
        "status": "firing",
        "alerts": [{"status": "firing", "labels": {"alertname": "Test"}}],
    }
    response = client.post(
        "/api/relay/webhook",
        headers=AUTH_HEADER,
        json=invalid_payload,
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    data = response.json()
    assert data["status"] == 422


# =============================================================================
# 4. Successful Dispatch & Reshaping Tests (AC-4, AC-6)
# =============================================================================


def test_valid_firing_alert_dispatches_successfully(
    client: TestClient, mock_dispatcher: MockGitHubDispatcher
) -> None:
    """Valid firing alert reshapes payload, triggers dispatch, and returns HTTP 200 with status 'dispatched'."""
    response = client.post(
        "/api/relay/webhook",
        headers=AUTH_HEADER,
        json=SAMPLE_GRAFANA_ALERT,
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["status"] == "dispatched"
    assert data["event_type"] == "grafana-alert"
    assert data["fingerprint"] == "a1b2c3d4e5f67890"

    # Verify mock dispatcher was called once with exact expected payload
    assert len(mock_dispatcher.dispatches) == 1
    dispatch = mock_dispatcher.dispatches[0]
    assert dispatch.event_type == "grafana-alert"
    assert dispatch.client_payload == {
        "alertname": "HandoverReportGenerationHighErrorRate",
        "fingerprint": "a1b2c3d4e5f67890",
        "status": "firing",
        "environment": "prod",
        "dashboard_url": "https://grafana.example.com/d/handover",
        "runbook_url": "https://github.com/gxobst/handover-copilot/blob/main/_docs/runbook.md",
    }


def test_alert_field_extraction_fallbacks(
    client: TestClient, mock_dispatcher: MockGitHubDispatcher
) -> None:
    """Field extraction properly applies fallbacks when optional annotations/labels are omitted."""
    minimal_alert = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "fingerprint": "fp-minimal-123",
                "labels": {},
                "annotations": {},
            }
        ],
    }
    response = client.post(
        "/api/relay/webhook",
        headers=AUTH_HEADER,
        json=minimal_alert,
    )
    assert response.status_code == status.HTTP_200_OK
    assert len(mock_dispatcher.dispatches) == 1
    payload = mock_dispatcher.dispatches[0].client_payload
    assert payload["alertname"] == "UnknownAlert"
    assert payload["fingerprint"] == "fp-minimal-123"
    assert payload["environment"] == "prod"
    assert payload["dashboard_url"] == ""
    assert payload["runbook_url"] == "_docs/runbook.md"


# =============================================================================
# 5. Deduplication & Storm Protection Tests (AC-5)
# =============================================================================


def test_deduplication_prevents_duplicate_dispatch_within_cooldown(
    client: TestClient, mock_dispatcher: MockGitHubDispatcher
) -> None:
    """Repeated alert with identical fingerprint within cooldown window is deduplicated."""
    # First request: should dispatch
    res1 = client.post(
        "/api/relay/webhook",
        headers=AUTH_HEADER,
        json=SAMPLE_GRAFANA_ALERT,
    )
    assert res1.status_code == status.HTTP_200_OK
    assert res1.json()["status"] == "dispatched"
    assert len(mock_dispatcher.dispatches) == 1

    # Second request immediately: should deduplicate
    res2 = client.post(
        "/api/relay/webhook",
        headers=AUTH_HEADER,
        json=SAMPLE_GRAFANA_ALERT,
    )
    assert res2.status_code == status.HTTP_200_OK
    data2 = res2.json()
    assert data2["status"] == "deduplicated"
    assert data2["fingerprint"] == "a1b2c3d4e5f67890"
    assert data2["event_type"] == "grafana-alert"

    # Mock dispatcher should NOT have been invoked again
    assert len(mock_dispatcher.dispatches) == 1


def test_different_fingerprints_dispatch_independently(
    client: TestClient, mock_dispatcher: MockGitHubDispatcher
) -> None:
    """Different fingerprints are not deduplicated and dispatch independently."""
    payload1 = {
        "status": "firing",
        "alerts": [{"status": "firing", "fingerprint": "alert-1"}],
    }
    payload2 = {
        "status": "firing",
        "alerts": [{"status": "firing", "fingerprint": "alert-2"}],
    }

    res1 = client.post("/api/relay/webhook", headers=AUTH_HEADER, json=payload1)
    res2 = client.post("/api/relay/webhook", headers=AUTH_HEADER, json=payload2)

    assert res1.json()["status"] == "dispatched"
    assert res2.json()["status"] == "dispatched"
    assert len(mock_dispatcher.dispatches) == 2


def test_cooldown_expiration_allows_redispatch(
    client: TestClient, mock_dispatcher: MockGitHubDispatcher
) -> None:
    """Alert dispatched again after cooldown window expires triggers a new dispatch call."""
    fake_time = 1_000_000.0

    with unittest.mock.patch("time.time", return_value=fake_time):
        res1 = client.post(
            "/api/relay/webhook",
            headers=AUTH_HEADER,
            json=SAMPLE_GRAFANA_ALERT,
        )
        assert res1.json()["status"] == "dispatched"
        assert len(mock_dispatcher.dispatches) == 1

    # Advance time within cooldown window (e.g. +600s < 1800s) -> deduplicated
    with unittest.mock.patch("time.time", return_value=fake_time + 600.0):
        res2 = client.post(
            "/api/relay/webhook",
            headers=AUTH_HEADER,
            json=SAMPLE_GRAFANA_ALERT,
        )
        assert res2.json()["status"] == "deduplicated"
        assert len(mock_dispatcher.dispatches) == 1

    # Advance time beyond cooldown window (e.g. +1801s > 1800s) -> dispatches again!
    with unittest.mock.patch("time.time", return_value=fake_time + 1801.0):
        res3 = client.post(
            "/api/relay/webhook",
            headers=AUTH_HEADER,
            json=SAMPLE_GRAFANA_ALERT,
        )
        assert res3.json()["status"] == "dispatched"
        assert len(mock_dispatcher.dispatches) == 2


# =============================================================================
# 6. Non-firing Alert Handling Tests (AC-5)
# =============================================================================


def test_resolved_alert_ignored_without_dispatch(
    client: TestClient, mock_dispatcher: MockGitHubDispatcher
) -> None:
    """Resolved/non-firing alert returns HTTP 200 with status 'ignored' and does not trigger dispatch."""
    resolved_alert = {
        "status": "resolved",
        "alerts": [
            {
                "status": "resolved",
                "fingerprint": "fp-resolved-999",
                "labels": {"alertname": "HighLatency"},
            }
        ],
    }
    response = client.post(
        "/api/relay/webhook",
        headers=AUTH_HEADER,
        json=resolved_alert,
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["status"] == "ignored"
    assert data["fingerprint"] == "fp-resolved-999"
    assert data.get("reason") == "non-firing alert"
    assert len(mock_dispatcher.dispatches) == 0


# =============================================================================
# 7. Upstream Failure & Error Handling Tests (AC-6, AC-7)
# =============================================================================


def test_upstream_github_error_returns_502_problem_details(
    client: TestClient,
) -> None:
    """Upstream GitHub failure returns HTTP 502 with RFC 9457 ProblemDetails."""
    failing_dispatcher = MockGitHubDispatcher(should_fail=True, failure_status_code=500)
    app.dependency_overrides[get_github_dispatcher] = lambda: failing_dispatcher

    response = client.post(
        "/api/relay/webhook",
        headers=AUTH_HEADER,
        json=SAMPLE_GRAFANA_ALERT,
    )
    assert response.status_code == status.HTTP_502_BAD_GATEWAY
    assert response.headers.get("content-type") == "application/problem+json"
    data = response.json()
    assert data["status"] == 502
    assert data["title"] == "Bad Gateway"
    assert "Simulated GitHub upstream failure" in data["detail"]


def test_failed_dispatch_does_not_pollute_cooldown_cache(
    client: TestClient,
) -> None:
    """Failed dispatch attempts do not lock out future retries in the cooldown cache."""
    dispatcher = MockGitHubDispatcher(should_fail=True)
    app.dependency_overrides[get_github_dispatcher] = lambda: dispatcher

    # First attempt fails
    res1 = client.post(
        "/api/relay/webhook",
        headers=AUTH_HEADER,
        json=SAMPLE_GRAFANA_ALERT,
    )
    assert res1.status_code == status.HTTP_502_BAD_GATEWAY

    # Make dispatcher healthy
    dispatcher.should_fail = False

    # Retry should immediately dispatch rather than claiming 'deduplicated'
    res2 = client.post(
        "/api/relay/webhook",
        headers=AUTH_HEADER,
        json=SAMPLE_GRAFANA_ALERT,
    )
    assert res2.status_code == status.HTTP_200_OK
    assert res2.json()["status"] == "dispatched"
    assert len(dispatcher.dispatches) == 1


# =============================================================================
# 8. Unit Tests for HttpGitHubDispatcher and RelayService
# =============================================================================


@pytest.mark.anyio
async def test_http_github_dispatcher_success() -> None:
    """HttpGitHubDispatcher sends correct headers, payload, and URL to GitHub dispatches API."""
    settings = Settings(
        GITHUB_DISPATCH_PAT="test-pat-token-secret",
        GITHUB_REPOSITORY="gxobst/handover-copilot",
    )
    dispatcher = HttpGitHubDispatcher(settings=settings)

    test_payload = GitHubDispatchPayload(
        event_type="grafana-alert",
        client_payload={"alertname": "TestAlert", "fingerprint": "123"},
    )

    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.github.com/repos/gxobst/handover-copilot/dispatches"
        assert request.headers["Accept"] == "application/vnd.github+json"
        assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"
        assert request.headers["Authorization"] == "Bearer test-pat-token-secret"
        return httpx.Response(204)

    transport = httpx.MockTransport(mock_handler)
    with unittest.mock.patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
        result = await dispatcher.dispatch(test_payload)
        assert result is True


@pytest.mark.anyio
async def test_http_github_dispatcher_error_masks_pat() -> None:
    """HttpGitHubDispatcher raises GitHubDispatchError without leaking the PAT on 4xx/5xx responses."""
    secret_pat = "super-secret-pat-xyz123"
    settings = Settings(
        GITHUB_DISPATCH_PAT=secret_pat,
        GITHUB_REPOSITORY="gxobst/handover-copilot",
    )
    dispatcher = HttpGitHubDispatcher(settings=settings)

    test_payload = GitHubDispatchPayload(
        event_type="grafana-alert",
        client_payload={"alertname": "TestAlert"},
    )

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Bad credentials"})

    transport = httpx.MockTransport(mock_handler)
    with unittest.mock.patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
        with pytest.raises(GitHubDispatchError) as exc_info:
            await dispatcher.dispatch(test_payload)
        assert "403" in str(exc_info.value)
        assert secret_pat not in str(exc_info.value)


@pytest.mark.anyio
async def test_relay_service_cache_pruning() -> None:
    """RelayService prunes expired fingerprint entries from cooldown cache."""
    settings = Settings(RELAY_DEDUPE_COOLDOWN_SECONDS=100)
    mock_dispatcher = MockGitHubDispatcher()
    cache: dict[str, float] = {
        "old_fingerprint": 50.0,
        "recent_fingerprint": 150.0,
    }
    service = RelayService(
        dispatcher=mock_dispatcher,
        settings=settings,
        cooldown_cache=cache,
    )

    # Prune at now = 200.0:
    # 200.0 - 50.0 = 150.0 >= 100 -> pruned
    # 200.0 - 150.0 = 50.0 < 100 -> kept
    service._prune_expired(now=200.0)
    assert "old_fingerprint" not in cache
    assert "recent_fingerprint" in cache


@pytest.mark.anyio
async def test_http_github_dispatcher_network_error() -> None:
    """HttpGitHubDispatcher raises GitHubDispatchError upon network/timeout exception."""
    settings = Settings(GITHUB_REPOSITORY="gxobst/handover-copilot")
    dispatcher = HttpGitHubDispatcher(settings=settings)
    test_payload = GitHubDispatchPayload(
        event_type="grafana-alert",
        client_payload={"alertname": "TestAlert"},
    )

    def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("Connection timed out")

    transport = httpx.MockTransport(mock_handler)
    with unittest.mock.patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
        with pytest.raises(GitHubDispatchError) as exc_info:
            await dispatcher.dispatch(test_payload)
        assert "network error" in str(exc_info.value).lower()


def test_schema_extra_attributes_allowed() -> None:
    """Verify relay Pydantic schemas accept arbitrary extra fields from Grafana webhook."""
    from app.schemas.relay import GrafanaAlertAnnotations, GrafanaAlertLabels

    labels = GrafanaAlertLabels(alertname="Test", custom_label="custom_val")
    assert labels.alertname == "Test"
    assert labels.model_dump()["custom_label"] == "custom_val"

    annotations = GrafanaAlertAnnotations(summary="Test summary", extra_info="abc")
    assert annotations.summary == "Test summary"
    assert annotations.model_dump()["extra_info"] == "abc"
