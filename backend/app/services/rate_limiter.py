"""In-memory thread-safe rate limiter and generation budget protection for report generation.

Implements Issue #41:
- Per-client IP sliding window rate limit (default 5 requests / 600s).
- Per-client IP lifetime cap (default 20 requests).
- Global service total lifetime cap (default 20 requests) to protect Vertex AI spend.
- Client IP resolution via X-Forwarded-For (first hop) with client.host fallback.
- Strict universal enforcement with NO admin token bypass.
- RFC 9457 ProblemDetails with HTTP 429 Too Many Requests and Retry-After header.
- Automatic memory pruning of expired window timestamps.
"""

from functools import lru_cache
import threading
import time
from typing import Optional

from fastapi import Request

from app.config import Settings, get_settings
from app.errors import RateLimitExceededException


def extract_client_ip(request: Request) -> str:
    """Extract client IP from X-Forwarded-For header (first hop) or request.client.host."""
    forwarded = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if forwarded:
        parts = forwarded.split(",")
        if parts:
            first_ip = parts[0].strip()
            if first_ip:
                return first_ip
    if request.client and request.client.host:
        host = request.client.host.strip()
        if host:
            return host
    return "127.0.0.1"


class RateLimiter:
    """In-memory thread-safe rate limiter and report generation budget controller."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ip_timestamps: dict[str, list[float]] = {}
        self._ip_lifetime_counts: dict[str, int] = {}
        self._global_count: int = 0
        self._total_checks: int = 0

    def reset(self) -> None:
        """Reset all rate limiter state (used in automated test fixtures)."""
        with self._lock:
            self._ip_timestamps.clear()
            self._ip_lifetime_counts.clear()
            self._global_count = 0
            self._total_checks = 0

    def get_stats(self) -> dict[str, int]:
        """Return diagnostic metrics for testing and monitoring."""
        with self._lock:
            return {
                "global_count": self._global_count,
                "tracked_ips_window": len(self._ip_timestamps),
                "tracked_ips_lifetime": len(self._ip_lifetime_counts),
            }

    def _prune_expired_locked(self, cutoff: float) -> None:
        """Prune expired timestamps across all tracked client IPs to prevent memory leaks."""
        empty_ips: list[str] = []
        for ip, timestamps in self._ip_timestamps.items():
            valid = [ts for ts in timestamps if ts > cutoff]
            if valid:
                self._ip_timestamps[ip] = valid
            else:
                empty_ips.append(ip)
        for ip in empty_ips:
            self._ip_timestamps.pop(ip, None)

    def check_and_record(
        self,
        request: Request,
        settings: Settings,
        now: Optional[float] = None,
    ) -> None:
        """Check rate limits and generation budget caps, recording the request if allowed.

        Universal enforcement: NO admin token bypass is permitted because repository
        credentials and tokens are publicly visible.

        Raises:
            RateLimitExceededException (HTTP 429) if budget or window limit is exceeded.
        """
        if not settings.rate_limit_enabled:
            return

        current_time = time.time() if now is None else float(now)
        client_ip = extract_client_ip(request)

        with self._lock:
            self._total_checks += 1
            # Periodic pruning of expired window entries every 50 checks or when tracking > 200 IPs
            if self._total_checks % 50 == 0 or len(self._ip_timestamps) > 200:
                self._prune_expired_locked(current_time - settings.rate_limit_window_seconds)

            # 1. Per-user lifetime cap check
            user_lifetime = self._ip_lifetime_counts.get(client_ip, 0)
            if user_lifetime >= settings.rate_limit_user_lifetime_cap:
                raise RateLimitExceededException(
                    detail="Per-user lifetime generation cap reached (maximum 20 reports) to protect Vertex AI spend.",
                    retry_after=86400,
                )

            # 2. Global total lifetime generation cap check
            if self._global_count >= settings.rate_limit_global_cap:
                raise RateLimitExceededException(
                    detail="Global report generation budget cap reached (maximum 20 reports) to protect Vertex AI spend.",
                    retry_after=86400,
                )

            # 3. Sliding window per-user check
            window_seconds = settings.rate_limit_window_seconds
            max_requests = settings.rate_limit_max_requests
            cutoff = current_time - window_seconds

            timestamps = self._ip_timestamps.get(client_ip, [])
            valid_timestamps = [ts for ts in timestamps if ts > cutoff]
            self._ip_timestamps[client_ip] = valid_timestamps

            if len(valid_timestamps) >= max_requests:
                oldest_in_window = valid_timestamps[0]
                retry_after = max(1, int(oldest_in_window + window_seconds - current_time + 0.999))
                raise RateLimitExceededException(
                    detail=(
                        f"Per-user generation rate limit exceeded ({max_requests} requests per "
                        f"{window_seconds // 60} minutes) to protect Vertex AI quota."
                    ),
                    retry_after=retry_after,
                )

            # Request is allowed -> record it
            valid_timestamps.append(current_time)
            self._ip_lifetime_counts[client_ip] = user_lifetime + 1
            self._global_count += 1


@lru_cache
def get_rate_limiter() -> RateLimiter:
    """Dependency provider returning singleton RateLimiter instance."""
    return RateLimiter()
