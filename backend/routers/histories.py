from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from typing import List
from backend.database import async_session
from backend.models.history import History
from backend.schemas.history import HistoryResponse, HistoryListResponse, FeedbackCreate
from backend.agents.orchestrator import HistoriadorOrchestrator

router = APIRouter(prefix="/api/histories", tags=["histories"])
orchestrator = HistoriadorOrchestrator()

@router.get("", response_model=HistoryListResponse)
async def list_histories(topic_id: str = "", status: str = ""):
    async with async_session() as session:
        stmt = select(History).order_by(History.created_at.desc())
        if topic_id:
            stmt = stmt.where(History.topic_id == topic_id)
        if status:
            stmt = stmt.where(History.status == status)
        result = await session.execute(stmt)
        histories = result.scalars().all()
        return HistoryListResponse(
            histories=[HistoryResponse(id=h.id, topic_id=h.topic_id, subtopic_id=h.subtopic_id, title=h.title, content=h.content[:500], status=h.status, profile_id=h.profile_id, feedback_count=h.feedback_count, created_at=h.created_at, updated_at=h.updated_at) for h in histories],
            total=len(histories),
        )

@router.get("/{history_id}", response_model=HistoryResponse)
async def get_history(history_id: str):
    async with async_session() as session:
        history = await session.get(History, history_id)
        if not history:
            raise HTTPException(404, "History not found")
        return HistoryResponse(id=history.id, topic_id=history.topic_id, subtopic_id=history.subtopic_id, title=history.title, content=history.content, status=history.status, profile_id=history.profile_id, feedback_count=history.feedback_count, created_at=history.created_at, updated_at=history.updated_at)

@router.post("/{history_id}/feedback", response_model=dict)
async def submit_feedback(history_id: str, body: FeedbackCreate):
    result = await orchestrator.submit_feedback(history_id, body.feedback_type, body.feedback_text)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result
