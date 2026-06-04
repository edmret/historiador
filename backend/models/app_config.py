from sqlalchemy import Column, String, Text, DateTime
from datetime import datetime, timezone
from backend.models.base import Base


class AppConfig(Base):
    """Key-value store for application configuration persisted to the database.

    Each row is a single config key with an optional string value.
    The ``updated_at`` timestamp is automatically managed by SQLAlchemy.
    """

    __tablename__ = "app_config"

    key = Column(String(128), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
