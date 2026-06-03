from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class HistoryResponse(BaseModel):
    id: str
    topic_id: str
    subtopic_id: Optional[str] = None
    title: str
    content: str
    status: str
    profile_id: Optional[str] = None
    feedback_count: int = 0
    created_at: datetime
    updated_at: datetime

class HistoryListResponse(BaseModel):
    histories: List[HistoryResponse]
    total: int

class FeedbackCreate(BaseModel):
    history_id: Optional[str] = None
    profile_id: Optional[str] = None
    feedback_type: str  # accept, reject, refine_request
    feedback_text: Optional[str] = None