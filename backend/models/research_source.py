import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from backend.models.base import Base

class ResearchSource(Base):
    __tablename__ = "research_sources"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    subtopic_id = Column(String, ForeignKey("subtopics.id"), nullable=False)
    agent_name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    title = Column(String)
    content_snippet = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))