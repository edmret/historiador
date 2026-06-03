import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey
from backend.models.base import Base

class History(Base):
    __tablename__ = "histories"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    topic_id = Column(String, ForeignKey("topics.id"), nullable=False)
    subtopic_id = Column(String, ForeignKey("subtopics.id"), nullable=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    status = Column(String, default="in_review")  # in_review→refining→accepted→rejected
    profile_id = Column(String, ForeignKey("profiles.id"), nullable=True)
    feedback_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))