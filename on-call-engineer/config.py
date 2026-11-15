"""Configuration and CLI argument parsing for on-call engineer poller."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
import sys

DEFAULT_ALERT_URL = "http://34.153.185.34:9090/api/v1/alerts"
DEFAULT_POLL_INTERVAL = 60
DEFAULT_COOLDOWN = 900
DEFAULT_AGENT_CMD = "agy"
DEFAULT_AGENT_TIMEOUT = 300


@dataclass
class PollerConfig:
    """Runtime configuration for the on-call alert polling daemon."""

    alert_url: str = DEFAULT_ALERT_URL
    interval_seconds: int = DEFAULT_POLL_INTERVAL
    cooldown_seconds: int = DEFAULT_COOLDOWN
    agent_cmd: str = DEFAULT_AGENT_CMD
    alert_file: str | None = None
    once: bool = False
    dry_run: bool = False
    verbose: bool = False
    agent_timeout_seconds: int = DEFAULT_AGENT_TIMEOUT


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct argument parser with environment variable fallbacks."""
    parser = argparse.ArgumentParser(
        prog="on-call-poller",
        description="Autonomous on-call alert polling daemon and headless agent dispatcher.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    env_alert_url = os.getenv("ALERT_API_URL", DEFAULT_ALERT_URL)
    env_interval = int(os.getenv("POLL_INTERVAL_SECONDS", str(DEFAULT_POLL_INTERVAL)))
    env_cooldown = int(os.getenv("ALERT_COOLDOWN_SECONDS", str(DEFAULT_COOLDOWN)))
    env_agent_cmd = os.getenv("AGENT_CMD", DEFAULT_AGENT_CMD)
    env_mock_file = os.getenv("ALERT_MOCK_FILE")

    parser.add_argument(
        "--alert-url",
        dest="alert_url",
        default=env_alert_url,
        help="Endpoint URL of Prometheus / Alertmanager alerts API.",
    )
    parser.add_argument(
        "--interval",
        dest="interval_seconds",
        type=int,
        default=env_interval,
        help="Polling interval in seconds between alert evaluations.",
    )
    parser.add_argument(
        "--cooldown",
        dest="cooldown_seconds",
        type=int,
        default=env_cooldown,
        help="Cooldown period in seconds per alert fingerprint to suppress duplicate dispatches.",
    )
    parser.add_argument(
        "--agent-cmd",
        dest="agent_cmd",
        default=env_agent_cmd,
        help="Shell command or binary invoked to dispatch the autonomous coding agent.",
    )
    parser.add_argument(
        "--alert-file",
        dest="alert_file",
        default=env_mock_file,
        help="Path to local JSON mock fixture file for offline testing instead of querying network URL.",
    )
    parser.add_argument(
        "--once",
        "--single-run",
        dest="once",
        action="store_true",
        default=False,
        help="Execute a single polling cycle and exit with status code 0 (for testing and CI).",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help="Simulate alert evaluation and dispatch formatting without launching agent processes.",
    )
    parser.add_argument(
        "--timeout",
        dest="agent_timeout_seconds",
        type=int,
        default=DEFAULT_AGENT_TIMEOUT,
        help="Maximum execution timeout in seconds for dispatched agent processes.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        dest="verbose",
        action="store_true",
        default=False,
        help="Enable detailed debug logging output.",
    )

    return parser


def parse_config(argv: list[str] | None = None) -> PollerConfig:
    """Parse CLI arguments and return validated PollerConfig instance."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    return PollerConfig(
        alert_url=args.alert_url,
        interval_seconds=args.interval_seconds,
        cooldown_seconds=args.cooldown_seconds,
        agent_cmd=args.agent_cmd,
        alert_file=args.alert_file,
        once=args.once,
        dry_run=args.dry_run,
        verbose=args.verbose,
        agent_timeout_seconds=args.agent_timeout_seconds,
    )
