"""Webhook relay service for receiving Grafana alerts and dispatching GitHub repository events."""

from functools import lru_cache
import time
from typing import Any, Optional, Protocol, runtime_checkable

from fastapi import Depends
import httpx
import structlog

from app.config import Settings, get_settings
from app.schemas.relay import (
    GitHubDispatchClientPayload,
    GitHubDispatchPayload,
    GrafanaAlertItem,
    GrafanaAlertPayload,
    RelayResponse,
)

logger = structlog.get_logger("relay")


class GitHubDispatchError(Exception):
    """Exception raised when upstream GitHub repository dispatch fails."""


@runtime_checkable
class GitHubDispatcher(Protocol):
    """Interface protocol for repository dispatch triggers."""

    async def dispatch(self, payload: GitHubDispatchPayload) -> bool:
        """Send a repository dispatch event to GitHub."""
        ...


class HttpGitHubDispatcher:
    """Outbound GitHub repository dispatcher sending HTTP POST via httpx.AsyncClient."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def dispatch(self, payload: GitHubDispatchPayload) -> bool:
        repo = self.settings.github_repository.strip()
        url = f"https://api.github.com/repos/{repo}/dispatches"
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.settings.github_dispatch_pat:
            headers["Authorization"] = f"Bearer {self.settings.github_dispatch_pat}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    json=payload.model_dump(),
                    headers=headers,
                )
                if response.status_code not in (200, 201, 204):
                    logger.error(
                        "github_dispatch_failed",
                        status_code=response.status_code,
                        repo=repo,
                    )
                    raise GitHubDispatchError(
                        f"GitHub repository_dispatch upstream failed with HTTP {response.status_code}"
                    )
                return True
        except httpx.RequestError as exc:
            logger.error(
                "github_dispatch_request_error",
                error_type=type(exc).__name__,
                repo=repo,
            )
            raise GitHubDispatchError(
                f"GitHub repository_dispatch network error: {type(exc).__name__}"
            ) from exc


class MockGitHubDispatcher:
    """Mock dispatcher recording dispatches for offline unit and integration testing."""

    def __init__(
        self,
        should_fail: bool = False,
        failure_status_code: int = 502,
        error: Optional[Exception] = None,
    ) -> None:
        self.should_fail = should_fail
        self.failure_status_code = failure_status_code
        self.error = error
        self.dispatches: list[GitHubDispatchPayload] = []

    async def dispatch(self, payload: GitHubDispatchPayload) -> bool:
        if self.error is not None:
            raise self.error
        if self.should_fail:
            raise GitHubDispatchError(
                f"Simulated GitHub upstream failure HTTP {self.failure_status_code}"
            )
        self.dispatches.append(payload)
        return True


class RelayService:
    """Relay service orchestrating deduplication, reshaping, and dispatching."""

    def __init__(
        self,
        dispatcher: GitHubDispatcher,
        settings: Settings,
        cooldown_cache: Optional[dict[str, float]] = None,
    ) -> None:
        self.dispatcher = dispatcher
        self.settings = settings
        self.cooldown_cache: dict[str, float] = (
            cooldown_cache if cooldown_cache is not None else {}
        )

    def _prune_expired(self, now: float) -> None:
        """Prune fingerprint cache entries older than the cooldown window to prevent memory leaks."""
        cooldown = self.settings.relay_dedupe_cooldown_seconds
        expired = [
            fp for fp, ts in self.cooldown_cache.items() if now - ts >= cooldown
        ]
        for fp in expired:
            del self.cooldown_cache[fp]

    def _extract_alert_details(
        self, payload: GrafanaAlertPayload
    ) -> tuple[GrafanaAlertItem, bool]:
        """Identify primary firing alert or fallback alert, along with firing status."""
        firing_alerts = [
            alert for alert in payload.alerts if alert.status.lower() == "firing"
        ]
        is_firing = bool(firing_alerts) or payload.status.lower() == "firing"
        selected_alert = firing_alerts[0] if firing_alerts else payload.alerts[0]
        return selected_alert, is_firing

    async def process_alert(self, payload: GrafanaAlertPayload) -> RelayResponse:
        """Process incoming Grafana alert webhook with deduplication and GitHub dispatch."""
        selected_alert, is_firing = self._extract_alert_details(payload)
        fingerprint = selected_alert.fingerprint

        # Non-firing alerts (e.g. status: "resolved") do not trigger GitHub dispatch
        if not is_firing:
            logger.info(
                "relay_alert_ignored_non_firing",
                fingerprint=fingerprint,
                status=payload.status,
            )
            return RelayResponse(
                status="ignored",
                event_type="grafana-alert",
                fingerprint=fingerprint,
                reason="non-firing alert",
            )

        now = time.time()
        self._prune_expired(now)

        # Check deduplication window
        last_dispatched = self.cooldown_cache.get(fingerprint)
        cooldown = self.settings.relay_dedupe_cooldown_seconds
        if last_dispatched is not None and (now - last_dispatched) < cooldown:
            logger.info(
                "relay_alert_deduplicated",
                fingerprint=fingerprint,
                elapsed_s=now - last_dispatched,
                cooldown_s=cooldown,
            )
            return RelayResponse(
                status="deduplicated",
                event_type="grafana-alert",
                fingerprint=fingerprint,
            )

        # Reshape alert into GitHub repository_dispatch payload
        labels = {**payload.commonLabels, **selected_alert.labels}
        annotations = {**payload.commonAnnotations, **selected_alert.annotations}

        alertname = (
            labels.get("alertname")
            or payload.commonLabels.get("alertname")
            or "UnknownAlert"
        )
        environment = (
            labels.get("environment")
            or labels.get("env")
            or payload.commonLabels.get("environment")
            or payload.commonLabels.get("env")
            or "prod"
        )
        dashboard_url = (
            selected_alert.dashboardURL
            or annotations.get("dashboard_url")
            or payload.commonAnnotations.get("dashboard_url")
            or ""
        )
        runbook_url = (
            annotations.get("runbook_url")
            or payload.commonAnnotations.get("runbook_url")
            or "_docs/runbook.md"
        )

        client_payload = GitHubDispatchClientPayload(
            alertname=alertname,
            fingerprint=fingerprint,
            status="firing",
            environment=environment,
            dashboard_url=dashboard_url,
            runbook_url=runbook_url,
        )

        dispatch_payload = GitHubDispatchPayload(
            event_type="grafana-alert",
            client_payload=client_payload.model_dump(),
        )

        # Trigger outbound dispatch
        await self.dispatcher.dispatch(dispatch_payload)

        # Record timestamp only after successful dispatch
        self.cooldown_cache[fingerprint] = now
        logger.info(
            "relay_alert_dispatched",
            fingerprint=fingerprint,
            alertname=alertname,
            environment=environment,
        )

        return RelayResponse(
            status="dispatched",
            event_type="grafana-alert",
            fingerprint=fingerprint,
        )


_SHARED_COOLDOWN_CACHE: dict[str, float] = {}


_SHARED_MOCK_DISPATCHER = MockGitHubDispatcher()


def get_shared_cooldown_cache() -> dict[str, float]:
    """Dependency provider returning the module-level shared cooldown cache."""
    return _SHARED_COOLDOWN_CACHE


def get_github_dispatcher(
    settings: Settings = Depends(get_settings),
) -> GitHubDispatcher:
    """Dependency provider returning HttpGitHubDispatcher or MockGitHubDispatcher when offline."""
    pat = (settings.github_dispatch_pat or "").strip().lower()
    if not pat or pat in ("fake", "mock", "test"):
        return _SHARED_MOCK_DISPATCHER
    return HttpGitHubDispatcher(settings=settings)


def get_relay_service(
    dispatcher: GitHubDispatcher = Depends(get_github_dispatcher),
    settings: Settings = Depends(get_settings),
    cache: dict[str, float] = Depends(get_shared_cooldown_cache),
) -> RelayService:
    """Dependency provider returning the configured RelayService instance."""
    return RelayService(
        dispatcher=dispatcher,
        settings=settings,
        cooldown_cache=cache,
    )
