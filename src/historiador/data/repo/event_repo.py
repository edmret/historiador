"""Durable event log access — the replay path behind ``/ws/runs`` and the REST API.

Every method here exists to serve one of three questions the dashboard asks:

* *"What happened after seq N?"* → :meth:`EventRepo.read_since`, the exact query the
  WebSocket ``subscribe`` frame and ``GET /api/runs/{id}/events?since_seq=`` share.
* *"Where was I?"* → :meth:`EventRepo.max_seq`, which lets the event bus restore its
  per-run watermark after a daemon restart instead of re-numbering from 1 and
  corrupting the client's view of ordering.
* *"Did this batch land?"* → :meth:`EventRepo.append`, which is idempotent on the
  ``(run_id, seq)`` primary key so a retried flush is a no-op rather than a duplicate.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import CursorResult, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from historiador.data import models as orm

DEFAULT_REPLAY_LIMIT = 500


class EventRecord(BaseModel):
    """Transport-shaped event row. Mirrors the ``Event`` envelope of §4.1.

    Frozen because an event is a historical fact: once read out of the log, nothing
    downstream has any business mutating it.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    seq: int = Field(ge=1)
    ts: float
    type: str
    node_id: str | None = None
    agent: str | None = None
    # Payload shape is per-type and validated in core.events.types; at this layer it
    # is opaque JSON, hence `Any`.
    payload: dict[str, Any] = Field(default_factory=dict)


def _to_record(row: orm.Event) -> EventRecord:
    return EventRecord(
        run_id=row.run_id,
        seq=row.seq,
        ts=row.ts,
        type=row.type,
        node_id=row.node_id,
        agent=row.agent,
        payload=row.payload,
    )


class EventRepo:
    """Repository for the append-only event log.

    No ORM instance ever leaves this class; callers receive :class:`EventRecord`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, events: Sequence[EventRecord]) -> int:
        """Append a batch, ignoring rows whose ``(run_id, seq)`` already exists.

        Returns the number of rows actually inserted, which lets a caller detect a
        replayed batch without a second round trip.

        ``ON CONFLICT (run_id, seq) DO NOTHING`` is used rather than a blanket
        ``INSERT OR IGNORE``: the latter would also swallow foreign-key and CHECK
        violations, turning a genuine bug (an event for a run that does not exist, a
        ``seq`` of 0) into silent data loss. Only re-delivery of an already-persisted
        sequence number is a tolerable no-op.
        """
        if not events:
            return 0
        stmt = sqlite_insert(orm.Event).values(
            [
                {
                    "run_id": e.run_id,
                    "seq": e.seq,
                    "ts": e.ts,
                    "type": e.type,
                    "node_id": e.node_id,
                    "agent": e.agent,
                    "payload": e.payload,
                }
                for e in events
            ]
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=["run_id", "seq"])
        # execute() is statically Result[Any]; an INSERT always yields a CursorResult,
        # which is where rowcount lives.
        result = cast("CursorResult[Any]", await self._session.execute(stmt))
        return int(result.rowcount)

    async def read_since(
        self,
        run_id: str,
        since_seq: int = 0,
        limit: int = DEFAULT_REPLAY_LIMIT,
    ) -> list[EventRecord]:
        """Events with ``seq > since_seq``, in ascending ``seq`` order.

        Strictly greater-than: the client's ``since_seq`` is the highest sequence it
        has *already applied*, so returning it again would double-apply a delta.
        The ``(run_id, seq)`` primary key makes this an index range scan.
        """
        stmt = (
            select(orm.Event)
            .where(orm.Event.run_id == run_id, orm.Event.seq > since_seq)
            .order_by(orm.Event.seq.asc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_record(row) for row in rows]

    async def read_range(self, run_id: str, start_seq: int, end_seq: int) -> list[EventRecord]:
        """Inclusive ``[start_seq, end_seq]`` slice — used to backfill a detected gap."""
        stmt = (
            select(orm.Event)
            .where(
                orm.Event.run_id == run_id,
                orm.Event.seq >= start_seq,
                orm.Event.seq <= end_seq,
            )
            .order_by(orm.Event.seq.asc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_record(row) for row in rows]

    async def read_by_type(
        self,
        run_id: str,
        types: Sequence[str],
        since_seq: int = 0,
        limit: int = DEFAULT_REPLAY_LIMIT,
    ) -> list[EventRecord]:
        """Filtered replay, served by ``ix_events_run_id_type_seq``."""
        if not types:
            return []
        stmt = (
            select(orm.Event)
            .where(
                orm.Event.run_id == run_id,
                orm.Event.type.in_(list(types)),
                orm.Event.seq > since_seq,
            )
            .order_by(orm.Event.seq.asc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_record(row) for row in rows]

    async def max_seq(self, run_id: str) -> int:
        """Highest persisted ``seq`` for a run, or ``0`` when the run has no events.

        ``0`` is the correct empty answer because sequences start at 1, so a restarted
        bus can unconditionally use ``max_seq(run_id) + 1`` as its next number.
        """
        stmt = select(func.max(orm.Event.seq)).where(orm.Event.run_id == run_id)
        value = (await self._session.execute(stmt)).scalar_one_or_none()
        return 0 if value is None else int(value)

    async def count(self, run_id: str) -> int:
        """Number of persisted events for a run — used to assert gaplessness in tests."""
        stmt = select(func.count()).select_from(orm.Event).where(orm.Event.run_id == run_id)
        return int((await self._session.execute(stmt)).scalar_one())


__all__ = ["DEFAULT_REPLAY_LIMIT", "EventRecord", "EventRepo"]
