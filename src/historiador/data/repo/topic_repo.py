"""The topic aggregate: topics, their subtopics, the scoping transcript, and sources.

These four tables are one aggregate because they share a lifetime — deleting a topic
deletes its subtopics (``ON DELETE CASCADE``), which deletes their research sources.
Keeping them behind one repository means that invariant is expressed once, in the
schema, and never re-implemented as a hand-rolled cleanup loop.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from historiador.data import models as orm
from historiador.data.session import Clock, SystemClock, now_datetime


class Topic(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    status: orm.TopicStatus
    profile_id: str | None = None
    created_at: datetime
    updated_at: datetime


class Subtopic(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    topic_id: str
    title: str
    description: str | None = None
    status: orm.SubtopicStatus
    todo_order: int
    created_at: datetime
    updated_at: datetime


class ScopingMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    topic_id: str
    role: orm.ScopingRole
    content: str
    created_at: datetime


class ResearchSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    subtopic_id: str
    agent_name: str
    url: str
    title: str | None = None
    content_snippet: str | None = None
    created_at: datetime


def _to_topic(row: orm.Topic) -> Topic:
    return Topic(
        id=row.id,
        title=row.title,
        status=row.status,
        profile_id=row.profile_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_subtopic(row: orm.Subtopic) -> Subtopic:
    return Subtopic(
        id=row.id,
        topic_id=row.topic_id,
        title=row.title,
        description=row.description,
        status=row.status,
        todo_order=row.todo_order,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_message(row: orm.ScopingMessage) -> ScopingMessage:
    return ScopingMessage(
        id=row.id,
        topic_id=row.topic_id,
        role=row.role,
        content=row.content,
        created_at=row.created_at,
    )


def _to_source(row: orm.ResearchSource) -> ResearchSource:
    return ResearchSource(
        id=row.id,
        subtopic_id=row.subtopic_id,
        agent_name=row.agent_name,
        url=row.url,
        title=row.title,
        content_snippet=row.content_snippet,
        created_at=row.created_at,
    )


class TopicRepo:
    """Repository for the topic aggregate. Returns Pydantic models only."""

    def __init__(self, session: AsyncSession, *, clock: Clock | None = None) -> None:
        self._session = session
        self._clock: Clock = clock if clock is not None else SystemClock()

    # ── topics ──────────────────────────────────────────────────────────────────

    async def create(
        self,
        *,
        title: str,
        profile_id: str | None = None,
        status: orm.TopicStatus = orm.TopicStatus.SCOPING,
        topic_id: str | None = None,
    ) -> Topic:
        """Create a topic.

        The default status is ``SCOPING``. The legacy model defaulted to ``"scoring"``
        — a typo that no constraint could catch because the column was a bare string.
        Here the value comes from :class:`~historiador.data.models.TopicStatus`, so the
        same mistake will not compile, let alone commit.
        """
        now = now_datetime(self._clock)
        row = orm.Topic(
            id=topic_id if topic_id is not None else orm.new_id(),
            title=title,
            status=status,
            profile_id=profile_id,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return _to_topic(row)

    async def get(self, topic_id: str) -> Topic | None:
        row = await self._session.get(orm.Topic, topic_id)
        return None if row is None else _to_topic(row)

    async def list_topics(
        self,
        *,
        status: orm.TopicStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Topic]:
        stmt = select(orm.Topic).order_by(orm.Topic.created_at.desc()).limit(limit).offset(offset)
        if status is not None:
            stmt = stmt.where(orm.Topic.status == status)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_topic(row) for row in rows]

    async def set_status(self, topic_id: str, status: orm.TopicStatus) -> Topic | None:
        row = await self._session.get(orm.Topic, topic_id)
        if row is None:
            return None
        row.status = status
        row.updated_at = now_datetime(self._clock)
        await self._session.flush()
        return _to_topic(row)

    async def set_profile(self, topic_id: str, profile_id: str | None) -> Topic | None:
        row = await self._session.get(orm.Topic, topic_id)
        if row is None:
            return None
        row.profile_id = profile_id
        row.updated_at = now_datetime(self._clock)
        await self._session.flush()
        return _to_topic(row)

    async def delete(self, topic_id: str) -> bool:
        """Delete a topic; subtopics, messages and sources cascade in the database."""
        row = await self._session.get(orm.Topic, topic_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True

    # ── subtopics ───────────────────────────────────────────────────────────────

    async def add_subtopic(
        self,
        *,
        topic_id: str,
        title: str,
        description: str | None = None,
        todo_order: int | None = None,
        status: orm.SubtopicStatus = orm.SubtopicStatus.TODO,
    ) -> Subtopic:
        """Append a subtopic; ``todo_order`` defaults to the end of the kanban column."""
        now = now_datetime(self._clock)
        order = todo_order if todo_order is not None else await self._next_order(topic_id)
        row = orm.Subtopic(
            id=orm.new_id(),
            topic_id=topic_id,
            title=title,
            description=description,
            status=status,
            todo_order=order,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return _to_subtopic(row)

    async def _next_order(self, topic_id: str) -> int:
        stmt = select(func.max(orm.Subtopic.todo_order)).where(orm.Subtopic.topic_id == topic_id)
        current = (await self._session.execute(stmt)).scalar_one_or_none()
        return 0 if current is None else int(current) + 1

    async def list_subtopics(
        self, topic_id: str, *, status: orm.SubtopicStatus | None = None
    ) -> list[Subtopic]:
        stmt = (
            select(orm.Subtopic)
            .where(orm.Subtopic.topic_id == topic_id)
            .order_by(orm.Subtopic.todo_order.asc())
        )
        if status is not None:
            stmt = stmt.where(orm.Subtopic.status == status)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_subtopic(row) for row in rows]

    async def get_subtopic(self, subtopic_id: str) -> Subtopic | None:
        row = await self._session.get(orm.Subtopic, subtopic_id)
        return None if row is None else _to_subtopic(row)

    async def set_subtopic_status(
        self, subtopic_id: str, status: orm.SubtopicStatus
    ) -> Subtopic | None:
        row = await self._session.get(orm.Subtopic, subtopic_id)
        if row is None:
            return None
        row.status = status
        row.updated_at = now_datetime(self._clock)
        await self._session.flush()
        return _to_subtopic(row)

    # ── scoping transcript ──────────────────────────────────────────────────────

    async def add_scoping_message(
        self, *, topic_id: str, role: orm.ScopingRole, content: str
    ) -> ScopingMessage:
        row = orm.ScopingMessage(
            id=orm.new_id(),
            topic_id=topic_id,
            role=role,
            content=content,
            created_at=now_datetime(self._clock),
        )
        self._session.add(row)
        await self._session.flush()
        return _to_message(row)

    async def list_scoping_messages(self, topic_id: str) -> list[ScopingMessage]:
        stmt = (
            select(orm.ScopingMessage)
            .where(orm.ScopingMessage.topic_id == topic_id)
            .order_by(orm.ScopingMessage.created_at.asc(), orm.ScopingMessage.id.asc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_message(row) for row in rows]

    # ── research sources ────────────────────────────────────────────────────────

    async def add_research_source(
        self,
        *,
        subtopic_id: str,
        agent_name: str,
        url: str,
        title: str | None = None,
        content_snippet: str | None = None,
    ) -> ResearchSource:
        """Record a source. Violating ``(subtopic_id, url)`` uniqueness raises —
        callers that expect overlap should use :meth:`list_research_sources` first or
        catch ``IntegrityError`` deliberately."""
        row = orm.ResearchSource(
            id=orm.new_id(),
            subtopic_id=subtopic_id,
            agent_name=agent_name,
            url=url,
            title=title,
            content_snippet=content_snippet,
            created_at=now_datetime(self._clock),
        )
        self._session.add(row)
        await self._session.flush()
        return _to_source(row)

    async def list_research_sources(self, subtopic_id: str) -> list[ResearchSource]:
        stmt = (
            select(orm.ResearchSource)
            .where(orm.ResearchSource.subtopic_id == subtopic_id)
            .order_by(orm.ResearchSource.created_at.asc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_source(row) for row in rows]


__all__ = ["ResearchSource", "ScopingMessage", "Subtopic", "Topic", "TopicRepo"]
