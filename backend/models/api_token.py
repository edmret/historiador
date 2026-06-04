"""API Token model — long-lived bearer tokens for headless MCP access."""

from sqlalchemy import Column, String, Text, DateTime, Boolean
from datetime import datetime, timezone
import secrets

from backend.models.base import Base


def _generate_token() -> str:
    """Generate a cryptographically random API token."""
    return "ht_" + secrets.token_hex(32)


class APIToken(Base):
    """Long-lived API token for programmatic access (MCP clients)."""

    __tablename__ = "api_tokens"

    id = Column(String(36), primary_key=True)  # UUID
    token_hash = Column(String(128), unique=True, nullable=False, index=True)
    label = Column(String(128), nullable=False)
    user_id = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)

    @staticmethod
    def hash_token(token: str) -> str:
        """Hash a token for storage (SHA-256 hex)."""
        import hashlib
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def create_new(label: str, user_id: str) -> tuple[str, "APIToken"]:
        """Create a new APIToken. Returns (raw_token, db_instance).

        The raw token is returned ONLY once — store the hash in DB.
        """
        from datetime import datetime, timezone
        import uuid

        raw = _generate_token()
        hashed = APIToken.hash_token(raw)
        return raw, APIToken(
            id=str(uuid.uuid4()),
            token_hash=hashed,
            label=label,
            user_id=user_id,
        )
