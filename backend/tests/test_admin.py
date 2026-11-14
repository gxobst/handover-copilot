"""Integration and unit tests for dynamic admin settings API and authentication.

Covers Issue #8 acceptance criteria:
- Configuration of ADMIN_TOKEN in Settings
- Bearer token security dependency (HTTPBearer, constant-time compare_digest)
- 401 Unauthorized with RFC 9457 ProblemDetails on missing, malformed, or invalid tokens
- GET /api/admin/settings returns current active and fallback models
- PUT /api/admin/settings updates active_model, fallback_model, or both
- Validation: 422 ProblemDetails on empty payload {}, null, empty string, whitespace, invalid pattern
- Model validation is strictly pattern-based (non-empty string matching ^[a-zA-Z0-9._-]+$), accepts retired models (gemini-2.5-flash-lite)
- Immediate read-after-write (AC-10) without server restart or caching delay
- End-to-end report generation immediately honors runtime admin updates
- Unit tests for settings_store functions and require_admin_token dependency
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Generator
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.auth import require_admin_token
from app.config import Settings, get_settings
from app.db.models import AppSetting, Event
from app.db.session import create_db_engine, get_db
from app.main import app, create_app
from app.schemas.admin import (
    MODEL_NAME_PATTERN,
    AdminSettingsResponse,
    AdminSettingsUpdate,
)
from app.schemas.errors import ProblemDetails
from app.schemas.events import Category
from app.settings_store import (
    SETTING_ACTIVE_MODEL,
    SETTING_FALLBACK_MODEL,
    get_admin_settings,
    update_admin_settings,
)

DEFAULT_ADMIN_TOKEN = "dev-admin-secret-key-12345"
AUTH_HEADER = {"Authorization": f"Bearer {DEFAULT_ADMIN_TOKEN}"}


# ---------------------------------------------------------------------------
# Test Fixtures (Isolated Temporary SQLite Database)
# ---------------------------------------------------------------------------


@pytest.fixture
def test_db_path(tmp_path: Path) -> Path:
    """Provide a path for an isolated temporary SQLite database."""
    return tmp_path / "test_admin.db"


@pytest.fixture
def test_db_url(test_db_path: Path) -> str:
    """Provide SQLite URL for the isolated temporary database."""
    return f"sqlite:///{test_db_path.as_posix()}"


@pytest.fixture
def alembic_config(test_db_url: str) -> Config:
    """Provide Alembic Config pointing to the temporary test database."""
    backend_dir = Path(__file__).resolve().parent.parent
    ini_path = backend_dir / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("sqlalchemy.url", test_db_url)
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    return cfg


@pytest.fixture
def db_session(alembic_config: Config, test_db_url: str) -> Generator[Session, None, None]:
    """Run Alembic migrations to head and provide transactional session."""
    command.upgrade(alembic_config, "head")
    engine = create_db_engine(test_db_url)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def test_settings() -> Settings:
    """Provide default Settings instance with standard admin token and models."""
    return Settings(
        admin_token=DEFAULT_ADMIN_TOKEN,
        active_model="google/gemini-3.5-flash-lite",
        fallback_model="google/gemini-3.1-flash-lite",
    )


@pytest.fixture
def client(db_session: Session, test_settings: Settings) -> Generator[TestClient, None, None]:
    """Provide a TestClient with get_db and get_settings overridden to test fixtures."""
    test_app = create_app()
    test_app.dependency_overrides[get_db] = lambda: db_session
    test_app.dependency_overrides[get_settings] = lambda: test_settings
    with TestClient(test_app) as tc:
        yield tc
    test_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 1. Authentication & Security Tests (GET & PUT /api/admin/settings)
# ---------------------------------------------------------------------------


def test_get_settings_missing_auth_header(client: TestClient) -> None:
    """GET /api/admin/settings without Authorization returns 401 ProblemDetails."""
    response = client.get("/api/admin/settings")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = ProblemDetails.model_validate(response.json())
    assert problem.status == 401
    assert problem.title == "Unauthorized"
    assert "Missing Authorization header" in problem.detail


def test_get_settings_malformed_auth_header_basic(client: TestClient) -> None:
    """GET /api/admin/settings with Basic auth header returns 401 ProblemDetails."""
    response = client.get(
        "/api/admin/settings",
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = ProblemDetails.model_validate(response.json())
    assert problem.status == 401
    assert problem.title == "Unauthorized"
    assert "Malformed Authorization header" in problem.detail


def test_get_settings_malformed_auth_header_missing_token(client: TestClient) -> None:
    """GET /api/admin/settings with 'Bearer' and no token returns 401 ProblemDetails."""
    response = client.get(
        "/api/admin/settings",
        headers={"Authorization": "Bearer"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = ProblemDetails.model_validate(response.json())
    assert problem.status == 401
    assert problem.title == "Unauthorized"


def test_get_settings_invalid_token(client: TestClient) -> None:
    """GET /api/admin/settings with incorrect token returns 401 ProblemDetails."""
    response = client.get(
        "/api/admin/settings",
        headers={"Authorization": "Bearer wrong-admin-token-value"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = ProblemDetails.model_validate(response.json())
    assert problem.status == 401
    assert problem.title == "Unauthorized"
    assert "Invalid or expired admin token" in problem.detail


def test_put_settings_missing_auth_header(client: TestClient) -> None:
    """PUT /api/admin/settings without Authorization returns 401 ProblemDetails."""
    response = client.put(
        "/api/admin/settings",
        json={"active_model": "gemini-3.5-flash"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = ProblemDetails.model_validate(response.json())
    assert problem.status == 401
    assert problem.title == "Unauthorized"


def test_put_settings_invalid_token(client: TestClient) -> None:
    """PUT /api/admin/settings with invalid token returns 401 ProblemDetails."""
    response = client.put(
        "/api/admin/settings",
        headers={"Authorization": "Bearer invalid-key"},
        json={"active_model": "gemini-3.5-flash"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = ProblemDetails.model_validate(response.json())
    assert problem.status == 401
    assert problem.title == "Unauthorized"


# ---------------------------------------------------------------------------
# 2. GET /api/admin/settings Tests
# ---------------------------------------------------------------------------


def test_get_settings_default_values(client: TestClient) -> None:
    """GET /api/admin/settings returns 200 with default models when DB is empty."""
    response = client.get("/api/admin/settings", headers=AUTH_HEADER)
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data == {
        "active_model": "google/gemini-3.5-flash-lite",
        "fallback_model": "google/gemini-3.1-flash-lite",
        "activeModel": "google/gemini-3.5-flash-lite",
        "fallbackModel": "google/gemini-3.1-flash-lite",
    }
    validated = AdminSettingsResponse.model_validate(data)
    assert validated.active_model == "google/gemini-3.5-flash-lite"
    assert validated.fallback_model == "google/gemini-3.1-flash-lite"


def test_get_settings_reads_from_database(client: TestClient, db_session: Session) -> None:
    """GET /api/admin/settings reads persisted values from app_settings table."""
    db_session.add(AppSetting(key=SETTING_ACTIVE_MODEL, value="gemini-custom-active"))
    db_session.add(AppSetting(key=SETTING_FALLBACK_MODEL, value="gemini-custom-fallback"))
    db_session.commit()

    response = client.get("/api/admin/settings", headers=AUTH_HEADER)
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "active_model": "gemini-custom-active",
        "fallback_model": "gemini-custom-fallback",
        "activeModel": "gemini-custom-active",
        "fallbackModel": "gemini-custom-fallback",
    }


# ---------------------------------------------------------------------------
# 3. PUT /api/admin/settings Validation Tests (HTTP 422 ProblemDetails)
# ---------------------------------------------------------------------------


def test_put_settings_empty_payload(client: TestClient) -> None:
    """PUT /api/admin/settings with empty object {} returns 422 ProblemDetails."""
    response = client.put("/api/admin/settings", headers=AUTH_HEADER, json={})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = ProblemDetails.model_validate(response.json())
    assert problem.status == 422
    assert problem.title == "Unprocessable Entity"
    assert "At least one of active_model or fallback_model must be provided" in problem.detail


def test_put_settings_null_active_model(client: TestClient) -> None:
    """PUT /api/admin/settings with null active_model returns 422 ProblemDetails."""
    response = client.put(
        "/api/admin/settings",
        headers=AUTH_HEADER,
        json={"active_model": None},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    problem = ProblemDetails.model_validate(response.json())
    assert problem.status == 422
    assert "cannot be null" in problem.detail


def test_put_settings_null_fallback_model(client: TestClient) -> None:
    """PUT /api/admin/settings with null fallback_model returns 422 ProblemDetails."""
    response = client.put(
        "/api/admin/settings",
        headers=AUTH_HEADER,
        json={"fallback_model": None},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    problem = ProblemDetails.model_validate(response.json())
    assert problem.status == 422
    assert "cannot be null" in problem.detail


def test_put_settings_empty_string_model(client: TestClient) -> None:
    """PUT /api/admin/settings with empty string model returns 422 ProblemDetails."""
    response = client.put(
        "/api/admin/settings",
        headers=AUTH_HEADER,
        json={"active_model": ""},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    problem = ProblemDetails.model_validate(response.json())
    assert problem.status == 422
    assert "cannot be empty or whitespace" in problem.detail


def test_put_settings_whitespace_only_model(client: TestClient) -> None:
    """PUT /api/admin/settings with whitespace-only string returns 422 ProblemDetails."""
    response = client.put(
        "/api/admin/settings",
        headers=AUTH_HEADER,
        json={"fallback_model": "    "},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    problem = ProblemDetails.model_validate(response.json())
    assert problem.status == 422
    assert "cannot be empty or whitespace" in problem.detail


def test_put_settings_invalid_characters(client: TestClient) -> None:
    """PUT /api/admin/settings with invalid characters returns 422 ProblemDetails."""
    invalid_models = [
        "gemini 3.5 flash",  # contains spaces
        "gemini/model:v1",   # slash and colon not in ^[a-zA-Z0-9._-]+$
        "model@test!",       # special chars
        "model$name",        # symbol
    ]
    for model_name in invalid_models:
        response = client.put(
            "/api/admin/settings",
            headers=AUTH_HEADER,
            json={"active_model": model_name},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT, f"Failed for {model_name}"
        problem = ProblemDetails.model_validate(response.json())
        assert problem.status == 422
        assert "invalid characters" in problem.detail


def test_put_settings_extra_forbidden_fields(client: TestClient) -> None:
    """PUT /api/admin/settings with unexpected fields returns 422 ProblemDetails."""
    response = client.put(
        "/api/admin/settings",
        headers=AUTH_HEADER,
        json={"active_model": "gemini-3.5-flash", "unexpected": "value"},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    problem = ProblemDetails.model_validate(response.json())
    assert problem.status == 422


# ---------------------------------------------------------------------------
# 4. PUT /api/admin/settings Success Tests (Partial & Full Updates)
# ---------------------------------------------------------------------------


def test_put_settings_update_active_model_only(client: TestClient, db_session: Session) -> None:
    """PUT updating active_model updates active_model and preserves fallback_model."""
    response = client.put(
        "/api/admin/settings",
        headers=AUTH_HEADER,
        json={"active_model": "gemini-3.5-flash"},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "active_model": "gemini-3.5-flash",
        "fallback_model": "google/gemini-3.1-flash-lite",
        "activeModel": "gemini-3.5-flash",
        "fallbackModel": "google/gemini-3.1-flash-lite",
    }

    # Verify persistence in DB
    row = db_session.get(AppSetting, SETTING_ACTIVE_MODEL)
    assert row is not None
    assert row.value == "gemini-3.5-flash"


def test_put_settings_update_fallback_model_only(client: TestClient, db_session: Session) -> None:
    """PUT updating fallback_model updates fallback_model and preserves active_model."""
    response = client.put(
        "/api/admin/settings",
        headers=AUTH_HEADER,
        json={"fallback_model": "gemini-3.5-flash"},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "active_model": "google/gemini-3.5-flash-lite",
        "fallback_model": "gemini-3.5-flash",
        "activeModel": "google/gemini-3.5-flash-lite",
        "fallbackModel": "gemini-3.5-flash",
    }

    # Verify persistence in DB
    row = db_session.get(AppSetting, SETTING_FALLBACK_MODEL)
    assert row is not None
    assert row.value == "gemini-3.5-flash"


def test_put_settings_update_both_models(client: TestClient, db_session: Session) -> None:
    """PUT updating both active_model and fallback_model succeeds."""
    response = client.put(
        "/api/admin/settings",
        headers=AUTH_HEADER,
        json={
            "active_model": "gemini-4-argon",
            "fallback_model": "gemini-3.5-flash-lite",
        },
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "active_model": "gemini-4-argon",
        "fallback_model": "gemini-3.5-flash-lite",
        "activeModel": "gemini-4-argon",
        "fallbackModel": "gemini-3.5-flash-lite",
    }

    assert db_session.get(AppSetting, SETTING_ACTIVE_MODEL).value == "gemini-4-argon"
    assert db_session.get(AppSetting, SETTING_FALLBACK_MODEL).value == "gemini-3.5-flash-lite"


def test_put_settings_accepts_retired_model(client: TestClient) -> None:
    """Model validation is pattern-only and accepts retired models like gemini-2.5-flash-lite."""
    response = client.put(
        "/api/admin/settings",
        headers=AUTH_HEADER,
        json={"active_model": "gemini-2.5-flash-lite"},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["active_model"] == "gemini-2.5-flash-lite"


def test_put_settings_trims_whitespace(client: TestClient, db_session: Session) -> None:
    """PUT strips leading and trailing whitespace from model names."""
    response = client.put(
        "/api/admin/settings",
        headers=AUTH_HEADER,
        json={"active_model": "   gemini-3.5-flash   "},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["active_model"] == "gemini-3.5-flash"
    assert db_session.get(AppSetting, SETTING_ACTIVE_MODEL).value == "gemini-3.5-flash"


# ---------------------------------------------------------------------------
# 5. Immediate Read-After-Write (AC-10) Tests
# ---------------------------------------------------------------------------


def test_immediate_read_after_write(client: TestClient) -> None:
    """AC-10: Changes via PUT /api/admin/settings are immediately reflected on next GET."""
    # Initial state
    get1 = client.get("/api/admin/settings", headers=AUTH_HEADER)
    assert get1.json()["active_model"] == "google/gemini-3.5-flash-lite"

    # Update active_model
    put_res = client.put(
        "/api/admin/settings",
        headers=AUTH_HEADER,
        json={"active_model": "gemini-2.5-flash-lite"},
    )
    assert put_res.status_code == status.HTTP_200_OK

    # Next GET must immediately return new model without server restart
    get2 = client.get("/api/admin/settings", headers=AUTH_HEADER)
    assert get2.status_code == status.HTTP_200_OK
    assert get2.json()["active_model"] == "gemini-2.5-flash-lite"
    assert get2.json()["fallback_model"] == "google/gemini-3.1-flash-lite"

    # Update fallback_model
    put_res2 = client.put(
        "/api/admin/settings",
        headers=AUTH_HEADER,
        json={"fallback_model": "gemini-3.5-flash"},
    )
    assert put_res2.status_code == status.HTTP_200_OK

    # Next GET reflects both updates
    get3 = client.get("/api/admin/settings", headers=AUTH_HEADER)
    assert get3.json() == {
        "active_model": "gemini-2.5-flash-lite",
        "fallback_model": "gemini-3.5-flash",
        "activeModel": "gemini-2.5-flash-lite",
        "fallbackModel": "gemini-3.5-flash",
    }


# ---------------------------------------------------------------------------
# 6. End-to-End Handover Report Generation Honors Dynamic Settings
# ---------------------------------------------------------------------------


def test_report_generation_honors_dynamic_admin_updates_immediately(
    client: TestClient,
    db_session: Session,
) -> None:
    """Verify that subsequent POST /api/reports/generate honors updated model immediately.

    Scenario:
    1. Seed shift events in the database.
    2. Generate report with default active_model (gemini-3.5-flash-lite) -> succeeds with primary.
    3. Admin PUT updates active_model to retired model (gemini-2.5-flash-lite).
    4. Next report generation immediately attempts gemini-2.5-flash-lite, fails (ModelNotFound in FakeLLMClient),
       falls back to gemini-3.1-flash-lite, and succeeds with model_used="gemini-3.1-flash-lite".
    5. Admin PUT updates active_model to supported model (gemini-3.5-flash).
    6. Next report generation succeeds with primary model_used="gemini-3.5-flash".
    """
    shift_key = "2026-11-14-early"

    # Step 1: Seed shift events
    event = Event(
        id=uuid4(),
        shift_key=shift_key,
        machine="Packaging-Line-1",
        category="downtime",
        note="Sensor jam stopped belt for 15 minutes",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(event)
    db_session.commit()

    # Step 2: Generate initial report with default settings
    gen_res1 = client.post("/api/reports/generate", json={"shift_key": shift_key})
    assert gen_res1.status_code == status.HTTP_201_CREATED
    report1 = gen_res1.json()
    assert report1["version"] == 1
    assert report1["model_used"] == "google/gemini-3.5-flash-lite"

    # Step 3: Admin reconfigures active_model to retired model gemini-2.5-flash-lite
    admin_put = client.put(
        "/api/admin/settings",
        headers=AUTH_HEADER,
        json={"active_model": "gemini-2.5-flash-lite"},
    )
    assert admin_put.status_code == status.HTTP_200_OK
    assert admin_put.json()["active_model"] == "gemini-2.5-flash-lite"

    # Step 4: Next report generation immediately uses new setting -> fallback to google/gemini-3.1-flash-lite
    gen_res2 = client.post("/api/reports/generate", json={"shift_key": shift_key})
    assert gen_res2.status_code == status.HTTP_201_CREATED
    report2 = gen_res2.json()
    assert report2["version"] == 2
    assert report2["model_used"] == "google/gemini-3.1-flash-lite"

    # Step 5: Admin restores active_model to another supported model gemini-3.5-flash
    admin_put2 = client.put(
        "/api/admin/settings",
        headers=AUTH_HEADER,
        json={"active_model": "gemini-3.5-flash"},
    )
    assert admin_put2.status_code == status.HTTP_200_OK
    assert admin_put2.json()["active_model"] == "gemini-3.5-flash"

    # Step 6: Next report generation succeeds with gemini-3.5-flash as primary
    gen_res3 = client.post("/api/reports/generate", json={"shift_key": shift_key})
    assert gen_res3.status_code == status.HTTP_201_CREATED
    report3 = gen_res3.json()
    assert report3["version"] == 3
    assert report3["model_used"] == "gemini-3.5-flash"


# ---------------------------------------------------------------------------
# 7. Unit Tests for Settings Store and Auth Dependencies
# ---------------------------------------------------------------------------


def test_settings_store_unit_crud(db_session: Session, test_settings: Settings) -> None:
    """Direct unit test of get_admin_settings and update_admin_settings."""
    # Initial read falls back to test_settings
    initial = get_admin_settings(db=db_session, settings=test_settings)
    assert initial.active_model == "google/gemini-3.5-flash-lite"
    assert initial.fallback_model == "google/gemini-3.1-flash-lite"

    # Update active model
    up1 = update_admin_settings(
        update=AdminSettingsUpdate(active_model="gemini-4-argon"),
        db=db_session,
        settings=test_settings,
    )
    assert up1.active_model == "gemini-4-argon"
    assert up1.fallback_model == "google/gemini-3.1-flash-lite"

    # Update fallback model
    up2 = update_admin_settings(
        update=AdminSettingsUpdate(fallback_model="gemini-3.5-flash-lite"),
        db=db_session,
        settings=test_settings,
    )
    assert up2.active_model == "gemini-4-argon"
    assert up2.fallback_model == "gemini-3.5-flash-lite"

    # Read returns persisted values
    read = get_admin_settings(db=db_session, settings=test_settings)
    assert read.active_model == "gemini-4-argon"
    assert read.fallback_model == "gemini-3.5-flash-lite"


def test_require_admin_token_direct_validation(test_settings: Settings) -> None:
    """Direct unit test of require_admin_token auth dependency logic."""
    from starlette.requests import Request
    from fastapi.security import HTTPAuthorizationCredentials

    # Valid token
    scope = {"type": "http", "headers": [(b"authorization", f"Bearer {DEFAULT_ADMIN_TOKEN}".encode())]}
    req = Request(scope)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=DEFAULT_ADMIN_TOKEN)
    token = require_admin_token(req, creds, test_settings)
    assert token == DEFAULT_ADMIN_TOKEN

    # Missing header
    req_empty = Request({"type": "http", "headers": []})
    with pytest.raises(HTTPException) as exc_info:
        require_admin_token(req_empty, None, test_settings)
    assert exc_info.value.status_code == 401
    assert "Missing Authorization header" in exc_info.value.detail

    # Wrong credentials scheme
    creds_basic = HTTPAuthorizationCredentials(scheme="Basic", credentials="xyz")
    with pytest.raises(HTTPException) as exc_info:
        require_admin_token(req, creds_basic, test_settings)
    assert exc_info.value.status_code == 401
    assert "Malformed Authorization header" in exc_info.value.detail

    # Invalid token
    creds_wrong = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong-token")
    with pytest.raises(HTTPException) as exc_info:
        require_admin_token(req, creds_wrong, test_settings)
    assert exc_info.value.status_code == 401
    assert "Invalid or expired admin token" in exc_info.value.detail


def test_model_name_pattern_regex() -> None:
    """Verify MODEL_NAME_PATTERN allows alphanumeric, dot, underscore, and dash."""
    valid = [
        "gemini-3.5-flash-lite",
        "google/gemini-3.5-flash-lite",
        "gemini-2.5-flash-lite",
        "gemini-4-argon",
        "model.name_123-v1",
        "a",
    ]
    for m in valid:
        assert MODEL_NAME_PATTERN.match(m) is not None

    invalid = [
        "",
        "model name",
        "model:1",
        "model@org",
    ]
    for m in invalid:
        assert MODEL_NAME_PATTERN.match(m) is None
