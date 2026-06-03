from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from backend.database import async_session, get_session
from backend.models.topic import Topic
from backend.models.subtopic import Subtopic
from backend.models.scoping_message import ScopingMessage
from backend.schemas.topic import TopicCreate, TopicResponse, ScopingMessageCreate, ScopingMessageResponse, SubtopicItem, SubtopicUpdate
from backend.agents.orchestrator import HistoriadorOrchestrator

router = APIRouter(prefix="/api/topics", tags=["topics"])
orchestrator = HistoriadorOrchestrator()

@router.get("", response_model=List[TopicResponse])
async def list_topics():
    async with async_session() as session:
        result = await session.execute(select(Topic).order_by(Topic.created_at.desc()))
        topics = result.scalars().all()
        responses = []
        for t in topics:
            sub_result = await session.execute(select(Subtopic).where(Subtopic.topic_id == t.id))
            subtopics = [SubtopicItem(id=s.id, title=s.title, description=s.description, status=s.status) for s in sub_result.scalars().all()]
            responses.append(TopicResponse(id=t.id, title=t.title, status=t.status, profile_id=t.profile_id, created_at=t.created_at, updated_at=t.updated_at, subtopics=subtopics))
        return responses

@router.post("", response_model=TopicResponse, status_code=201)
async def create_topic(body: TopicCreate):
    topic = await orchestrator.create_topic(body.title)
    return TopicResponse(id=topic.id, title=topic.title, status=topic.status, profile_id=topic.profile_id, created_at=topic.created_at, updated_at=topic.updated_at)

@router.get("/{topic_id}", response_model=TopicResponse)
async def get_topic(topic_id: str):
    async with async_session() as session:
        topic = await session.get(Topic, topic_id)
        if not topic:
            raise HTTPException(404, "Topic not found")
        sub_result = await session.execute(select(Subtopic).where(Subtopic.topic_id == topic_id))
        subtopics = [SubtopicItem(id=s.id, title=s.title, description=s.description, status=s.status) for s in sub_result.scalars().all()]
        return TopicResponse(id=topic.id, title=topic.title, status=topic.status, profile_id=topic.profile_id, created_at=topic.created_at, updated_at=topic.updated_at, subtopics=subtopics)

@router.post("/{topic_id}/scoping", response_model=dict)
async def send_scoping_message(topic_id: str, body: ScopingMessageCreate):
    result = await orchestrator.process_scoping(topic_id, body.content)
    return result

@router.get("/{topic_id}/scoping", response_model=List[ScopingMessageResponse])
async def get_scoping_messages(topic_id: str):
    async with async_session() as session:
        result = await session.execute(
            select(ScopingMessage).where(ScopingMessage.topic_id == topic_id).order_by(ScopingMessage.created_at)
        )
        return [ScopingMessageResponse(id=m.id, topic_id=m.topic_id, role=m.role, content=m.content, created_at=m.created_at) for m in result.scalars().all()]

@router.patch("/{topic_id}/subtopics/{subtopic_id}", response_model=SubtopicItem)
async def update_subtopic(topic_id: str, subtopic_id: str, body: SubtopicUpdate):
    async with async_session() as session:
        sub = await session.get(Subtopic, subtopic_id)
        if not sub:
            raise HTTPException(404, "Subtopic not found")
        if body.status is not None:
            sub.status = body.status
        if body.todo_order is not None:
            sub.todo_order = body.todo_order
        await session.commit()
        await session.refresh(sub)
        return SubtopicItem(id=sub.id, title=sub.title, description=sub.description, status=sub.status)