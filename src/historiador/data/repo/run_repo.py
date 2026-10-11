"""Runs and run nodes — the persisted mirror of the live DAG.

A run row exists so the dashboard can show a *finished* or *reloaded* run without the
scheduler being alive. Node rows exist for the same reason at node granularity: after
a daemon restart the run view is rebuilt from ``run_nodes`` (the snapshot) plus
``events`` with ``seq > snapshot_seq`` (the deltas), which is the snapshot-then-delta
contract of ARCHITECTURE.md §7.
"""

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import CursorResult, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from historiador.data import models as orm
from historiador.data.session import Clock, SystemClock


class Usage(BaseModel):
    """Token accounting. Mirrors ``core.llm.types.Usage`` without importing it."""

    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    cached_tokens: int = Field(default=0, ge=0)


class RunRecord(BaseModel):
    """A run as the API and dashboard see it.

    ``cost_usd is None`` means *unknown* (unpriced model), never *free*. Downstream
    must render it as "—", not "$0.00" — see ARCHITECTURE.md §5.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    topic_id: str | None
    status: orm.RunStatus
    created_at: float
    started_at: float | None = None
    ended_at: float | None = None
    usage: Usage = Field(default_factory=Usage)
    cost_usd: float | None = None
    # DAG snapshot; its schema belongs to core.graph, so it is opaque JSON here.
    graph: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None


class RunNodeRecord(BaseModel):
    """One node's persisted state."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    node_id: str
    agent: str
    label: str
    state: orm.NodeState = orm.NodeState.BLOCKED
    attempt: int = Field(default=0, ge=0)
    activity: str = ""
    started_at: float | None = None
    ended_at: float | None = None
    usage: Usage = Field(default_factory=Usage)
    cost_usd: float | None = None
    error: dict[str, Any] | None = None


def _to_run(row: orm.Run) -> RunRecord:
    return RunRecord(
        id=row.id,
        topic_id=row.topic_id,
        status=row.status,
        created_at=row.created_at,
        started_at=row.started_at,
        ended_at=row.ended_at,
        usage=Usage(
            prompt_tokens=row.prompt_tokens,
            completion_tokens=row.completion_tokens,
            cached_tokens=row.cached_tokens,
        ),
        cost_usd=row.cost_usd,
        graph=row.graph,
        error=row.error,
    )


def _to_node(row: orm.RunNode) -> RunNodeRecord:
    return RunNodeRecord(
        run_id=row.run_id,
        node_id=row.node_id,
        agent=row.agent,
        label=row.label,
        state=row.state,
        attempt=row.attempt,
        activity=row.activity,
        started_at=row.started_at,
        ended_at=row.ended_at,
        usage=Usage(
            prompt_tokens=row.prompt_tokens,
            completion_tokens=row.completion_tokens,
            cached_tokens=row.cached_tokens,
        ),
        cost_usd=row.cost_usd,
        error=row.error,
    )


class RunRepo:
    """Repository for the ``runs`` / ``run_nodes`` aggregate."""

    def __init__(self, session: AsyncSession, *, clock: Clock | None = None) -> None:
        self._session = session
        self._clock: Clock = clock if clock is not None else SystemClock()

    async def create(
        self,
        *,
        topic_id: str | None,
        graph: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> RunRecord:
        """Persist a PENDING run. The caller may supply ``run_id`` because the id is
        minted before the run starts and already appears in ``RUN_CREATED``."""
        row = orm.Run(
            id=run_id if run_id is not None else orm.new_id(),
            topic_id=topic_id,
            status=orm.RunStatus.PENDING,
            created_at=self._clock.now(),
            prompt_tokens=0,
            completion_tokens=0,
            cached_tokens=0,
            cost_usd=None,
            graph=graph if graph is not None else {},
            error=None,
        )
        self._session.add(row)
        await self._session.flush()
        return _to_run(row)

    async def get(self, run_id: str) -> RunRecord | None:
        row = await self._session.get(orm.Run, run_id)
        return None if row is None else _to_run(row)

    async def list_runs(
        self,
        *,
        status: orm.RunStatus | None = None,
        topic_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RunRecord]:
        """Newest-first run list — the dashboard's landing query.

        Ordering and filtering match ``ix_runs_status_created_at`` exactly.
        """
        stmt = select(orm.Run).order_by(orm.Run.created_at.desc()).limit(limit).offset(offset)
        if status is not None:
            stmt = stmt.where(orm.Run.status == status)
        if topic_id is not None:
            stmt = stmt.where(orm.Run.topic_id == topic_id)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_run(row) for row in rows]

    async def count(self, *, status: orm.RunStatus | None = None) -> int:
        stmt = select(func.count()).select_from(orm.Run)
        if status is not None:
            stmt = stmt.where(orm.Run.status == status)
        return int((await self._session.execute(stmt)).scalar_one())

    async def mark_started(self, run_id: str) -> RunRecord | None:
        row = await self._session.get(orm.Run, run_id)
        if row is None:
            return None
        row.status = orm.RunStatus.RUNNING
        row.started_at = self._clock.now()
        await self._session.flush()
        return _to_run(row)

    async def mark_finished(
        self,
        run_id: str,
        *,
        status: orm.RunStatus,
        usage: Usage | None = None,
        cost_usd: float | None = None,
        error: dict[str, Any] | None = None,
    ) -> RunRecord | None:
        """Write terminal state.

        ``cost_usd`` is passed straight through, ``None`` included: a run over an
        unpriced model must stay unpriced rather than being coerced to 0.
        """
        row = await self._session.get(orm.Run, run_id)
        if row is None:
            return None
        row.status = status
        row.ended_at = self._clock.now()
        if row.started_at is None:
            # Satisfies ck_runs_run_ended_implies_started: a run that failed before
            # the scheduler started it still has to record a start instant.
            row.started_at = row.ended_at
        if usage is not None:
            row.prompt_tokens = usage.prompt_tokens
            row.completion_tokens = usage.completion_tokens
            row.cached_tokens = usage.cached_tokens
        row.cost_usd = cost_usd
        row.error = error
        await self._session.flush()
        return _to_run(row)

    async def update_graph(self, run_id: str, graph: dict[str, Any]) -> None:
        row = await self._session.get(orm.Run, run_id)
        if row is not None:
            row.graph = graph
            await self._session.flush()

    # ── nodes ───────────────────────────────────────────────────────────────────

    async def upsert_nodes(self, nodes: list[RunNodeRecord]) -> int:
        """Insert-or-update node snapshots in one statement.

        Upsert rather than insert because node state is written repeatedly as a node
        moves BLOCKED → READY → RUNNING → SUCCEEDED, and the scheduler must not have
        to track whether it has persisted this node before.
        """
        if not nodes:
            return 0
        payload = [
            {
                "run_id": n.run_id,
                "node_id": n.node_id,
                "agent": n.agent,
                "label": n.label,
                "state": n.state.value,
                "attempt": n.attempt,
                "activity": n.activity,
                "started_at": n.started_at,
                "ended_at": n.ended_at,
                "prompt_tokens": n.usage.prompt_tokens,
                "completion_tokens": n.usage.completion_tokens,
                "cached_tokens": n.usage.cached_tokens,
                "cost_usd": n.cost_usd,
                "error": n.error,
            }
            for n in nodes
        ]
        stmt = sqlite_insert(orm.RunNode).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["run_id", "node_id"],
            set_={
                "state": stmt.excluded.state,
                "attempt": stmt.excluded.attempt,
                "activity": stmt.excluded.activity,
                "started_at": stmt.excluded.started_at,
                "ended_at": stmt.excluded.ended_at,
                "prompt_tokens": stmt.excluded.prompt_tokens,
                "completion_tokens": stmt.excluded.completion_tokens,
                "cached_tokens": stmt.excluded.cached_tokens,
                "cost_usd": stmt.excluded.cost_usd,
                "error": stmt.excluded.error,
            },
        )
        result = cast("CursorResult[Any]", await self._session.execute(stmt))
        return int(result.rowcount)

    async def list_nodes(self, run_id: str) -> list[RunNodeRecord]:
        stmt = (
            select(orm.RunNode)
            .where(orm.RunNode.run_id == run_id)
            .order_by(orm.RunNode.node_id.asc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_node(row) for row in rows]

    async def get_node(self, run_id: str, node_id: str) -> RunNodeRecord | None:
        row = await self._session.get(orm.RunNode, (run_id, node_id))
        return None if row is None else _to_node(row)

    async def reap_orphaned(self, *, reason: str) -> int:
        """Force every non-terminal run to CANCELLED.

        Called on daemon startup: ARCHITECTURE.md §8 forbids a killed daemon from
        leaving a run stuck in RUNNING forever, and no scheduler is alive to finish
        the runs that were in flight when the process died.
        """
        stmt = select(orm.Run).where(
            orm.Run.status.in_([orm.RunStatus.PENDING, orm.RunStatus.RUNNING])
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        now = self._clock.now()
        for row in rows:
            row.status = orm.RunStatus.CANCELLED
            row.started_at = row.started_at if row.started_at is not None else now
            row.ended_at = now
            row.error = {"reason": reason}
        await self._session.flush()
        return len(rows)


__all__ = ["RunNodeRecord", "RunRecord", "RunRepo", "Usage"]
