"""Data models and representations for on-call engineer alert handling."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any


def compute_alert_fingerprint(
    labels: dict[str, str],
    alertname: str = "",
    explicit_fingerprint: str | None = None,
) -> str:
    """Generate a deterministic fingerprint identifying an alert by its labels.

    If an explicit fingerprint is supplied by the monitoring system, it is used directly.
    Otherwise, a 16-character SHA-256 hex digest is derived from the sorted label key-value pairs.
    """
    if explicit_fingerprint:
        return explicit_fingerprint

    effective_name = alertname or labels.get("alertname", "UnknownAlert")
    sorted_pairs = sorted((k, str(v)) for k, v in labels.items() if k != "fingerprint")
    canonical_str = f"{effective_name}:" + ",".join(f"{k}={v}" for k, v in sorted_pairs)
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()[:16]


@dataclass
class AlertContext:
    """Structured context passed to the on-call coding agent upon incident dispatch."""

    alertname: str
    environment: str
    version: str
    severity: str
    summary: str
    description: str
    dashboard_url: str
    runbook_url: str
    firing_timestamp: str
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)
    fingerprint: str = ""
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a structured dictionary containing all alert details."""
        return {
            "alertname": self.alertname,
            "environment": self.environment,
            "version": self.version,
            "severity": self.severity,
            "summary": self.summary,
            "description": self.description,
            "dashboard_url": self.dashboard_url,
            "runbook_url": self.runbook_url,
            "firing_timestamp": self.firing_timestamp,
            "labels": dict(self.labels),
            "annotations": dict(self.annotations),
            "fingerprint": self.fingerprint,
        }

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize alert details to JSON."""
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    def to_markdown_summary(self) -> str:
        """Render a formatted markdown summary for agent consumption."""
        labels_block = "\n".join(f"- `{k}`: {v}" for k, v in sorted(self.labels.items())) or "None"
        annotations_block = (
            "\n".join(f"- `{k}`: {v}" for k, v in sorted(self.annotations.items())) or "None"
        )
        return (
            f"### Active Incident: {self.alertname}\n\n"
            f"- **Severity:** {self.severity}\n"
            f"- **Environment:** {self.environment}\n"
            f"- **Version:** {self.version}\n"
            f"- **Firing Since:** {self.firing_timestamp}\n"
            f"- **Summary:** {self.summary}\n"
            f"- **Description:** {self.description}\n"
            f"- **Dashboard URL:** {self.dashboard_url or 'N/A'}\n"
            f"- **Runbook URL:** {self.runbook_url or 'N/A'}\n"
            f"- **Fingerprint:** `{self.fingerprint}`\n\n"
            f"#### Active Labels\n{labels_block}\n\n"
            f"#### Annotations\n{annotations_block}"
        )


@dataclass
class AlertTrackedState:
    """Internal poller tracking state for an individual alert fingerprint."""

    fingerprint: str
    alertname: str
    first_seen_at: float
    last_seen_at: float
    last_dispatched_at: float = 0.0
    last_state: str = "firing"
    in_flight: bool = False
    dispatch_count: int = 0
