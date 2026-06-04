"""API Token service — create, resolve, list, revoke long-lived tokens."""

from datetime import datetime, timezone
import hashlib
from sqlalchemy import select
from backend.database import async_session
from backend.models.api_token import APIToken


async def create_api_token(label: str, user_id: str, session=None) -> tuple[str, APIToken]:
    """Create a new API token. Returns (raw_token, db_instance).

    The raw token is printed ONCE — store it before returning.
    """
    own_session = False
    if session is None:
        session = async_session()
        own_session = True

    try:
        raw, db_token = APIToken.create_new(label, user_id)
        session.add(db_token)
        await session.commit()
        return raw, db_token
    finally:
        if own_session:
            await session.close()


async def resolve_api_token(token: str) -> dict | None:
    """Resolve a raw token string to user info, or None if invalid/expired.

    The token must be passed without the 'ht_' prefix stripping since the
    model generates them with that prefix.
    """
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    async with async_session() as session:
        stmt = select(APIToken).where(
            APIToken.token_hash == token_hash,
            APIToken.is_active == True,
        )
        if expires := APIToken.expires_at:
            stmt = stmt.where(APIToken.expires_at > datetime.now(timezone.utc))

        result = await session.execute(stmt)
        db_token = result.scalar_one_or_none()
        if db_token is None:
            return None

        # Update last_used_at
        db_token.last_used_at = datetime.now(timezone.utc)
        await session.commit()

        return {
            "user_id": db_token.user_id,
            "token_id": db_token.id,
            "label": db_token.label,
            "email": None,
            "name": None,
        }


async def list_api_tokens(user_id: str) -> list[dict]:
    """List all active tokens for a user (last_4 chars only)."""
    async with async_session() as session:
        stmt = select(APIToken).where(
            APIToken.user_id == user_id,
            APIToken.is_active == True,
        ).order_by(APIToken.created_at.desc())
        result = await session.execute(stmt)
        tokens = result.scalars().all()
        return [
            {
                "id": t.id,
                "label": t.label,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
                "expires_at": t.expires_at.isoformat() if t.expires_at else None,
            }
            for t in tokens
        ]


async def revoke_api_token(token_id: str, user_id: str) -> bool:
    """Revoke (soft-delete) an API token. Returns True if found and revoked."""
    async with async_session() as session:
        stmt = select(APIToken).where(
            APIToken.id == token_id,
            APIToken.user_id == user_id,
        )
        result = await session.execute(stmt)
        token = result.scalar_one_or_none()
        if token is None:
            return False
        token.is_active = False
        await session.commit()
        return True