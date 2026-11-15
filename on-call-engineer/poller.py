"""Alert polling daemon for Prometheus / Alertmanager and autonomous agent dispatch."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any
import urllib.error
import urllib.request

from config import PollerConfig
from dispatcher import AgentDispatcher, DispatchResult
from models import AlertContext, AlertTrackedState, compute_alert_fingerprint

logger = logging.getLogger("on_call_engineer.poller")


class AlertPoller:
    """Daemon that periodically evaluates the observability alerts API and dispatches agents."""

    def __init__(
        self,
        config: PollerConfig,
        dispatcher: AgentDispatcher | None = None,
    ) -> None:
        self.config = config
        self.dispatcher = dispatcher or AgentDispatcher(
            agent_cmd=config.agent_cmd,
            dry_run=config.dry_run,
            timeout_seconds=config.agent_timeout_seconds,
        )
        self.tracker: dict[str, AlertTrackedState] = {}
        self._running = False

    def fetch_raw_payload(self) -> Any:
        """Fetch alert payload from local mock file or remote HTTP API.

        Gracefully handles network errors, timeouts, non-200 responses, and malformed JSON,
        returning None on error so the daemon can continue running safely.
        """
        # Local mock file mode
        if self.config.alert_file:
            path = Path(self.config.alert_file)
            if not path.is_file():
                logger.error("Alert mock file not found: %s", path)
                return None
            try:
                raw_text = path.read_text(encoding="utf-8")
                return json.loads(raw_text)
            except json.JSONDecodeError as exc:
                logger.error("Malformed JSON in alert mock file %s: %s", path, exc)
                return None
            except Exception as exc:
                logger.error("Unexpected error reading alert mock file %s: %s", path, exc)
                return None

        # Remote HTTP endpoint mode
        req = urllib.request.Request(
            self.config.alert_url,
            headers={"Accept": "application/json", "User-Agent": "on-call-poller/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                if resp.status != 200:
                    logger.warning(
                        "Alert API returned non-200 HTTP status %d: %s",
                        resp.status,
                        resp.reason,
                    )
                    return None
                data = resp.read().decode("utf-8")
                return json.loads(data)
        except urllib.error.HTTPError as exc:
            logger.warning("Alert API HTTP error: %d %s", exc.code, exc.reason)
            return None
        except urllib.error.URLError as exc:
            logger.warning("Alert API unreachable at %s: %s", self.config.alert_url, exc.reason)
            return None
        except TimeoutError:
            logger.warning("Alert API request timed out for %s", self.config.alert_url)
            return None
        except json.JSONDecodeError as exc:
            logger.error("Malformed JSON response from Alert API %s: %s", self.config.alert_url, exc)
            return None
        except Exception as exc:
            logger.error("Unexpected error querying Alert API %s: %s", self.config.alert_url, exc)
            return None

    def extract_firing_alerts(self, payload: Any) -> list[AlertContext]:
        """Extract and normalize all alerts currently in 'firing' state.

        Ignores pending, resolved, and malformed alerts.
        """
        if payload is None:
            return []

        # Determine alerts list across Prometheus and Alertmanager response schemas
        raw_alerts: list[Any] = []
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, dict) and isinstance(data.get("alerts"), list):
                raw_alerts = data["alerts"]
            elif isinstance(payload.get("alerts"), list):
                raw_alerts = payload["alerts"]
            elif isinstance(data, list):
                raw_alerts = data
            else:
                logger.warning(
                    "Unexpected payload structure: missing 'alerts' or 'data.alerts' list key."
                )
                return []
        elif isinstance(payload, list):
            raw_alerts = payload
        else:
            logger.warning("Unexpected top-level payload type: %s (expected dict or list)", type(payload))
            return []

        firing_alerts: list[AlertContext] = []

        for item in raw_alerts:
            if not isinstance(item, dict):
                logger.warning("Skipping non-dict alert item: %r", item)
                continue

            # Check alert state: Prometheus uses item['state'], Alertmanager uses item['status']['state'] or item['status']
            raw_state = item.get("state") or item.get("status")
            if isinstance(raw_state, dict):
                raw_state = raw_state.get("state")
            state_str = str(raw_state or "").strip().lower()

            # Ignore any alert not actively firing
            if state_str != "firing":
                continue

            labels = {str(k): str(v) for k, v in item.get("labels", {}).items()}
            annotations = {str(k): str(v) for k, v in item.get("annotations", {}).items()}

            alertname = labels.get("alertname") or annotations.get("alertname") or "UnknownAlert"
            environment = labels.get("environment") or annotations.get("environment") or "unknown"
            version = labels.get("version") or annotations.get("version") or "unknown"
            severity = labels.get("severity") or annotations.get("severity") or "unknown"
            summary = annotations.get("summary") or f"Alert {alertname} firing in {environment}"
            description = annotations.get("description") or f"Active firing incident for {alertname}"
            dashboard_url = annotations.get("dashboard_url") or ""
            runbook_url = annotations.get("runbook_url") or ""

            firing_timestamp = (
                item.get("activeAt")
                or item.get("startsAt")
                or datetime.now(timezone.utc).isoformat()
            )

            fingerprint = compute_alert_fingerprint(
                labels=labels,
                alertname=alertname,
                explicit_fingerprint=item.get("fingerprint"),
            )

            context = AlertContext(
                alertname=alertname,
                environment=environment,
                version=version,
                severity=severity,
                summary=summary,
                description=description,
                dashboard_url=dashboard_url,
                runbook_url=runbook_url,
                firing_timestamp=str(firing_timestamp),
                labels=labels,
                annotations=annotations,
                fingerprint=fingerprint,
                raw_payload=item,
            )
            firing_alerts.append(context)

        return firing_alerts

    def poll_cycle(self) -> list[DispatchResult]:
        """Execute a single polling iteration.

        1. Fetches raw payload.
        2. Filters firing alerts.
        3. Enforces deduplication, in-flight protection, and cooldown window per fingerprint.
        4. Dispatches agents sequentially for actionable firing alerts.
        5. Detects and logs transitions to resolved / absent state.
        """
        now = time.time()
        logger.debug("Starting poll cycle against endpoint %s", self.config.alert_file or self.config.alert_url)

        payload = self.fetch_raw_payload()
        if payload is None:
            logger.info("No payload received from alert source; will retry on next poll tick.")
            return []

        firing_alerts = self.extract_firing_alerts(payload)
        logger.info("Poll cycle evaluated %d active firing alert(s).", len(firing_alerts))

        current_firing_fps: set[str] = set()
        dispatched_results: list[DispatchResult] = []

        # Process each firing alert sequentially
        for alert in firing_alerts:
            fp = alert.fingerprint
            current_firing_fps.add(fp)

            if fp not in self.tracker:
                self.tracker[fp] = AlertTrackedState(
                    fingerprint=fp,
                    alertname=alert.alertname,
                    first_seen_at=now,
                    last_seen_at=now,
                    last_state="firing",
                )
            else:
                self.tracker[fp].last_seen_at = now
                self.tracker[fp].last_state = "firing"

            tracked = self.tracker[fp]

            # In-flight protection
            if tracked.in_flight:
                logger.info(
                    "Alert '%s' [fingerprint=%s] is currently being investigated by an in-flight agent. Skipping duplicate dispatch.",
                    alert.alertname,
                    fp,
                )
                continue

            # Deduplication & cooldown window check
            if tracked.last_dispatched_at > 0.0:
                elapsed = now - tracked.last_dispatched_at
                if elapsed < self.config.cooldown_seconds:
                    remaining = self.config.cooldown_seconds - elapsed
                    logger.info(
                        "Alert '%s' [fingerprint=%s] is within cooldown window (%.1fs remaining of %ds). Skipping duplicate dispatch.",
                        alert.alertname,
                        fp,
                        remaining,
                        self.config.cooldown_seconds,
                    )
                    continue

            # Dispatch agent
            logger.info(
                "Triggering agent dispatch for firing alert '%s' [fingerprint=%s, severity=%s].",
                alert.alertname,
                fp,
                alert.severity,
            )
            tracked.in_flight = True
            try:
                res = self.dispatcher.dispatch(alert)
                tracked.last_dispatched_at = time.time()
                tracked.dispatch_count += 1
                dispatched_results.append(res)
            finally:
                tracked.in_flight = False

        # Transition detection: check for alerts that were firing but are now resolved or absent
        for fp, state in list(self.tracker.items()):
            if state.last_state == "firing" and fp not in current_firing_fps:
                logger.info(
                    "Alert '%s' [fingerprint=%s] transitioned from firing to resolved/absent. Updating tracked state.",
                    state.alertname,
                    fp,
                )
                state.last_state = "resolved"
                state.last_seen_at = now

        return dispatched_results

    def run(self) -> None:
        """Run the polling loop until interrupted or until single cycle completes in once mode."""
        logger.info(
            "Starting on-call alert poller [url=%s, interval=%ds, cooldown=%ds, once=%s, dry_run=%s]",
            self.config.alert_file or self.config.alert_url,
            self.config.interval_seconds,
            self.config.cooldown_seconds,
            self.config.once,
            self.config.dry_run,
        )

        self._running = True
        try:
            while self._running:
                self.poll_cycle()
                if self.config.once:
                    logger.info("Single-run (--once) complete. Exiting cleanly.")
                    break
                time.sleep(self.config.interval_seconds)
        except KeyboardInterrupt:
            logger.info("Poller stopped by user interrupt.")
        finally:
            self._running = False
