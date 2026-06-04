"""Authentication router — Stytch login exchange, session check, API token management."""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field
from typing import Optional

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    """Exchange a Stytch session JWT for a Historiador session."""

    session_token: str = Field(..., description="Stytch session JWT")


class LoginResponse(BaseModel):
    user_id: str
    email: Optional[str] = None
    name: Optional[str] = None


class APITokenCreateRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=128)


class APITokenCreateResponse(BaseModel):
    raw_token: str
    id: str
    label: str


class APITokenItem(BaseModel):
    id: str
    label: str
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None
    expires_at: Optional[str] = None


class APIUser(BaseModel):
    user_id: str
    email: Optional[str] = None
    name: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _get_user_from_request(request: Request) -> dict | None:
    """Extract authenticated user by checking Bearer or x-api-key headers."""
    from backend.auth.stytch_client import validate_stytch_session
    from backend.auth.tokens import resolve_api_token

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        jwt = auth_header[7:]
        return await validate_stytch_session(jwt)

    api_key = request.headers.get("x-api-key", "")
    if api_key:
        return await resolve_api_token(api_key)

    return None


async def require_user(request: Request) -> dict:
    """Dependency: require authenticated user, raise 401 otherwise."""
    user = await _get_user_from_request(request)
    if user is None:
        from backend.config import settings
        if not settings.stytch_project_id or not settings.stytch_secret:
            return {"user_id": "anonymous", "email": None, "name": "Developer"}
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    """Exchange a Stytch session JWT for user info."""
    from backend.auth.stytch_client import validate_stytch_session

    user = await validate_stytch_session(body.session_token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session token",
        )
    return LoginResponse(
        user_id=user["user_id"],
        email=user.get("email"),
        name=user.get("name"),
    )


@router.get("/me", response_model=LoginResponse | APIUser)
async def me(request: Request):
    """Return current user info. Works with Bearer JWT or x-api-key."""
    from backend.config import settings

    user = await _get_user_from_request(request)
    if user is None:
        if not settings.stytch_project_id or not settings.stytch_secret:
            return APIUser(user_id="anonymous", name="Developer")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    if user.get("email") is not None or user.get("name") is not None:
        return LoginResponse(
            user_id=user["user_id"],
            email=user.get("email"),
            name=user.get("name"),
        )
    return APIUser(user_id=user["user_id"])


@router.get("/config")
async def auth_config():
    """Return public Stytch configuration for the frontend SDK.

    This endpoint is intentionally public (no auth required).
    """
    from backend.config import settings

    return {
        "stytch_project_id": settings.stytch_project_id,
        "stytch_public_token": settings.stytch_public_token,
        "stytch_environment": settings.stytch_environment,
        "stytch_configured": bool(settings.stytch_project_id and settings.stytch_secret),
    }


# ── API Token management (requires auth) ─────────────────────────────────────

@router.post("/tokens", response_model=APITokenCreateResponse)
async def create_token(body: APITokenCreateRequest, user: dict = Depends(require_user)):
    """Generate a new long-lived API token."""
    from backend.auth.tokens import create_api_token

    raw, db_token = await create_api_token(body.label, user["user_id"])
    return APITokenCreateResponse(
        raw_token=raw,
        id=db_token.id,
        label=db_token.label,
    )


@router.get("/tokens", response_model=list[APITokenItem])
async def list_tokens(user: dict = Depends(require_user)):
    """List all active API tokens for the current user."""
    from backend.auth.tokens import list_api_tokens

    return await list_api_tokens(user["user_id"])


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(token_id: str, user: dict = Depends(require_user)):
    """Revoke an API token by ID."""
    from backend.auth.tokens import revoke_api_token

    ok = await revoke_api_token(token_id, user["user_id"])
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")