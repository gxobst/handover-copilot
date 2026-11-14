"""Authentication and authorization dependencies for Shift Handover Copilot."""

import secrets
from typing import Optional

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings

security_scheme = HTTPBearer(auto_error=False)


def require_admin_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_scheme),
    settings: Settings = Depends(get_settings),
) -> str:
    """Validate Bearer admin token with constant-time comparison against ADMIN_TOKEN.

    Returns the validated token string on success.
    Raises HTTP 401 Unauthorized with RFC 9457 ProblemDetails on missing,
    malformed, or invalid tokens.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed Authorization header, expected 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    if not token or not secrets.compare_digest(token, settings.admin_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token


def require_relay_token(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> str:
    """Validate webhook token against RELAY_WEBHOOK_TOKEN using constant-time comparison.

    Accepts token via 'X-Webhook-Token' header or 'Authorization: Bearer <token>'.
    Raises HTTP 401 Unauthorized with RFC 9457 ProblemDetails if missing or invalid.
    """
    token: Optional[str] = request.headers.get("X-Webhook-Token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing webhook authentication token. Provide 'X-Webhook-Token' header or 'Authorization: Bearer <token>'",
        )

    if not secrets.compare_digest(token, settings.relay_webhook_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook authentication token",
        )

    return token
