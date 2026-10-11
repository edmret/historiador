"""What an agent is, and — more importantly — what an agent is allowed to touch.

An agent here is a pure async function over a context. It receives everything it
needs as `AgentContext` fields and imports nothing: no DB session, no global
config, no LLM client it constructed itself. Two consequences follow, and both
are the reason this module exists at all:

1. **Testability.** A domain agent can be exercised with a `FakeClock`, a fake
   LLM and a recording emitter, with no network, no database and no event loop
   tricks. If agents reached for globals, every agent test would need the whole
   process wired up.
2. **Observability.** Because the LLM client and the tool registry are handed in
   *already bound to this node*, every model call and every tool invocation
   emits `LLM_*` / `TOOL_*` events automatically. An agent cannot forget to
   instrument itself, because it never holds an uninstrumented handle.

The dependencies that belong to sibling modules (`core.llm`, `core.tools`,
`core.cancel`, `core.events`) are declared here as *structural* Protocols rather
than imported. That is deliberate: `agent.py` is the contract every domain agent
is written against, so it must not drag a third of the runtime into the import
graph of a unit test — and structural typing means the real classes satisfy
these Protocols without inheriting from anything.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol, runtime_checkable

from historiador.core.clock import Clock

__all__ = [
    "NODE_PROGRESS_EVENT",
    "Agent",
    "AgentContext",
    "AgentSpec",
    "CancelScope",
    "EventEmitter",
    "LLMClient",
    "Logger",
    "ToolRegistry",
]

#: Wire value of `EventType.NODE_PROGRESS`. Spelled as a literal because
#: `core.events` sits *beside* this module, not beneath it, and an agent
#: contract that imports the event bus cannot be unit-tested in isolation.
#: `EventType` is a `StrEnum`, so the bus compares and serializes this
#: identically to the member itself.
NODE_PROGRESS_EVENT: Final = "node.progress"

# `activity(pct=...)` is a completion *fraction*, not a 0-100 percentage. One
# convention has to win: the dashboard renders `pct` straight into a progress
# bar, and a mixed convention shows some agents stuck at 1% forever.
_PCT_MIN: Final = 0.0
_PCT_MAX: Final = 1.0


# ── structural stand-ins for sibling modules ─────────────────────────────


class LLMClient(Protocol):
    """The model handle an agent is given, already bound to its `model_key`.

    Mirrors `core.llm.client.LLMClient` (§5). `Any` on the request/response
    types is load-bearing rather than lazy: the concrete `ChatRequest` /
    `ChatResponse` dataclasses live in `core.llm.types`, and naming them here
    would invert the dependency this module exists to avoid.
    """

    async def chat(self, req: Any, /) -> Any: ...

    def stream(self, req: Any, /) -> AsyncIterator[Any]: ...

    async def structured[T](self, req: Any, schema: type[T], /) -> T: ...


class ToolRegistry(Protocol):
    """The tools an agent may call, already bound to this node for `tool.*` events."""

    def has(self, name: str, /) -> bool: ...

    async def call(self, name: str, arguments: Mapping[str, Any], /) -> Any: ...


@runtime_checkable
class CancelScope(Protocol):
    """Cooperative cancellation (`core.cancel`).

    Agents poll this between steps. Cancellation is cooperative precisely so a
    cancelled node can still flush its partial work and emit a final event
    instead of being torn down mid-write.
    """

    @property
    def cancelled(self) -> bool: ...

    def raise_if_cancelled(self) -> None: ...


class EventEmitter(Protocol):
    """Publishes an event bound to this run (`core.events.bus`).

    `seq` and `ts` are assigned by the bus, never by the caller — that is what
    makes the stream gapless and replayable (§4.1).
    """

    async def emit(
        self,
        type: Any,  # noqa: A002 - matches the bus signature; `EventType` lives in core.events
        *,
        node_id: str | None = None,
        agent: str | None = None,
        **payload: Any,
    ) -> None: ...


class Logger(Protocol):
    """Structural logger so either `logging.Logger` or a bound structlog logger fits.

    Positional-only first argument because stdlib names it `msg` and structlog
    names it `event`; pinning either name would exclude the other.
    """

    def debug(self, msg: str, /, *args: Any) -> None: ...

    def info(self, msg: str, /, *args: Any) -> None: ...

    def warning(self, msg: str, /, *args: Any) -> None: ...

    def error(self, msg: str, /, *args: Any) -> None: ...


# ── spec ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """Static declaration of an agent: identity, routing, and failure budget.

    Frozen because the dispatcher, the router and the dashboard all read the
    same instance concurrently; a spec that could be mutated mid-run would let
    one node's timeout change another node's behaviour.
    """

    #: Stable machine id, e.g. "research". Used as the event `agent` field and
    #: as the per-agent concurrency key, so it must not be a display string.
    name: str
    #: UI label, e.g. "Research Agent".
    display_name: str
    #: Routing key into the LLM router, e.g. "research". Kept separate from
    #: `name` so two agents can share a model, or one agent can be re-pointed
    #: at a cheaper model, without renaming anything the events refer to.
    model_key: str
    #: Wall budget for a single attempt, enforced by the dispatcher. A hang is
    #: converted into a bounded, retryable `TimeoutError` here and nowhere else.
    timeout_s: float = 120.0
    #: `RetryPolicy` from `core.retry`, injected opaquely: this module is the
    #: contract domain agents import, and it must not depend on the retry
    #: implementation. `None` means "dispatcher applies its default policy".
    #: `Any` (not `object`) so the dispatcher can use it without a cast.
    retry: Any = None
    #: Per-agent cap layered *under* the run-wide cap, e.g. one scraper-heavy
    #: agent limited to 2 while the run allows 8. `None` inherits the run cap.
    max_concurrency: int | None = None

    def __post_init__(self) -> None:
        # Validated at construction, not at dispatch: a typo'd spec should fail
        # when the pipeline is defined, not three minutes into a paid run.
        if not self.name:
            raise ValueError("AgentSpec.name must be a non-empty stable id")
        if self.timeout_s <= 0:
            raise ValueError(f"AgentSpec.timeout_s must be positive, got {self.timeout_s!r}")
        if self.max_concurrency is not None and self.max_concurrency < 1:
            raise ValueError(
                f"AgentSpec.max_concurrency must be >= 1 or None, got {self.max_concurrency!r}"
            )


# ── context ──────────────────────────────────────────────────────────────


class AgentContext:
    """Everything an agent may touch. Passed in, never imported.

    Constructed by the dispatcher for exactly one node attempt, so `node_id`
    and the bound `llm`/`tools` handles are already correct for every event the
    agent causes — the agent never has to tag anything itself.
    """

    __slots__ = (
        "_activity",
        "agent",
        "cancel",
        "clock",
        "emit",
        "llm",
        "logger",
        "node_id",
        "run_id",
        "tools",
    )

    def __init__(
        self,
        *,
        run_id: str,
        node_id: str,
        llm: LLMClient,
        tools: ToolRegistry,
        emit: EventEmitter,
        cancel: CancelScope,
        clock: Clock,
        logger: Logger,
        agent: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.node_id = node_id
        self.llm = llm
        self.tools = tools
        self.emit = emit
        self.cancel = cancel
        self.clock = clock
        self.logger = logger
        #: `AgentSpec.name` of the agent running this node. Carried so progress
        #: events are attributable without the UI joining back to the graph.
        self.agent = agent
        self._activity = ""

    @property
    def current_activity(self) -> str:
        """The last text passed to `activity()`; "" before the first call."""
        return self._activity

    async def activity(self, text: str, *, pct: float | None = None) -> None:
        """Set the human-readable "what am I doing right now" string.

        This is the product. The dashboard's central claim is that a user can
        watch a run and see, per agent, the actual work in flight — "searching
        for 'Bolivian tin barons 1900-1930'", "scraping 4/11 sources",
        "drafting section 3 of 7" — instead of a spinner that means nothing.
        That text comes from here and from nowhere else.

        So: call it **before every meaningful step**, not once per node. A node
        that runs for ninety seconds and calls `activity()` once has, from the
        user's point of view, hung. The call is cheap — one bounded-queue
        publish — and it is the only mechanism by which an agent's internal
        progress becomes visible.

        `pct` is an optional completion fraction in [0.0, 1.0] for steps with a
        countable denominator (sources scraped, sections written). Omit it when
        there is no honest denominator; a fabricated bar is worse than none.

        Emits `NODE_PROGRESS`.
        """
        if pct is not None and not (_PCT_MIN <= pct <= _PCT_MAX):
            # Loud, because the alternative (silently clamping) ships a
            # progress bar that lies about work that never happened.
            raise ValueError(f"activity(pct=...) must be a fraction in [0.0, 1.0], got {pct!r}")

        self._activity = text
        payload: dict[str, Any] = {"activity": text}
        if pct is not None:
            payload["pct"] = pct
        await self.emit.emit(
            NODE_PROGRESS_EVENT,
            node_id=self.node_id,
            agent=self.agent,
            **payload,
        )

    def __repr__(self) -> str:
        # Deliberately omits llm/tools/logger: their reprs routinely embed a
        # base URL with an API key in it (see errors.py on the same hazard).
        return (
            f"AgentContext(run_id={self.run_id!r}, node_id={self.node_id!r}, "
            f"agent={self.agent!r}, activity={self._activity!r})"
        )


# ── the agent contract ───────────────────────────────────────────────────


@runtime_checkable
class Agent[I, O](Protocol):
    """An agent: a spec plus one async call over a context.

    Generic over input and output so `pipeline.py` can type the edges between
    nodes — a writer whose input is a `Compilation` cannot be wired to a node
    that produces a `ScopingResult` without mypy noticing.

    Note what is *absent*: no `setup`, no `teardown`, no `on_error`, no
    knowledge of retries, timeouts, concurrency or the DAG. Those are the
    dispatcher's job (§3.4). An agent that knew it was being retried would
    inevitably start making retry decisions, and retry classification would
    stop living in one auditable place.
    """

    @property
    def spec(self) -> AgentSpec: ...

    async def run(self, ctx: AgentContext, inp: I) -> O: ...
