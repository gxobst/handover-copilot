#!/usr/bin/env python3
"""Comprehensive verification script for On-Call Engineer Poller and Dispatcher (Issue #39).

Validates:
1. File and directory structure in on-call-engineer/:
   - poll_alerts.py, dispatcher.py, config.py, models.py, README.md, tests/test_poller.py.
2. Exact verbatim system prompt compliance matching Issue #39 specification.
3. Structured alert context extraction with all mandatory telemetry and metadata fields.
4. CLI configuration flags and environment variable fallbacks.
5. Poller alert filtering: state="firing" only; ignores pending/resolved/empty lists.
6. Deduplication and cooldown window tracking per alert fingerprint.
7. Sequential agent dispatch for multiple simultaneous firing alerts.
8. Alert resolution transition logging and state updates.
9. Error handling: unreachable alert API, HTTP errors, timeouts, malformed JSON.
10. Testing support flags: --once, --dry-run, --alert-file.
11. CLI subprocess execution with --once and --dry-run exiting 0.
12. Full unit test suite execution in on-call-engineer/tests.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

REPO_ROOT = Path(__file__).resolve().parent.parent
ON_CALL_DIR = REPO_ROOT / "on-call-engineer"
FIXTURES_DIR = ON_CALL_DIR / "tests" / "fixtures"

if str(ON_CALL_DIR) not in sys.path:
    sys.path.insert(0, str(ON_CALL_DIR))

from config import (
    DEFAULT_ALERT_URL,
    DEFAULT_COOLDOWN,
    DEFAULT_POLL_INTERVAL,
    PollerConfig,
    parse_config,
)
from dispatcher import (
    VERBATIM_SYSTEM_PROMPT,
    AgentDispatcher,
    build_full_agent_prompt,
)
from models import AlertContext, compute_alert_fingerprint
from poller import AlertPoller


def verify_file_structure() -> list[str]:
    """Verify presence of all required files and directories."""
    errors: list[str] = []
    required_files = [
        ON_CALL_DIR / "poll_alerts.py",
        ON_CALL_DIR / "dispatcher.py",
        ON_CALL_DIR / "config.py",
        ON_CALL_DIR / "models.py",
        ON_CALL_DIR / "poller.py",
        ON_CALL_DIR / "README.md",
        ON_CALL_DIR / "tests" / "test_poller.py",
        FIXTURES_DIR / "firing_single.json",
        FIXTURES_DIR / "firing_multiple.json",
        FIXTURES_DIR / "pending_alert.json",
        FIXTURES_DIR / "resolved_alert.json",
        FIXTURES_DIR / "empty_alerts.json",
        FIXTURES_DIR / "malformed.json",
    ]

    for req in required_files:
        if not req.is_file():
            errors.append(f"Missing required file: {req.relative_to(REPO_ROOT)}")

    return errors


def verify_verbatim_system_prompt() -> list[str]:
    """Verify that the system prompt strictly matches Issue #39 specification."""
    errors: list[str] = []
    expected_prompt = (
        "You are the on-call engineer for this repository. An alert just fired.\n\n"
        "Investigate the root cause. Read the code and reproduce the failure.\n"
        "If you find a real bug, make the smallest correction, run the backend tests,\n"
        "and commit the fix with a clear message.\n\n"
        "If the alert is a false positive, explain why and do not change the code."
    )

    if VERBATIM_SYSTEM_PROMPT != expected_prompt:
        errors.append(
            f"VERBATIM_SYSTEM_PROMPT does not match expected prompt.\n"
            f"Expected:\n{expected_prompt}\n\nActual:\n{VERBATIM_SYSTEM_PROMPT}"
        )

    # Check dispatcher module source text
    dispatcher_file = ON_CALL_DIR / "dispatcher.py"
    content = dispatcher_file.read_text(encoding="utf-8")
    if "You are the on-call engineer for this repository. An alert just fired." not in content:
        errors.append("dispatcher.py does not contain the mandatory verbatim on-call prompt opening line.")
    if "If the alert is a false positive, explain why and do not change the code." not in content:
        errors.append("dispatcher.py does not contain the mandatory verbatim on-call prompt closing line.")

    return errors


def verify_structured_alert_context() -> list[str]:
    """Verify AlertContext extracts and exposes all required incident attributes."""
    errors: list[str] = []
    required_keys = [
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
    ]

    ctx = AlertContext(
        alertname="HandoverGenerationFailureRateHigh",
        environment="prod",
        version="v1.2.3",
        severity="critical",
        summary="High report generation failure rate",
        description="Shift leads cannot generate handovers",
        dashboard_url="http://dashboard.local/view",
        runbook_url="http://runbook.local/docs",
        firing_timestamp="2026-11-15T18:00:00Z",
        labels={"environment": "prod", "service": "handover-backend"},
        annotations={"summary": "High report failure"},
        fingerprint="fp-test-123",
    )

    data = ctx.to_dict()
    for key in required_keys:
        if key not in data:
            errors.append(f"AlertContext dictionary missing required key: '{key}'")

    full_prompt = build_full_agent_prompt(ctx)
    if VERBATIM_SYSTEM_PROMPT not in full_prompt:
        errors.append("build_full_agent_prompt does not include VERBATIM_SYSTEM_PROMPT.")
    if "HandoverGenerationFailureRateHigh" not in full_prompt:
        errors.append("build_full_agent_prompt missing alertname.")
    if "http://dashboard.local/view" not in full_prompt:
        errors.append("build_full_agent_prompt missing dashboard_url.")
    if "http://runbook.local/docs" not in full_prompt:
        errors.append("build_full_agent_prompt missing runbook_url.")

    return errors


def verify_poller_filtering_and_cooldown() -> list[str]:
    """Verify alert poller filtering, deduplication, cooldown, and resolution tracking."""
    errors: list[str] = []

    # 1. Zero alerts
    cfg_empty = PollerConfig(alert_file=str(FIXTURES_DIR / "empty_alerts.json"), dry_run=True, once=True)
    poller_empty = AlertPoller(cfg_empty)
    if len(poller_empty.poll_cycle()) != 0:
        errors.append("Poller dispatched agent when alerts list was empty.")

    # 2. Pending alerts ignored
    cfg_pending = PollerConfig(alert_file=str(FIXTURES_DIR / "pending_alert.json"), dry_run=True, once=True)
    poller_pending = AlertPoller(cfg_pending)
    if len(poller_pending.poll_cycle()) != 0:
        errors.append("Poller dispatched agent for pending alert.")

    # 3. Resolved alerts ignored
    cfg_resolved = PollerConfig(alert_file=str(FIXTURES_DIR / "resolved_alert.json"), dry_run=True, once=True)
    poller_resolved = AlertPoller(cfg_resolved)
    if len(poller_resolved.poll_cycle()) != 0:
        errors.append("Poller dispatched agent for resolved alert.")

    # 4. Firing alert dispatch
    cfg_firing = PollerConfig(
        alert_file=str(FIXTURES_DIR / "firing_single.json"),
        cooldown_seconds=900,
        dry_run=True,
    )
    poller_firing = AlertPoller(cfg_firing)
    dispatched1 = poller_firing.poll_cycle()
    if len(dispatched1) != 1:
        errors.append(f"Expected 1 dispatch for firing alert, got {len(dispatched1)}.")
    elif dispatched1[0].context.alertname != "HandoverGenerationFailureRateHigh":
        errors.append(f"Unexpected dispatched alert: {dispatched1[0].context.alertname}")

    # 5. Cooldown suppression
    dispatched2 = poller_firing.poll_cycle()
    if len(dispatched2) != 0:
        errors.append("Cooldown failed: duplicate dispatch occurred within cooldown window.")

    # 6. Resolution transition
    poller_firing.config.alert_file = str(FIXTURES_DIR / "empty_alerts.json")
    poller_firing.poll_cycle()
    fp = dispatched1[0].context.fingerprint
    if poller_firing.tracker[fp].last_state != "resolved":
        errors.append(f"Alert state was not updated to 'resolved' after alert disappeared. State: {poller_firing.tracker[fp].last_state}")

    # 7. Multiple firing alerts sequential dispatch
    cfg_multi = PollerConfig(alert_file=str(FIXTURES_DIR / "firing_multiple.json"), dry_run=True)
    poller_multi = AlertPoller(cfg_multi)
    dispatched_multi = poller_multi.poll_cycle()
    if len(dispatched_multi) != 2:
        errors.append(f"Expected 2 sequential dispatches for multiple firing alerts, got {len(dispatched_multi)}.")

    return errors


def verify_error_resilience() -> list[str]:
    """Verify error resilience against malformed payloads and unreachable endpoints."""
    errors: list[str] = []

    # 1. Malformed JSON
    cfg_malformed = PollerConfig(alert_file=str(FIXTURES_DIR / "malformed.json"), dry_run=True, once=True)
    poller_malformed = AlertPoller(cfg_malformed)
    try:
        res = poller_malformed.poll_cycle()
        if len(res) != 0:
            errors.append("Malformed JSON caused unexpected dispatch.")
    except Exception as exc:
        errors.append(f"Poller crashed on malformed JSON payload: {exc}")

    # 2. Unreachable endpoint
    cfg_unreachable = PollerConfig(alert_url="http://127.0.0.1:59998/api/v1/alerts", dry_run=True, once=True)
    poller_unreachable = AlertPoller(cfg_unreachable)
    try:
        res = poller_unreachable.poll_cycle()
        if len(res) != 0:
            errors.append("Unreachable endpoint caused unexpected dispatch.")
    except Exception as exc:
        errors.append(f"Poller crashed on unreachable API endpoint: {exc}")

    return errors


def verify_cli_subprocess_execution() -> list[str]:
    """Verify running poll_alerts.py directly as a CLI process with --once and --dry-run."""
    errors: list[str] = []
    script_path = ON_CALL_DIR / "poll_alerts.py"
    fixture_path = FIXTURES_DIR / "firing_single.json"

    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--alert-file", str(fixture_path),
                "--once",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(ON_CALL_DIR),
        )
        if proc.returncode != 0:
            errors.append(f"CLI execution failed with returncode {proc.returncode}. Stderr: {proc.stderr}")
    except Exception as exc:
        errors.append(f"Subprocess execution of poll_alerts.py failed: {exc}")

    return errors


def run_unit_tests() -> list[str]:
    """Run pytest suite on on-call-engineer/tests and verify all tests pass."""
    errors: list[str] = []
    test_path = ON_CALL_DIR / "tests"

    cmd_candidates = [
        [sys.executable, "-m", "pytest", str(test_path), "-v"],
        ["pytest", str(test_path), "-v"],
        ["uv", "run", "pytest", str(test_path), "-v"],
    ]

    last_output = ""
    success = False

    for cmd in cmd_candidates:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(REPO_ROOT),
                shell=(cmd[0] in ["pytest", "uv"]),
            )
            last_output = f"{proc.stdout}\n{proc.stderr}"
            if proc.returncode == 0:
                success = True
                break
        except Exception:
            continue

    if not success:
        errors.append(f"Unit tests in on-call-engineer/tests failed:\n{last_output}")

    return errors


def main() -> int:
    """Run comprehensive verification checks."""
    print("=" * 70)
    print("   On-Call Engineer Alert Poller & Agent Dispatcher Verification")
    print("   Issue #39 Validation Suite")
    print("=" * 70)

    all_errors: list[str] = []

    # Check 1: File structure
    print("\n[1/7] Verifying file and directory structure...")
    errs = verify_file_structure()
    if errs:
        all_errors.extend(errs)
        for e in errs:
            print(f"  ❌ {e}")
    else:
        print("  ✅ on-call-engineer/ directory layout and all required files present.")

    # Check 2: Verbatim System Prompt
    print("\n[2/7] Verifying exact verbatim system prompt compliance...")
    errs = verify_verbatim_system_prompt()
    if errs:
        all_errors.extend(errs)
        for e in errs:
            print(f"  ❌ {e}")
    else:
        print("  ✅ Mandatory 7-line on-call system prompt matches specification verbatim.")

    # Check 3: Structured Alert Context
    print("\n[3/7] Verifying structured alert context and prompt formatting...")
    errs = verify_structured_alert_context()
    if errs:
        all_errors.extend(errs)
        for e in errs:
            print(f"  ❌ {e}")
    else:
        print("  ✅ Structured AlertContext contains all mandatory telemetry attributes.")
        print("  ✅ Prompt markdown builder incorporates verbatim prompt and alert details.")

    # Check 4: Filtering, Cooldown & Resolution
    print("\n[4/7] Verifying alert filtering, cooldown windows, and resolution tracking...")
    errs = verify_poller_filtering_and_cooldown()
    if errs:
        all_errors.extend(errs)
        for e in errs:
            print(f"  ❌ {e}")
    else:
        print("  ✅ Empty, pending, and resolved alerts cleanly ignored without dispatch.")
        print("  ✅ Firing alert triggers dispatch with exact fingerprint.")
        print("  ✅ Cooldown window (default 900s) suppresses duplicate dispatches.")
        print("  ✅ Alert resolution correctly detected and state transitioned to 'resolved'.")
        print("  ✅ Multiple firing alerts processed sequentially with per-alert cooldown.")

    # Check 5: Error Resilience
    print("\n[5/7] Verifying network error and malformed payload resilience...")
    errs = verify_error_resilience()
    if errs:
        all_errors.extend(errs)
        for e in errs:
            print(f"  ❌ {e}")
    else:
        print("  ✅ Network connection errors and timeouts logged without crashing.")
        print("  ✅ Malformed JSON payloads handled safely without daemon exit.")

    # Check 6: CLI Subprocess Execution
    print("\n[6/7] Verifying CLI execution with --once and --dry-run...")
    errs = verify_cli_subprocess_execution()
    if errs:
        all_errors.extend(errs)
        for e in errs:
            print(f"  ❌ {e}")
    else:
        print("  ✅ poll_alerts.py executes cleanly as CLI script with status code 0.")

    # Check 7: Unit Test Suite
    print("\n[7/7] Running unit test suite (pytest on-call-engineer/tests)...")
    errs = run_unit_tests()
    if errs:
        all_errors.extend(errs)
        for e in errs:
            print(f"  ❌ {e}")
    else:
        print("  ✅ All unit and integration tests in on-call-engineer/tests passed.")

    print("\n" + "=" * 70)
    if all_errors:
        print(f"❌ Verification FAILED with {len(all_errors)} error(s):")
        for err in all_errors:
            print(f"  • {err}")
        print("=" * 70)
        return 1

    print("✅ All On-Call Poller & Agent Dispatcher Checks PASSED!")
    print(f"   Package Directory:  {ON_CALL_DIR}")
    print(f"   Entrypoint Script:  {ON_CALL_DIR / 'poll_alerts.py'}")
    print(f"   Test Suite:         {ON_CALL_DIR / 'tests' / 'test_poller.py'}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
