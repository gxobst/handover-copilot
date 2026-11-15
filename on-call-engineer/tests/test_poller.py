"""Unit and integration tests for on-call engineer alert polling and agent dispatch."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import MagicMock, patch
import urllib.error

import pytest

# Ensure on-call-engineer package is importable
PKG_DIR = Path(__file__).resolve().parent.parent
if str(PKG_DIR) not in sys.path:
    sys.path.insert(0, str(PKG_DIR))

from config import (
    DEFAULT_ALERT_URL,
    DEFAULT_COOLDOWN,
    DEFAULT_POLL_INTERVAL,
    PollerConfig,
    build_arg_parser,
    parse_config,
)
from dispatcher import (
    VERBATIM_SYSTEM_PROMPT,
    AgentDispatcher,
    DispatchResult,
    build_full_agent_prompt,
)
from models import AlertContext, AlertTrackedState, compute_alert_fingerprint
from poller import AlertPoller

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


# 1. Verbatim System Prompt Verification
def test_verbatim_system_prompt_exact_match():
    """Verify system prompt exactly matches the required specification byte-for-byte."""
    expected = (
        "You are the on-call engineer for this repository. An alert just fired.\n\n"
        "Investigate the root cause. Read the code and reproduce the failure.\n"
        "If you find a real bug, make the smallest correction, run the backend tests,\n"
        "and commit the fix with a clear message.\n\n"
        "If the alert is a false positive, explain why and do not change the code."
    )
    assert VERBATIM_SYSTEM_PROMPT == expected

    # Verify key phrases are strictly present
    assert "You are the on-call engineer for this repository. An alert just fired." in VERBATIM_SYSTEM_PROMPT
    assert "Investigate the root cause. Read the code and reproduce the failure." in VERBATIM_SYSTEM_PROMPT
    assert "If you find a real bug, make the smallest correction, run the backend tests," in VERBATIM_SYSTEM_PROMPT
    assert "and commit the fix with a clear message." in VERBATIM_SYSTEM_PROMPT
    assert "If the alert is a false positive, explain why and do not change the code." in VERBATIM_SYSTEM_PROMPT


# 2. Configuration & CLI Argument Parsing
def test_config_defaults():
    """Verify default configuration values."""
    config = parse_config([])
    assert config.alert_url == DEFAULT_ALERT_URL
    assert config.interval_seconds == DEFAULT_POLL_INTERVAL
    assert config.cooldown_seconds == DEFAULT_COOLDOWN
    assert config.agent_cmd == "agy"
    assert config.alert_file is None
    assert config.once is False
    assert config.dry_run is False


def test_config_cli_overrides():
    """Verify CLI arguments override defaults."""
    args = [
        "--alert-url", "http://custom-host:9090/api/v1/alerts",
        "--interval", "30",
        "--cooldown", "600",
        "--agent-cmd", "claude --headless",
        "--alert-file", "mock.json",
        "--once",
        "--dry-run",
        "-v",
    ]
    config = parse_config(args)
    assert config.alert_url == "http://custom-host:9090/api/v1/alerts"
    assert config.interval_seconds == 30
    assert config.cooldown_seconds == 600
    assert config.agent_cmd == "claude --headless"
    assert config.alert_file == "mock.json"
    assert config.once is True
    assert config.dry_run is True
    assert config.verbose is True


def test_config_env_vars(monkeypatch):
    """Verify environment variables act as fallbacks when CLI arguments are omitted."""
    monkeypatch.setenv("ALERT_API_URL", "http://env-host:9090/api/v1/alerts")
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "45")
    monkeypatch.setenv("ALERT_COOLDOWN_SECONDS", "300")
    monkeypatch.setenv("AGENT_CMD", "gemini-runner")
    monkeypatch.setenv("ALERT_MOCK_FILE", "env_mock.json")

    config = parse_config([])
    assert config.alert_url == "http://env-host:9090/api/v1/alerts"
    assert config.interval_seconds == 45
    assert config.cooldown_seconds == 300
    assert config.agent_cmd == "gemini-runner"
    assert config.alert_file == "env_mock.json"


# 3. Structured Alert Context & Fingerprinting
def test_compute_alert_fingerprint():
    """Verify deterministic alert fingerprint generation."""
    labels_a = {"alertname": "TestAlert", "environment": "prod", "service": "api"}
    labels_b = {"service": "api", "environment": "prod", "alertname": "TestAlert"}
    labels_diff = {"alertname": "TestAlert", "environment": "dev", "service": "api"}

    fp_a = compute_alert_fingerprint(labels_a, "TestAlert")
    fp_b = compute_alert_fingerprint(labels_b, "TestAlert")
    fp_diff = compute_alert_fingerprint(labels_diff, "TestAlert")

    assert fp_a == fp_b
    assert fp_a != fp_diff
    assert len(fp_a) == 16

    # Explicit fingerprint overrides
    explicit = compute_alert_fingerprint(labels_a, explicit_fingerprint="explicit-12345")
    assert explicit == "explicit-12345"


def test_alert_context_structure():
    """Verify structured AlertContext contains all required attributes and serializations."""
    ctx = AlertContext(
        alertname="HandoverGenerationFailureRateHigh",
        environment="prod",
        version="v1.2.3",
        severity="critical",
        summary="High report generation failure rate",
        description="Shift leads cannot generate handovers",
        dashboard_url="http://dashboard.local/123",
        runbook_url="http://runbook.local/456",
        firing_timestamp="2026-11-15T18:00:00Z",
        labels={"environment": "prod", "severity": "critical", "version": "v1.2.3"},
        annotations={"summary": "High failure", "runbook_url": "http://runbook.local/456"},
        fingerprint="fp-test-1",
    )

    data = ctx.to_dict()
    for req_field in [
        "alertname",
        "environment",
        "version",
        "severity",
        "summary",
        "description",
        "dashboard_url",
        "runbook_url",
        "firing_timestamp",
        "labels",
        "annotations",
        "fingerprint",
    ]:
        assert req_field in data

    json_str = ctx.to_json()
    assert "HandoverGenerationFailureRateHigh" in json_str

    full_prompt = build_full_agent_prompt(ctx)
    assert VERBATIM_SYSTEM_PROMPT in full_prompt
    assert "HandoverGenerationFailureRateHigh" in full_prompt
    assert "http://dashboard.local/123" in full_prompt
    assert "http://runbook.local/456" in full_prompt


# 4. Poller Filtering & Dispatch
def test_poller_empty_alerts():
    """Verify empty alerts response produces zero dispatches."""
    config = PollerConfig(alert_file=str(FIXTURES_DIR / "empty_alerts.json"), dry_run=True, once=True)
    poller = AlertPoller(config)
    dispatched = poller.poll_cycle()
    assert len(dispatched) == 0


def test_poller_pending_and_resolved_ignored():
    """Verify pending and resolved alerts are filtered out and not dispatched."""
    # Pending
    config_pending = PollerConfig(alert_file=str(FIXTURES_DIR / "pending_alert.json"), dry_run=True, once=True)
    poller_pending = AlertPoller(config_pending)
    dispatched_pending = poller_pending.poll_cycle()
    assert len(dispatched_pending) == 0

    # Resolved
    config_resolved = PollerConfig(alert_file=str(FIXTURES_DIR / "resolved_alert.json"), dry_run=True, once=True)
    poller_resolved = AlertPoller(config_resolved)
    dispatched_resolved = poller_resolved.poll_cycle()
    assert len(dispatched_resolved) == 0


def test_poller_single_firing_alert_dispatch():
    """Verify firing alert triggers agent dispatch with structured context and verbatim prompt."""
    config = PollerConfig(alert_file=str(FIXTURES_DIR / "firing_single.json"), dry_run=True, once=True)
    poller = AlertPoller(config)
    dispatched = poller.poll_cycle()

    assert len(dispatched) == 1
    res = dispatched[0]
    assert res.success is True
    assert res.dry_run is True
    assert res.context.alertname == "HandoverGenerationFailureRateHigh"
    assert res.context.environment == "prod"
    assert res.context.version == "v1.2.3"
    assert res.context.severity == "critical"
    assert "http://34.153.185.34:3000/d/handover-app-metrics" in res.context.dashboard_url
    assert "manual-testing-guide.md" in res.context.runbook_url
    assert VERBATIM_SYSTEM_PROMPT in res.prompt


def test_poller_deduplication_and_cooldown():
    """Verify duplicate alerts within the cooldown window do not re-dispatch."""
    config = PollerConfig(
        alert_file=str(FIXTURES_DIR / "firing_single.json"),
        cooldown_seconds=900,
        dry_run=True,
    )
    poller = AlertPoller(config)

    # First poll cycle: fires and dispatches
    cycle1 = poller.poll_cycle()
    assert len(cycle1) == 1
    fp = cycle1[0].context.fingerprint
    assert poller.tracker[fp].dispatch_count == 1

    # Second poll cycle immediately after: in cooldown window -> suppressed
    cycle2 = poller.poll_cycle()
    assert len(cycle2) == 0
    assert poller.tracker[fp].dispatch_count == 1

    # Third poll cycle after cooldown expired: dispatches again
    poller.tracker[fp].last_dispatched_at = time.time() - 901
    cycle3 = poller.poll_cycle()
    assert len(cycle3) == 1
    assert poller.tracker[fp].dispatch_count == 2


def test_poller_in_flight_protection():
    """Verify in-flight alerts are suppressed from duplicate dispatch."""
    config = PollerConfig(alert_file=str(FIXTURES_DIR / "firing_single.json"), dry_run=True)
    poller = AlertPoller(config)

    # Pretend alert is already in-flight
    payload = poller.fetch_raw_payload()
    firing = poller.extract_firing_alerts(payload)
    fp = firing[0].fingerprint
    poller.tracker[fp] = AlertTrackedState(
        fingerprint=fp,
        alertname=firing[0].alertname,
        first_seen_at=time.time(),
        last_seen_at=time.time(),
        in_flight=True,
    )

    dispatched = poller.poll_cycle()
    assert len(dispatched) == 0


def test_poller_multiple_firing_alerts_sequential():
    """Verify multiple distinct firing alerts in a single poll are dispatched sequentially."""
    config = PollerConfig(alert_file=str(FIXTURES_DIR / "firing_multiple.json"), dry_run=True)
    poller = AlertPoller(config)

    dispatched = poller.poll_cycle()
    assert len(dispatched) == 2

    alert_names = [d.context.alertname for d in dispatched]
    assert "HandoverGenerationFailureRateHigh" in alert_names
    assert "HandoverHttpErrorRateHigh" in alert_names

    # Check each has independent tracking and cooldown
    for d in dispatched:
        fp = d.context.fingerprint
        assert fp in poller.tracker
        assert poller.tracker[fp].dispatch_count == 1

    # Subsequent poll suppresses both
    cycle2 = poller.poll_cycle()
    assert len(cycle2) == 0


def test_poller_resolution_transition_logging(caplog):
    """Verify transition from firing to resolved/absent updates state and logs resolution."""
    config = PollerConfig(alert_file=str(FIXTURES_DIR / "firing_single.json"), dry_run=True)
    poller = AlertPoller(config)

    # Poll 1: Firing
    dispatched = poller.poll_cycle()
    assert len(dispatched) == 1
    fp = dispatched[0].context.fingerprint
    assert poller.tracker[fp].last_state == "firing"

    # Poll 2: Now payload is empty (alert resolved or disappeared)
    poller.config.alert_file = str(FIXTURES_DIR / "empty_alerts.json")
    with caplog.at_level("INFO"):
        cycle2 = poller.poll_cycle()
        assert len(cycle2) == 0
        assert poller.tracker[fp].last_state == "resolved"
        assert "transitioned from firing to resolved/absent" in caplog.text


# 5. Robustness & Error Handling
def test_unreachable_api_handling():
    """Verify network connection errors and non-200 responses do not crash the poller."""
    config = PollerConfig(alert_url="http://127.0.0.1:59999/api/v1/alerts", dry_run=True, once=True)
    poller = AlertPoller(config)

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        dispatched = poller.poll_cycle()
        assert len(dispatched) == 0


def test_http_500_api_handling():
    """Verify HTTP 500 error from API is logged without crashing."""
    config = PollerConfig(alert_url="http://test-server/api/v1/alerts", dry_run=True, once=True)
    poller = AlertPoller(config)

    http_error = urllib.error.HTTPError("http://test-server", 500, "Internal Server Error", {}, None)
    with patch("urllib.request.urlopen", side_effect=http_error):
        dispatched = poller.poll_cycle()
        assert len(dispatched) == 0


def test_malformed_json_handling():
    """Verify corrupt JSON payload does not crash poller."""
    config = PollerConfig(alert_file=str(FIXTURES_DIR / "malformed.json"), dry_run=True, once=True)
    poller = AlertPoller(config)
    dispatched = poller.poll_cycle()
    assert len(dispatched) == 0


# 6. Real Subprocess Dispatcher Test (Simulated Agent)
def test_dispatcher_subprocess_invocation():
    """Verify AgentDispatcher invokes child command with environment variables and prompt via stdin."""
    mock_runner_code = (
        "import sys, os; "
        "stdin_text = sys.stdin.read(); "
        "sys_prompt = os.environ.get('ON_CALL_SYSTEM_PROMPT', ''); "
        "alert_name = os.environ.get('ON_CALL_ALERT_NAME', ''); "
        "assert 'You are the on-call engineer' in sys_prompt; "
        "assert 'HandoverGenerationFailureRateHigh' in alert_name; "
        "assert 'HandoverGenerationFailureRateHigh' in stdin_text; "
        "print('MOCK_DISPATCH_SUCCESS')"
    )

    cmd = f'python -c "{mock_runner_code}"'
    dispatcher = AgentDispatcher(agent_cmd=cmd, dry_run=False)

    ctx = AlertContext(
        alertname="HandoverGenerationFailureRateHigh",
        environment="prod",
        version="v1.2.3",
        severity="critical",
        summary="High failure rate",
        description="Shift leads cannot generate handovers",
        dashboard_url="",
        runbook_url="",
        firing_timestamp="2026-11-15T18:00:00Z",
        fingerprint="fp-12345",
    )

    res = dispatcher.dispatch(ctx)
    assert res.success is True
    assert res.return_code == 0
    assert "MOCK_DISPATCH_SUCCESS" in res.output


# 7. CLI Execution via Subprocess
def test_cli_execution_once_dry_run():
    """Verify running poll_alerts.py as a script with --once and --dry-run completes cleanly."""
    script_path = PKG_DIR / "poll_alerts.py"
    fixture_path = FIXTURES_DIR / "firing_single.json"

    res = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--alert-file", str(fixture_path),
            "--once",
            "--dry-run",
            "-v",
        ],
        capture_output=True,
        text=True,
        cwd=str(PKG_DIR),
    )

    assert res.returncode == 0
    assert "Simulated dispatch for alert 'HandoverGenerationFailureRateHigh'" in res.stderr or "Simulated dispatch for alert 'HandoverGenerationFailureRateHigh'" in res.stdout
    assert "Single-run (--once) complete. Exiting cleanly." in res.stderr or "Single-run (--once) complete. Exiting cleanly." in res.stdout
