from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class TopicCreate(BaseModel):
    title: str

class SubtopicItem(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    status: str = "todo"

class TopicResponse(BaseModel):
    id: str
    title: str
    status: str
    profile_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    subtopics: List[SubtopicItem] = []

class ScopingMessageCreate(BaseModel):
    content: str

class ScopingMessageResponse(BaseModel):
    id: str
    topic_id: str
    role: str
    content: str
    created_at: datetime

class SubtopicUpdate(BaseModel):
    status: Optional[str] = None
    todo_order: Optional[int] = None