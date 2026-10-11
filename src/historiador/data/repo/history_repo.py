"""Histories — the artifacts the whole pipeline exists to produce."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from historiador.data import models as orm
from historiador.data.session import Clock, SystemClock, now_datetime


class History(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    topic_id: str
    subtopic_id: str | None = None
    title: str
    content: str
    status: orm.HistoryStatus
    profile_id: str | None = None
    feedback_count: int
    created_at: datetime
    updated_at: datetime


class HistorySummary(BaseModel):
    """List-view projection.

    Histories are long markdown documents; the kanban board renders dozens at once and
    needs none of the body. Selecting the content column for a board render would move
    megabytes per request for text that is never displayed.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    topic_id: str
    subtopic_id: str | None = None
    title: str
    status: orm.HistoryStatus
    profile_id: str | None = None
    feedback_count: int
    created_at: datetime
    updated_at: datetime


def _to_history(row: orm.History) -> History:
    return History(
        id=row.id,
        topic_id=row.topic_id,
        subtopic_id=row.subtopic_id,
        title=row.title,
        content=row.content,
        status=row.status,
        profile_id=row.profile_id,
        feedback_count=row.feedback_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class HistoryRepo:
    """Repository for the ``histories`` aggregate."""

    def __init__(self, session: AsyncSession, *, clock: Clock | None = None) -> None:
        self._session = session
        self._clock: Clock = clock if clock is not None else SystemClock()

    async def create(
        self,
        *,
        topic_id: str,
        title: str,
        content: str,
        subtopic_id: str | None = None,
        profile_id: str | None = None,
        status: orm.HistoryStatus = orm.HistoryStatus.IN_REVIEW,
    ) -> History:
        now = now_datetime(self._clock)
        row = orm.History(
            id=orm.new_id(),
            topic_id=topic_id,
            subtopic_id=subtopic_id,
            title=title,
            content=content,
            status=status,
            profile_id=profile_id,
            feedback_count=0,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return _to_history(row)

    async def get(self, history_id: str) -> History | None:
        row = await self._session.get(orm.History, history_id)
        return None if row is None else _to_history(row)

    async def list_histories(
        self,
        *,
        topic_id: str | None = None,
        status: orm.HistoryStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[HistorySummary]:
        """Board/list query — deliberately does not load ``content``."""
        stmt = (
            select(
                orm.History.id,
                orm.History.topic_id,
                orm.History.subtopic_id,
                orm.History.title,
                orm.History.status,
                orm.History.profile_id,
                orm.History.feedback_count,
                orm.History.created_at,
                orm.History.updated_at,
            )
            .order_by(orm.History.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if topic_id is not None:
            stmt = stmt.where(orm.History.topic_id == topic_id)
        if status is not None:
            stmt = stmt.where(orm.History.status == status)
        rows = (await self._session.execute(stmt)).all()
        return [
            HistorySummary(
                id=r.id,
                topic_id=r.topic_id,
                subtopic_id=r.subtopic_id,
                title=r.title,
                status=r.status,
                profile_id=r.profile_id,
                feedback_count=r.feedback_count,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in rows
        ]

    async def count(self, *, status: orm.HistoryStatus | None = None) -> int:
        stmt = select(func.count()).select_from(orm.History)
        if status is not None:
            stmt = stmt.where(orm.History.status == status)
        return int((await self._session.execute(stmt)).scalar_one())

    async def set_status(self, history_id: str, status: orm.HistoryStatus) -> History | None:
        row = await self._session.get(orm.History, history_id)
        if row is None:
            return None
        row.status = status
        row.updated_at = now_datetime(self._clock)
        await self._session.flush()
        return _to_history(row)

    async def replace_content(
        self, history_id: str, *, content: str, title: str | None = None
    ) -> History | None:
        """Overwrite the body after an editor-agent refinement pass."""
        row = await self._session.get(orm.History, history_id)
        if row is None:
            return None
        row.content = content
        if title is not None:
            row.title = title
        row.updated_at = now_datetime(self._clock)
        await self._session.flush()
        return _to_history(row)

    async def increment_feedback(self, history_id: str) -> History | None:
        """Bump the feedback counter.

        Read-modify-write is safe here only because every mutation runs on the single
        writer task (see :mod:`historiador.data.session`); there is no second writer to
        race with.
        """
        row = await self._session.get(orm.History, history_id)
        if row is None:
            return None
        row.feedback_count += 1
        row.updated_at = now_datetime(self._clock)
        await self._session.flush()
        return _to_history(row)

    async def delete(self, history_id: str) -> bool:
        row = await self._session.get(orm.History, history_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True


__all__ = ["History", "HistoryRepo", "HistorySummary"]
