#!/usr/bin/env python3
"""On-call engineer alert polling daemon entrypoint.

Periodically queries observability alert endpoint, detects active firing alerts,
and dispatches an autonomous coding agent with mandatory verbatim on-call prompt.
"""

from __future__ import annotations

import logging
from pathlib import Path
import sys

# Ensure local module imports resolve cleanly when invoked as script
REPO_DIR = Path(__file__).resolve().parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from config import parse_config
from poller import AlertPoller


def setup_logging(verbose: bool = False) -> None:
    """Configure structured logging output with timestamps and severity."""
    level = logging.DEBUG if verbose else logging.INFO
    format_str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=level, format=format_str, datefmt="%Y-%m-%d %H:%M:%S")


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for the on-call alert poller."""
    config = parse_config(argv)
    setup_logging(config.verbose)

    poller = AlertPoller(config)
    poller.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
