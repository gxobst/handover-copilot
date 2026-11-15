"""Unit and integration tests for report generation rate limiting and budget caps.

Covers Issue #41:
- 5 requests per 10 minutes per client IP sliding window rate limit.
- HTTP 429 Too Many Requests with RFC 9457 ProblemDetails and Retry-After header.
- Window sliding and expiration behavior.
- Resolution of client IP from X-Forwarded-For header (first hop) and client.host fallback.
- Per-user lifetime cap (maximum 20 reports per client IP).
- Global total budget cap (maximum 20 reports across service).
- Strict universal enforcement with NO admin token bypass.
- rate_limit_enabled=False bypass in Settings for testing.
- OpenTelemetry metrics emission (handover_http_requests_total{status_code="429"}).
- Thread-safe concurrency and automatic memory pruning.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Generator
from unittest.mock import MagicMock
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi import Request, status
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.db.models import Event
from app.db.session import create_db_engine, get_db
from app.errors import RateLimitExceededException
from app.main import create_app
from app.schemas.errors import ProblemDetails
from app.services.rate_limiter import (
    RateLimiter,
    extract_client_ip,
    get_rate_limiter,
)
from app.telemetry import get_in_memory_metric_reader

DEFAULT_ADMIN_TOKEN = "dev-admin-secret-key-12345"
AUTH_HEADER = {"Authorization": f"Bearer {DEFAULT_ADMIN_TOKEN}"}


@pytest.fixture
def test_db_path(tmp_path: Path) -> Path:
    """Provide a path for an isolated temporary SQLite database."""
    return tmp_path / "test_rate_limit.db"


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
    """Standard test Settings with rate limiting enabled."""
    return Settings(
        admin_token=DEFAULT_ADMIN_TOKEN,
        active_model="google/gemini-3.5-flash-lite",
        fallback_model="google/gemini-3.1-flash-lite",
        rate_limit_enabled=True,
        rate_limit_window_seconds=600,
        rate_limit_max_requests=5,
        rate_limit_user_lifetime_cap=20,
        rate_limit_global_cap=20,
    )


@pytest.fixture
def client(
    db_session: Session, test_settings: Settings
) -> Generator[TestClient, None, None]:
    """TestClient configured with isolated db and settings."""
    test_app = create_app()
    test_app.dependency_overrides[get_db] = lambda: db_session
    test_app.dependency_overrides[get_settings] = lambda: test_settings
    # Reset singleton rate limiter
    limiter = get_rate_limiter()
    limiter.reset()

    with TestClient(test_app) as tc:
        yield tc

    test_app.dependency_overrides.clear()
    limiter.reset()


def _seed_event(db_session: Session, shift_key: str = "2026-11-14-early") -> None:
    """Helper to insert a valid shift event for report generation."""
    event = Event(
        id=uuid4(),
        shift_key=shift_key,
        machine="Conveyor-1",
        category="downtime",
        note="Belt slip sensor replaced during morning shift",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(event)
    db_session.commit()


# ---------------------------------------------------------------------------
# 1. Per-Client Sliding Window Rate Limit Tests
# ---------------------------------------------------------------------------


def test_rate_limit_allows_up_to_max_requests_in_window(
    client: TestClient, db_session: Session
) -> None:
    """AC-1: 5 requests from the same client IP succeed within 10 minutes."""
    shift_key = "2026-11-14-early"
    _seed_event(db_session, shift_key)

    headers = {"X-Forwarded-For": "198.51.100.10"}
    for i in range(5):
        resp = client.post(
            "/api/reports/generate",
            headers=headers,
            json={"shift_key": shift_key},
        )
        assert resp.status_code == status.HTTP_201_CREATED, f"Request {i + 1} failed"
        assert resp.json()["version"] == i + 1


def test_rate_limit_rejects_6th_request_with_429(
    client: TestClient, db_session: Session
) -> None:
    """AC-1: The 6th request from the same IP is rejected with HTTP 429 and Retry-After."""
    shift_key = "2026-11-14-early"
    _seed_event(db_session, shift_key)

    headers = {"X-Forwarded-For": "198.51.100.20"}
    for _ in range(5):
        res = client.post(
            "/api/reports/generate",
            headers=headers,
            json={"shift_key": shift_key},
        )
        assert res.status_code == status.HTTP_201_CREATED

    # 6th request must fail with 429
    res6 = client.post(
        "/api/reports/generate",
        headers=headers,
        json={"shift_key": shift_key},
    )
    assert res6.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert res6.headers["content-type"].startswith("application/problem+json")
    assert "Retry-After" in res6.headers
    retry_after = int(res6.headers["Retry-After"])
    assert 0 < retry_after <= 600

    problem = ProblemDetails.model_validate(res6.json())
    assert problem.status == 429
    assert problem.title == "Too Many Requests"
    assert "5 requests per 10 minutes" in problem.detail
    assert "Vertex AI" in problem.detail
    assert problem.trace_id is not None


def test_rate_limit_sliding_window_expiration(
    test_settings: Settings,
) -> None:
    """AC-1: Once the window duration elapses, requests are accepted again."""
    limiter = RateLimiter()
    limiter.reset()

    # Create mock Request
    mock_request = MagicMock(spec=Request)
    mock_request.headers = {"x-forwarded-for": "198.51.100.30"}
    mock_request.client = None

    t0 = 1000000.0
    # Send 5 requests at t0
    for _ in range(5):
        limiter.check_and_record(mock_request, test_settings, now=t0)

    # 6th request at t0 + 10s is blocked
    with pytest.raises(RateLimitExceededException) as exc_info:
        limiter.check_and_record(mock_request, test_settings, now=t0 + 10.0)
    assert exc_info.value.status_code == 429

    # Advance time past window (600s): at t0 + 601s, request succeeds
    limiter.check_and_record(mock_request, test_settings, now=t0 + 601.0)
    stats = limiter.get_stats()
    assert stats["tracked_ips_window"] == 1


def test_different_client_ips_have_independent_windows(
    client: TestClient, db_session: Session
) -> None:
    """Client A reaching limit does not block Client B."""
    shift_key = "2026-11-14-early"
    _seed_event(db_session, shift_key)

    client_a_headers = {"X-Forwarded-For": "203.0.113.1"}
    client_b_headers = {"X-Forwarded-For": "203.0.113.2"}

    # Exhaust Client A's quota
    for _ in range(5):
        resp = client.post(
            "/api/reports/generate",
            headers=client_a_headers,
            json={"shift_key": shift_key},
        )
        assert resp.status_code == status.HTTP_201_CREATED

    # Client A is rate limited
    blocked_a = client.post(
        "/api/reports/generate",
        headers=client_a_headers,
        json={"shift_key": shift_key},
    )
    assert blocked_a.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    # Client B can still generate reports
    resp_b = client.post(
        "/api/reports/generate",
        headers=client_b_headers,
        json={"shift_key": shift_key},
    )
    assert resp_b.status_code == status.HTTP_201_CREATED


# ---------------------------------------------------------------------------
# 2. Per-User Lifetime Cap (20 Requests Total per Client IP)
# ---------------------------------------------------------------------------


def test_per_user_lifetime_cap_enforcement(test_settings: Settings) -> None:
    """AC-2: A user can generate at most 20 reports in total across time windows."""
    limiter = RateLimiter()
    limiter.reset()

    mock_request = MagicMock(spec=Request)
    mock_request.headers = {"x-forwarded-for": "198.51.100.50"}
    mock_request.client = None

    # Simulate 4 separate time windows of 5 requests each = 20 total
    base_time = 100000.0
    for window in range(4):
        window_time = base_time + (window * 1000.0)
        for req in range(5):
            limiter.check_and_record(
                mock_request, test_settings, now=window_time + req
            )

    # 21st request in a new window hits the per-user lifetime cap
    future_time = base_time + 10000.0
    with pytest.raises(RateLimitExceededException) as exc_info:
        limiter.check_and_record(mock_request, test_settings, now=future_time)
    assert exc_info.value.status_code == 429
    assert "Per-user lifetime generation cap reached (maximum 20 reports)" in exc_info.value.detail


# ---------------------------------------------------------------------------
# 3. Global Total Lifetime Request Cap (20 Requests Total)
# ---------------------------------------------------------------------------


def test_global_cap_enforcement_across_different_ips(
    test_settings: Settings,
) -> None:
    """AC-2: Total generation requests across all users cannot exceed global cap (20)."""
    limiter = RateLimiter()
    limiter.reset()

    # 20 different users generate 1 report each
    for i in range(20):
        req = MagicMock(spec=Request)
        req.headers = {"x-forwarded-for": f"10.0.0.{i + 1}"}
        req.client = None
        limiter.check_and_record(req, test_settings, now=1000.0 + i)

    # The 21st user is rejected with global cap explanation
    new_user_req = MagicMock(spec=Request)
    new_user_req.headers = {"x-forwarded-for": "10.0.0.99"}
    new_user_req.client = None

    with pytest.raises(RateLimitExceededException) as exc_info:
        limiter.check_and_record(new_user_req, test_settings, now=2000.0)
    assert exc_info.value.status_code == 429
    assert "Global report generation budget cap reached (maximum 20 reports)" in exc_info.value.detail


# ---------------------------------------------------------------------------
# 4. Strict Universal Enforcement — NO Admin Token Bypass
# ---------------------------------------------------------------------------


def test_admin_token_cannot_bypass_per_ip_rate_limit(
    client: TestClient, db_session: Session
) -> None:
    """AC-3: Admin tokens MUST NOT bypass the per-IP sliding window rate limit."""
    shift_key = "2026-11-14-early"
    _seed_event(db_session, shift_key)

    headers = {
        "X-Forwarded-For": "198.51.100.77",
        "Authorization": f"Bearer {DEFAULT_ADMIN_TOKEN}",
    }

    # Generate 5 reports with Admin token
    for i in range(5):
        resp = client.post(
            "/api/reports/generate",
            headers=headers,
            json={"shift_key": shift_key},
        )
        assert resp.status_code == status.HTTP_201_CREATED

    # 6th report with Admin token is still rejected with 429
    res6 = client.post(
        "/api/reports/generate",
        headers=headers,
        json={"shift_key": shift_key},
    )
    assert res6.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    problem = ProblemDetails.model_validate(res6.json())
    assert problem.status == 429
    assert "5 requests per 10 minutes" in problem.detail


def test_admin_token_cannot_bypass_global_cap(test_settings: Settings) -> None:
    """AC-3: Admin tokens MUST NOT bypass the global budget cap."""
    limiter = RateLimiter()
    limiter.reset()

    # Reach global cap
    for i in range(20):
        req = MagicMock(spec=Request)
        req.headers = {
            "x-forwarded-for": f"10.1.0.{i + 1}",
            "authorization": f"Bearer {DEFAULT_ADMIN_TOKEN}",
        }
        req.client = None
        limiter.check_and_record(req, test_settings, now=100.0 + i)

    # Next admin request is rejected
    admin_req = MagicMock(spec=Request)
    admin_req.headers = {
        "x-forwarded-for": "10.1.0.21",
        "authorization": f"Bearer {DEFAULT_ADMIN_TOKEN}",
    }
    admin_req.client = None

    with pytest.raises(RateLimitExceededException) as exc_info:
        limiter.check_and_record(admin_req, test_settings, now=200.0)
    assert exc_info.value.status_code == 429
    assert "Global report generation budget cap reached" in exc_info.value.detail


# ---------------------------------------------------------------------------
# 5. Testing Flag: rate_limit_enabled = False
# ---------------------------------------------------------------------------


def test_rate_limit_disabled_setting_bypasses_all_checks(
    client: TestClient, db_session: Session
) -> None:
    """AC-3: When rate_limit_enabled=False, requests are not limited."""
    shift_key = "2026-11-14-early"
    _seed_event(db_session, shift_key)

    disabled_settings = Settings(
        admin_token=DEFAULT_ADMIN_TOKEN,
        rate_limit_enabled=False,
        rate_limit_max_requests=2,
        rate_limit_global_cap=2,
    )

    test_app = create_app()
    test_app.dependency_overrides[get_db] = lambda: db_session
    test_app.dependency_overrides[get_settings] = lambda: disabled_settings

    with TestClient(test_app) as custom_client:
        headers = {"X-Forwarded-For": "198.51.100.88"}
        # Send 5 requests (exceeding max_requests=2 and global_cap=2)
        for i in range(5):
            res = custom_client.post(
                "/api/reports/generate",
                headers=headers,
                json={"shift_key": shift_key},
            )
            assert res.status_code == status.HTTP_201_CREATED, f"Request {i + 1} failed"


# ---------------------------------------------------------------------------
# 6. Client IP Extraction
# ---------------------------------------------------------------------------


def test_extract_client_ip_from_x_forwarded_for_chain() -> None:
    """Verifies client IP extraction from multiple proxy hops in X-Forwarded-For."""
    req = MagicMock(spec=Request)
    req.headers = {"x-forwarded-for": "  203.0.113.195  , 70.41.3.18, 150.172.238.178 "}
    req.client = None
    assert extract_client_ip(req) == "203.0.113.195"


def test_extract_client_ip_fallback_to_client_host() -> None:
    """Verifies fallback to request.client.host when header is absent."""
    req = MagicMock(spec=Request)
    req.headers = {}
    mock_client = MagicMock()
    mock_client.host = "192.168.1.100"
    req.client = mock_client
    assert extract_client_ip(req) == "192.168.1.100"


def test_extract_client_ip_fallback_unknown() -> None:
    """Verifies fallback to 127.0.0.1 when both header and client are absent."""
    req = MagicMock(spec=Request)
    req.headers = {}
    req.client = None
    assert extract_client_ip(req) == "127.0.0.1"


# ---------------------------------------------------------------------------
# 7. OpenTelemetry Metric Recording
# ---------------------------------------------------------------------------


def test_rate_limit_records_429_http_metric(
    client: TestClient, db_session: Session
) -> None:
    """AC-5: Emits OpenTelemetry metric for rate limit rejection."""
    shift_key = "2026-11-14-early"
    _seed_event(db_session, shift_key)

    headers = {"X-Forwarded-For": "198.51.100.99"}
    # Exhaust 5
    for _ in range(5):
        client.post(
            "/api/reports/generate",
            headers=headers,
            json={"shift_key": shift_key},
        )

    # Trigger 429
    res = client.post(
        "/api/reports/generate",
        headers=headers,
        json={"shift_key": shift_key},
    )
    assert res.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    # Verify metric reader captured 429
    reader = get_in_memory_metric_reader()
    if reader:
        metric_data = reader.get_metrics_data()
        found_429 = False
        for rm in metric_data.resource_metrics:
            for sm in rm.scope_metrics:
                for metric in sm.metrics:
                    if metric.name == "handover_http_requests_total":
                        for point in metric.data.data_points:
                            if point.attributes.get("status_code") == "429":
                                found_429 = True
                                assert point.value >= 1
        assert found_429, "Metric handover_http_requests_total with status_code=429 not found"


# ---------------------------------------------------------------------------
# 8. Thread Safety & Concurrency
# ---------------------------------------------------------------------------


def test_rate_limiter_thread_safety(test_settings: Settings) -> None:
    """Verify thread-safe accounting when multiple concurrent threads call check_and_record."""
    limiter = RateLimiter()
    limiter.reset()

    num_threads = 10
    requests_per_thread = 2
    # Total = 20 (hits global cap exactly)

    def worker(worker_id: int):
        req = MagicMock(spec=Request)
        req.headers = {"x-forwarded-for": f"172.16.0.{worker_id}"}
        req.client = None
        for r in range(requests_per_thread):
            limiter.check_and_record(req, test_settings, now=1000.0 + r)

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, i) for i in range(num_threads)]
        for f in futures:
            f.result()

    stats = limiter.get_stats()
    assert stats["global_count"] == 20

    # 21st concurrent call is rejected
    req_extra = MagicMock(spec=Request)
    req_extra.headers = {"x-forwarded-for": "172.16.0.99"}
    req_extra.client = None
    with pytest.raises(RateLimitExceededException):
        limiter.check_and_record(req_extra, test_settings, now=2000.0)


# ---------------------------------------------------------------------------
# 9. Automatic Memory Pruning
# ---------------------------------------------------------------------------


def test_rate_limiter_prunes_expired_timestamps(test_settings: Settings) -> None:
    """Verify memory cleanup of expired timestamps."""
    limiter = RateLimiter()
    limiter.reset()

    # Add 10 different IPs at t = 1000.0
    for i in range(10):
        req = MagicMock(spec=Request)
        req.headers = {"x-forwarded-for": f"10.200.0.{i}"}
        req.client = None
        limiter.check_and_record(req, test_settings, now=1000.0)

    assert limiter.get_stats()["tracked_ips_window"] == 10

    # Manually invoke prune at t = 2000.0 (past window_seconds=600)
    with limiter._lock:
        limiter._prune_expired_locked(2000.0 - test_settings.rate_limit_window_seconds)

    assert limiter.get_stats()["tracked_ips_window"] == 0
