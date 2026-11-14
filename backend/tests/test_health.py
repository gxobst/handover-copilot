import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app, create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_healthz_get_success(client: TestClient) -> None:
    """AC-9: GET /api/healthz returns 200 with status, version, and environment.

    Asserts HTTP 200, content-type header application/json, and exact JSON payload.
    """
    response = client.get("/api/healthz")

    assert response.status_code == 200
    assert "application/json" in response.headers.get("content-type", "")
    assert response.json() == {
        "status": "ok",
        "version": "0.1.0",
        "environment": "local",
    }


@pytest.mark.parametrize("method", ["post", "put", "delete", "patch"])
def test_healthz_non_get_methods_return_405(client: TestClient, method: str) -> None:
    """Assert non-GET HTTP methods on /api/healthz return 405 Method Not Allowed."""
    request_func = getattr(client, method)
    response = request_func("/api/healthz")
    assert response.status_code == 405


def test_healthz_honors_configured_settings() -> None:
    """Assert health endpoint reflects custom environment and version without DB access."""
    custom_settings = Settings(
        environment="dev",
        version="1.2.3",
    )
    test_app = create_app()
    test_app.dependency_overrides[get_settings] = lambda: custom_settings

    with TestClient(test_app) as custom_client:
        response = custom_client.get("/api/healthz")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "version": "1.2.3",
            "environment": "dev",
        }


def test_settings_env_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    """Assert Settings loads APP_ENV and APP_VERSION environment variables."""
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("APP_VERSION", "0.9.0")

    settings = Settings()
    assert settings.environment == "staging"
    assert settings.app_env == "staging"
    assert settings.version == "0.9.0"
    assert settings.app_version == "0.9.0"
