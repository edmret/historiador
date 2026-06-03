from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class TopicSubmit(BaseModel):
    topic_title: str
    profile_id: Optional[str] = None
    subtopic_ids: Optional[List[str]] = None
    num_research_agents: Optional[int] = None
    num_histories: Optional[int] = None

class TopicStatusResponse(BaseModel):
    topic_id: str
    title: str
    status: str
    progress_pct: float = 0.0
    current_stage: str = ""
    created_at: datetime
    updated_at: datetime

class PushSubscriptionCreate(BaseModel):
    endpoint: str
    p256dh: str
    auth: str