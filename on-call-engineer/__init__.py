"""On-call engineer alert polling and headless agent dispatch package."""

from pathlib import Path
import sys

# Support direct imports when directory is placed in sys.path
_PKG_DIR = Path(__file__).resolve().parent
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

from config import DEFAULT_ALERT_URL, DEFAULT_COOLDOWN, DEFAULT_POLL_INTERVAL, PollerConfig, parse_config
from dispatcher import VERBATIM_SYSTEM_PROMPT, AgentDispatcher, DispatchResult, build_full_agent_prompt
from models import AlertContext, AlertTrackedState, compute_alert_fingerprint
from poller import AlertPoller

__all__ = [
    "AlertContext",
    "AlertPoller",
    "AlertTrackedState",
    "AgentDispatcher",
    "DispatchResult",
    "DEFAULT_ALERT_URL",
    "DEFAULT_COOLDOWN",
    "DEFAULT_POLL_INTERVAL",
    "PollerConfig",
    "VERBATIM_SYSTEM_PROMPT",
    "build_full_agent_prompt",
    "compute_alert_fingerprint",
    "parse_config",
]
