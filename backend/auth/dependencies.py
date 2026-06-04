"""FastAPI auth dependencies — validates Stytch session JWTs on protected routes."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from backend.auth.stytch_client import validate_stytch_session

bearer_scheme = HTTPBearer(auto_error=False)

AUTH_HEADER_NAME = "x-api-key"


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """Dependency that returns the authenticated user dict.

    Tries, in order:
    1. Authorization: Bearer <stytch_jwt> (standard Stytch sessions)
    2. x-api-key: <api_token> (long-lived API tokens)

    When Stytch is not configured, returns an anonymous user (dev mode).

    Raises 401 if credentials are invalid or missing when Stytch IS configured.
    """
    from backend.config import settings

    if not settings.stytch_project_id or not settings.stytch_secret:
        return {"user_id": "anonymous", "email": None, "name": "Developer"}

    # ── Option 1: Bearer token (Stytch session JWT) ──
    if credentials and credentials.scheme.lower() == "bearer":
        user = await validate_stytch_session(credentials.credentials)
        if user:
            return user

    # ── Option 2: x-api-key (long-lived API token) ──
    # Handled via middleware; falls through to 401 here.

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict | None:
    """Dependency that returns user info or None if not authenticated.

    Unlike get_current_user, this NEVER raises — it returns None when
    the user isn't authenticated, letting the route handler decide.
    """
    try:
        return await get_current_user(credentials)
    except HTTPException:
        return None
