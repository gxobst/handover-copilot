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
