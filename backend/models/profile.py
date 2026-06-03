import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime
from backend.models.base import Base

class Profile(Base):
    __tablename__ = "profiles"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False, unique=True)
    description = Column(Text)
    tone = Column(String, default="neutral")  # dramatic, educational, humorous, epic, neutral
    audience = Column(String, default="general")
    preferred_length = Column(String, default="medium")  # short, medium, long
    style_notes = Column(Text)
    creation_feedback = Column(Text)  # JSON with Q&A from Profile Agent
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))