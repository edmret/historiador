import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey
from backend.models.base import Base

class FeedbackRecord(Base):
    __tablename__ = "feedback_records"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    history_id = Column(String, ForeignKey("histories.id"), nullable=True)
    profile_id = Column(String, ForeignKey("profiles.id"), nullable=True)
    feedback_type = Column(String, nullable=False)  # accept, reject, refine_request
    feedback_text = Column(Text)
    applied = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))