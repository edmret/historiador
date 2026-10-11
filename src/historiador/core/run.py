"""Run model — the state machine carried by every DAG execution.

`Run` and `RunNode` are the single source of truth for a run's runtime state.
They live in `core/` so the scheduler, dispatcher, API and tests all share the
same types without a circular import.  `core/` never imports `domain/` — see
the layering rule in ARCHITECTURE.md §2.

Design choices worth noting
───────────────────────────
* `RunState` and `NodeState` are `StrEnum` so they serialise as plain strings
  in JSON payloads without a custom encoder, and the dashboard's TypeScript
  exhaustiveness checks work against literals rather than opaque numbers.
* `RunNode` uses `slots=True` (not `frozen=True`) because the scheduler and
  dispatcher mutate node state in place as a node progresses — a frozen node
  would require creating a new object for every transition, which means the
  scheduler's dict of nodes-by-id would go stale on every update.
* `RunResults` is a plain `dict` alias rather than a class because `input_fn`
  (the DAG's edge wiring) just looks things up by node id — there is no
  behaviour to encapsulate.
* `Usage` is opaque here (imported as `Any`-compatible from `core.llm`) — see
  the same treatment in `agent.py`.  `run.py` must not drag `core.llm` into its
  import graph so that `RunNode` can be constructed in tests without a live LLM
  layer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from historiador.core.errors import RunError

__all__ = [
    "NodeState",
    "Run",
    "RunNode",
    "RunResults",
    "RunState",
]

# Mapping of node_id → output value produced by that node.  Passed into every
# `input_fn` so a downstream node can pull exactly the upstream outputs it
# depends on, with the graph providing the guarantee that those outputs exist.
RunResults = dict[str, Any]


# ── state machines ───────────────────────────────────────────────────────


class RunState(StrEnum):
    """Lifecycle of an entire run.

    Transitions (only these are valid):

        PENDING → RUNNING → SUCCEEDED
                          → FAILED
                          → CANCELLED
    """

    #: Created and persisted, not yet executing.
    PENDING = "pending"
    #: The scheduler has started dispatching nodes.
    RUNNING = "running"
    #: Every non-optional node reached `SUCCEEDED`; the run is complete.
    SUCCEEDED = "succeeded"
    #: At least one non-optional node reached `FAILED`.
    FAILED = "failed"
    #: The run was cancelled cooperatively (all in-flight nodes have settled).
    CANCELLED = "cancelled"


class NodeState(StrEnum):
    """Lifecycle of a single node within a run.

    Transitions (only these are valid):

        BLOCKED → READY → RUNNING → SUCCEEDED
                                  → RETRYING → RUNNING (back, up to max attempts)
                                             → FAILED
                                  → FAILED
                                  → CANCELLED
                        → SKIPPED  (terminal; an upstream non-optional node failed)
    """

    #: Dependencies have not yet all succeeded.  Initial state for every node.
    BLOCKED = "blocked"
    #: All dependencies succeeded; waiting for a concurrency slot.
    READY = "ready"
    #: Currently executing inside the dispatcher.
    RUNNING = "running"
    #: A retryable failure occurred; waiting for the backoff to expire.
    RETRYING = "retrying"
    #: The attempt succeeded on the last (or only) attempt.
    SUCCEEDED = "succeeded"
    #: All attempts were exhausted without success.
    FAILED = "failed"
    #: The run (or this node) was cancelled while it was running or ready.
    CANCELLED = "cancelled"
    #: An upstream non-optional node failed before this node could run.
    SKIPPED = "skipped"


# Terminal states — the scheduler stops tracking a node once it enters one.
TERMINAL_NODE_STATES: frozenset[NodeState] = frozenset(
    {NodeState.SUCCEEDED, NodeState.FAILED, NodeState.CANCELLED, NodeState.SKIPPED}
)


# ── run node ─────────────────────────────────────────────────────────────


@dataclass(slots=True)
class RunNode:
    """One node in the execution DAG.

    Mutable by design — the scheduler transitions `state`, `attempt`,
    `activity` etc. in place.  Thread-safety is guaranteed by the scheduler's
    single-writer model: all mutations happen on the event-loop thread inside
    the scheduler's async context.

    Fields that reference other modules (``usage``, ``error``) are typed as
    ``Any`` / ``RunError | None`` to avoid pulling ``core.llm`` into the
    import graph of a unit test that only needs the state machine.
    """

    #: Stable, unique node id within this run, e.g. ``"research-2"``.
    id: str
    #: ``AgentSpec.name`` of the agent that will execute this node.
    agent: str
    #: Human-readable UI label, e.g. ``"Research · Economic causes"``.
    label: str
    #: Ids of the nodes this node must wait for before it can be dispatched.
    depends_on: tuple[str, ...]
    #: Called by the dispatcher to construct this node's input.
    #: Receives the run's accumulated outputs map and returns whatever the
    #: agent's ``run(ctx, inp)`` signature expects.  May raise — that is a
    #: configuration error, reported as a ``GraphError``.
    input_fn: Callable[[RunResults], Any]
    #: If ``True``, this node's failure does not fail the run and does not
    #: cause its dependents to be ``SKIPPED``.
    optional: bool = False
    #: Current lifecycle state.  Starts as ``BLOCKED`` for all nodes.
    state: NodeState = field(default=NodeState.BLOCKED)
    #: How many dispatch attempts have started (0 before the first attempt).
    attempt: int = 0
    #: Live ``ctx.activity()`` text — empty string before the first call.
    activity: str = ""
    #: Monotonic epoch when the *current* (or last) attempt started, or None.
    started_at: float | None = None
    #: Monotonic epoch when the node settled into a terminal state, or None.
    ended_at: float | None = None
    #: Accumulated token usage across all attempts.
    #: Typed ``Any`` so ``core.run`` does not import ``core.llm.types``.
    usage: Any = None
    #: The terminal error, populated on ``FAILED`` or ``CANCELLED``.
    error: RunError | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("RunNode.id must be a non-empty string")
        if not self.agent:
            raise ValueError("RunNode.agent must be a non-empty string")

    @property
    def is_terminal(self) -> bool:
        """True when the node has reached a state it will not leave."""
        return self.state in TERMINAL_NODE_STATES

    @property
    def duration_s(self) -> float | None:
        """Wall duration of the most recent (or completed) attempt, or None.

        Returns ``None`` when the node has not yet started.  Available as soon
        as ``ended_at`` is set; also available mid-run (``ended_at`` is None)
        to support the dashboard's elapsed-time ticker — callers must supply
        ``now`` in that case and use ``started_at`` directly.
        """
        if self.started_at is None or self.ended_at is None:
            return None
        return self.ended_at - self.started_at

    def __repr__(self) -> str:
        return (
            f"RunNode(id={self.id!r}, agent={self.agent!r}, state={self.state!r}, "
            f"attempt={self.attempt!r})"
        )


# ── run ──────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class Run:
    """Top-level container for a single DAG execution.

    Owns the collection of nodes and the overall run state.  The scheduler
    mutates ``state`` and the individual nodes' fields as the run progresses.
    All reads from the API layer take a snapshot of this object and its nodes
    (via ``to_snapshot()``) rather than holding a live reference, so the
    scheduler never blocks on a reader.
    """

    #: Globally unique run id, typically a UUID.  Must match the ``run_id``
    #: embedded in every event emitted during this run.
    id: str
    #: The topic this run is generating a history for.
    topic_id: str
    #: Ordered node registry.  ``dict`` preserves insertion order (Python 3.7+)
    #: so the API can return nodes in a stable order without re-sorting.
    nodes: dict[str, RunNode]
    #: Overall run lifecycle state.
    state: RunState = field(default=RunState.PENDING)
    #: Wall epoch when the scheduler called ``execute()``.
    started_at: float | None = None
    #: Wall epoch when the run settled (succeeded / failed / cancelled).
    ended_at: float | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Run.id must be a non-empty string")
        if not self.topic_id:
            raise ValueError("Run.topic_id must be a non-empty string")

    @property
    def is_terminal(self) -> bool:
        """True when the run has reached a state it will not leave."""
        return self.state in {RunState.SUCCEEDED, RunState.FAILED, RunState.CANCELLED}

    @property
    def duration_s(self) -> float | None:
        """Total run duration, or None if the run has not started.

        Returns the open-ended elapsed time if the run is still live
        (``ended_at`` is None).  Callers that want to avoid negative elapsed
        times on clock skew must not call this before ``started_at`` is set.
        """
        if self.started_at is None:
            return None
        if self.ended_at is None:
            return None
        return self.ended_at - self.started_at

    def node(self, node_id: str) -> RunNode:
        """Look up a node by id; raises ``KeyError`` on an unknown id."""
        return self.nodes[node_id]

    def nodes_in_state(self, state: NodeState) -> list[RunNode]:
        """Return all nodes currently in `state`, in insertion order."""
        return [n for n in self.nodes.values() if n.state is state]

    def __repr__(self) -> str:
        return (
            f"Run(id={self.id!r}, topic_id={self.topic_id!r}, "
            f"state={self.state!r}, nodes={len(self.nodes)})"
        )
