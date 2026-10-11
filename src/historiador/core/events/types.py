"""Event taxonomy for the Historiador runtime.

Every observable action in the system — a node starting, a token streaming in,
a tool failing — is recorded as an :class:`Event`.  The event log is the
source of truth for:

* the live dashboard (streamed over WebSocket)
* post-run replay (``GET /api/runs/{id}/events?since_seq=N``)
* cost accounting and auditing

Design axioms
-------------
* **``seq`` is the contract.**  Assigned under a per-run lock at publish time;
  starts at 1, never skips, never resets within a run.  The client tracks
  the highest ``seq`` it has applied and reconnects with ``?since_seq=N``.
* **Payload is a flat ``Mapping``**, not a typed dataclass, so the wire format
  stays stable while the runtime evolves.  Every key that the dashboard
  depends on is documented in the taxonomy table in ``ARCHITECTURE.md §4.2``.
* **``node_id`` and ``agent`` are optional** — run-level events (``RUN_CREATED``,
  ``RUN_STARTED``, …) carry no node context.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

__all__ = ["Event", "EventType"]


class EventType(StrEnum):
    """All event types emitted by the runtime.

    The string value is the stable wire name; do not rename it without a
    migration plan for stored events and dashboard code.
    """

    # ── run lifecycle ──────────────────────────────────────────────────────
    RUN_CREATED = "RUN_CREATED"
    """Run persisted; payload: ``topic_id``, ``graph`` (nodes + edges)."""

    RUN_STARTED = "RUN_STARTED"
    """Scheduler begins executing the DAG."""

    RUN_COMPLETED = "RUN_COMPLETED"
    """Terminal success; payload: ``usage``, ``cost_usd``, ``duration_s``."""

    RUN_FAILED = "RUN_FAILED"
    """Terminal failure; payload: ``error``."""

    RUN_CANCELLED = "RUN_CANCELLED"
    """Cooperative cancel; payload: ``reason``."""

    # ── node lifecycle ─────────────────────────────────────────────────────
    NODE_READY = "NODE_READY"
    """All dependencies satisfied; node is waiting for a concurrency slot."""

    NODE_STARTED = "NODE_STARTED"
    """An execution attempt begins; payload: ``attempt``."""

    NODE_PROGRESS = "NODE_PROGRESS"
    """``ctx.activity(...)`` called; payload: ``activity``, optional ``pct``."""

    NODE_RETRYING = "NODE_RETRYING"
    """A retryable failure; payload: ``attempt``, ``delay_s``, ``error``."""

    NODE_SUCCEEDED = "NODE_SUCCEEDED"
    """Attempt succeeded; payload: ``duration_s``, ``usage``."""

    NODE_FAILED = "NODE_FAILED"
    """All attempts exhausted; payload: ``error``."""

    NODE_SKIPPED = "NODE_SKIPPED"
    """Upstream failed and node is not optional; payload: ``because``."""

    # ── LLM ───────────────────────────────────────────────────────────────
    LLM_REQUEST_STARTED = "LLM_REQUEST_STARTED"
    """Request dispatched; payload: ``model``, ``prompt_tokens_est``."""

    LLM_TOKEN = "LLM_TOKEN"
    """Coalesced streaming delta (≤50 ms or 256 chars); payload: ``delta``."""

    LLM_REQUEST_COMPLETED = "LLM_REQUEST_COMPLETED"
    """Response done; payload: ``usage``, ``cost_usd``, ``latency_ms``."""

    LLM_REQUEST_FAILED = "LLM_REQUEST_FAILED"
    """Request errored; payload: ``error``, optional ``status``."""

    # ── tools ─────────────────────────────────────────────────────────────
    TOOL_STARTED = "TOOL_STARTED"
    """Tool invoked; payload: ``tool``, ``args`` (redacted)."""

    TOOL_COMPLETED = "TOOL_COMPLETED"
    """Tool returned; payload: ``tool``, ``summary``, ``duration_ms``."""

    TOOL_FAILED = "TOOL_FAILED"
    """Tool errored; payload: ``tool``, ``error``."""

    # ── artifacts & logging ───────────────────────────────────────────────
    ARTIFACT_CREATED = "ARTIFACT_CREATED"
    """History or outline written; payload: ``kind``, ``id``, ``title``."""

    LOG = "LOG"
    """Structured log line; payload: ``level``, ``message``."""


@dataclass(frozen=True, slots=True)
class Event:
    """Immutable event envelope carried through the bus and persisted verbatim.

    Attributes
    ----------
    run_id:
        Opaque identifier for the run this event belongs to.
    seq:
        Monotonic, gapless sequence number **per run**.  Starts at 1.
        Assigned by :class:`~historiador.core.events.bus.EventBus` under a
        per-run lock — callers must *not* supply it.
    ts:
        Wall-clock timestamp in epoch seconds, sourced from
        :class:`~historiador.core.clock.Clock`.
    type:
        Discriminator from :class:`EventType`.
    node_id:
        The ``RunNode.id`` that emitted this event, or ``None`` for run-level
        events.
    agent:
        The ``AgentSpec.name`` for the emitting node, or ``None`` for
        run-level events.
    payload:
        Flat ``Mapping`` of JSON-serialisable values.  Schema is per-``type``
        and documented in ``ARCHITECTURE.md §4.2``.  Stored as-is; never
        mutated after construction.
    """

    run_id: str
    seq: int
    ts: float
    type: EventType
    node_id: str | None
    agent: str | None
    payload: Mapping[str, Any]  # JSON-serialisable; heterogeneous by design
