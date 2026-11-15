"""Pytest integration tests verifying all 7 Docker Compose scenarios against a live container stack.

When the container is running on http://127.0.0.1:8000 (or APP_BASE_URL), these tests execute against
the live deployment stack. If the stack is not running and TEST_COMPOSE_INTEGRATION is not set,
these tests are skipped cleanly so that standard backend unit test runs remain fast and isolated.
"""

import os
from pathlib import Path
import sys
import urllib.request
import pytest

# Ensure scripts directory is available for importing the test suite
repo_root = Path(__file__).resolve().parent.parent.parent
scripts_dir = repo_root / "scripts"
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from test_compose_integration import (
    DEFAULT_ADMIN_TOKEN,
    DEFAULT_BASE_URL,
    DEFAULT_RELAY_TOKEN,
    ComposeIntegrationTestSuite,
)

BASE_URL = os.environ.get("APP_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
FORCE_RUN = os.environ.get("TEST_COMPOSE_INTEGRATION") == "1"


def is_compose_stack_healthy() -> bool:
    """Check if the live container stack is running and healthy."""
    try:
        url = f"{BASE_URL}/api/healthz"
        with urllib.request.urlopen(url, timeout=2.0) as resp:
            return resp.status == 200
    except Exception:
        return False


COMPOSE_RUNNING = is_compose_stack_healthy()

pytestmark = pytest.mark.skipif(
    not (FORCE_RUN or COMPOSE_RUNNING),
    reason="Docker Compose container is not running on http://127.0.0.1:8000. Set TEST_COMPOSE_INTEGRATION=1 or start stack with 'docker compose up -d'.",
)


@pytest.fixture(scope="module")
def suite() -> ComposeIntegrationTestSuite:
    """Shared suite instance running the scenarios sequentially."""
    return ComposeIntegrationTestSuite(
        base_url=BASE_URL,
        admin_token=os.environ.get("ADMIN_TOKEN", DEFAULT_ADMIN_TOKEN),
        relay_token=os.environ.get("RELAY_WEBHOOK_TOKEN", DEFAULT_RELAY_TOKEN),
        skip_restart=False,
    )


def test_scenario_1_boot_and_spa(suite: ComposeIntegrationTestSuite) -> None:
    suite.run_scenario_1_boot_and_spa()


def test_scenario_2_events_lifecycle(suite: ComposeIntegrationTestSuite) -> None:
    suite.run_scenario_2_events_lifecycle()


def test_scenario_3_report_generation(suite: ComposeIntegrationTestSuite) -> None:
    suite.run_scenario_3_report_generation()


def test_scenario_4_version_progression(suite: ComposeIntegrationTestSuite) -> None:
    suite.run_scenario_4_version_progression()


def test_scenario_5_admin_settings(suite: ComposeIntegrationTestSuite) -> None:
    suite.run_scenario_5_admin_settings()


def test_scenario_6_database_persistence(suite: ComposeIntegrationTestSuite) -> None:
    suite.run_scenario_6_database_persistence()


def test_scenario_7_webhook_relay(suite: ComposeIntegrationTestSuite) -> None:
    suite.run_scenario_7_webhook_relay()
