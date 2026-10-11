"""Feedback records — the signal the profile agent learns from over time.

Feedback is kept as an append-only ledger rather than a mutable field on a history:
the editor agent needs the *sequence* of refinement requests, and the profile agent
needs the accept/reject history across every document a profile ever produced.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from historiador.data import models as orm
from historiador.data.session import Clock, SystemClock, now_datetime


class Feedback(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    history_id: str | None = None
    profile_id: str | None = None
    feedback_type: orm.FeedbackType
    feedback_text: str | None = None
    applied: bool
    created_at: datetime


def _to_feedback(row: orm.FeedbackRecord) -> Feedback:
    return Feedback(
        id=row.id,
        history_id=row.history_id,
        profile_id=row.profile_id,
        feedback_type=row.feedback_type,
        feedback_text=row.feedback_text,
        applied=row.applied,
        created_at=row.created_at,
    )


class FeedbackRepo:
    """Repository for the ``feedback_records`` aggregate."""

    def __init__(self, session: AsyncSession, *, clock: Clock | None = None) -> None:
        self._session = session
        self._clock: Clock = clock if clock is not None else SystemClock()

    async def create(
        self,
        *,
        feedback_type: orm.FeedbackType,
        history_id: str | None = None,
        profile_id: str | None = None,
        feedback_text: str | None = None,
    ) -> Feedback:
        """Record feedback.

        At least one of ``history_id``/``profile_id`` must be set; the database CHECK
        constraint enforces it, because feedback attached to nothing can never be
        surfaced again and would just be a slow leak of user intent.
        """
        row = orm.FeedbackRecord(
            id=orm.new_id(),
            history_id=history_id,
            profile_id=profile_id,
            feedback_type=feedback_type,
            feedback_text=feedback_text,
            applied=False,
            created_at=now_datetime(self._clock),
        )
        self._session.add(row)
        await self._session.flush()
        return _to_feedback(row)

    async def get(self, feedback_id: str) -> Feedback | None:
        row = await self._session.get(orm.FeedbackRecord, feedback_id)
        return None if row is None else _to_feedback(row)

    async def list_for_history(self, history_id: str) -> list[Feedback]:
        stmt = (
            select(orm.FeedbackRecord)
            .where(orm.FeedbackRecord.history_id == history_id)
            .order_by(orm.FeedbackRecord.created_at.asc(), orm.FeedbackRecord.id.asc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_feedback(row) for row in rows]

    async def list_for_profile(
        self, profile_id: str, *, applied: bool | None = None, limit: int = 200
    ) -> list[Feedback]:
        """Profile-learning query: ``applied=False`` yields the not-yet-absorbed queue."""
        stmt = (
            select(orm.FeedbackRecord)
            .where(orm.FeedbackRecord.profile_id == profile_id)
            .order_by(orm.FeedbackRecord.created_at.asc(), orm.FeedbackRecord.id.asc())
            .limit(limit)
        )
        if applied is not None:
            stmt = stmt.where(orm.FeedbackRecord.applied == applied)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_feedback(row) for row in rows]

    async def mark_applied(self, feedback_ids: list[str]) -> int:
        """Mark records as absorbed into a profile. Returns the number changed."""
        if not feedback_ids:
            return 0
        stmt = select(orm.FeedbackRecord).where(orm.FeedbackRecord.id.in_(feedback_ids))
        rows = (await self._session.execute(stmt)).scalars().all()
        for row in rows:
            row.applied = True
        await self._session.flush()
        return len(rows)

    async def count_for_history(self, history_id: str) -> int:
        stmt = (
            select(func.count())
            .select_from(orm.FeedbackRecord)
            .where(orm.FeedbackRecord.history_id == history_id)
        )
        return int((await self._session.execute(stmt)).scalar_one())


__all__ = ["Feedback", "FeedbackRepo"]
