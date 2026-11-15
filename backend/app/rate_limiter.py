"""Re-export rate limiter components for backward compatibility."""

from app.services.rate_limiter import (
    RateLimiter,
    extract_client_ip,
    get_rate_limiter,
)

__all__ = ["RateLimiter", "extract_client_ip", "get_rate_limiter"]
