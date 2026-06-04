"""Stytch client wrapper — session validation, login exchange, and client singleton."""

import stytch
from backend.config import settings

_client_instance: stytch.Client | None = None


def get_stytch_client() -> stytch.Client:
    """Return a singleton Stytch client configured from settings."""
    global _client_instance
    if _client_instance is not None:
        return _client_instance

    if not settings.stytch_project_id or not settings.stytch_secret:
        _client_instance = None
        return None

    env = stytch.env.live if settings.stytch_environment == "live" else stytch.env.test
    _client_instance = stytch.Client(
        project_id=settings.stytch_project_id,
        secret=settings.stytch_secret,
        environment=env,
    )
    return _client_instance


async def validate_stytch_session(session_token: str) -> dict | None:
    """Validate a Stytch session JWT and return user info dict, or None if invalid.

    Returns:
        {
            "user_id": str,
            "email": str | None,
            "name": str | None,
            "session_id": str,
        } or None if the token is expired/invalid.
    """
    client = get_stytch_client()
    if client is None:
        # Running without Stytch — no auth required (dev mode)
        return {"user_id": "anonymous", "email": None, "name": None, "session_id": None}

    try:
        resp = client.sessions.authenticate(session_token=session_token)
        user = resp["user"]
        email = None
        name = None
        if user.get("emails"):
            email = user["emails"][0].get("email")
        if user.get("name"):
            name = user["name"].get("first_name", "") + " " + user["name"].get("last_name", "")
            name = name.strip() or None
        return {
            "user_id": user["user_id"],
            "email": email,
            "name": name,
            "session_id": resp.get("session", {}).get("session_id"),
        }
    except Exception:
        return None


async def exchange_oauth_code(code: str, redirect_uri: str) -> dict | None:
    """Exchange an OAuth code for a session (used for Google/GitHub login)."""
    client = get_stytch_client()
    if client is None:
        return None
    try:
        resp = client.oauth.authenticate(code=code, redirect_url=redirect_uri)
        return {
            "session_token": resp["session_token"],
            "user_id": resp["user"]["user_id"],
            "email": resp["user"].get("emails", [{}])[0].get("email"),
        }
    except Exception:
        return None
