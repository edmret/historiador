from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class ProfileCreate(BaseModel):
    name: str
    description: Optional[str] = None
    tone: str = "neutral"
    audience: str = "general"
    preferred_length: str = "medium"
    style_notes: Optional[str] = None
    creation_feedback: Optional[str] = None

class ProfileResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    tone: str
    audience: str
    preferred_length: str
    style_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class ProfileListResponse(BaseModel):
    profiles: List[ProfileResponse]
    total: int

class ProfileUpdate(BaseModel):
    description: Optional[str] = None
    tone: Optional[str] = None
    audience: Optional[str] = None
    preferred_length: Optional[str] = None
    style_notes: Optional[str] = None