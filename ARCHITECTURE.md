# Historiador — Architecture Contract

> **Status:** authoritative. Every module is built against the contracts in this
> document. If an implementation needs to deviate, change this file first.
>
> **Rewrite scope:** full from-scratch. The old `backend/` and `frontend/` trees are
> reference material only — no code is migrated. Product capabilities from `README.md`
> are preserved; implementations are new.

---

## 1. Product goal

Historiador generates researched, narrative histories using a team of specialized
LLM agents, and exposes the *entire* multi-agent execution as a live, inspectable
system.

Two deliverables, one system:

1. **Storyteller runtime** — a native Python agent framework. A `Storyteller`
   orchestrator plans a run and dispatches sub-agents (scoping, research ×N,
   compiler, writer, editor, profile) as nodes in a dependency DAG, with real
   retries, timeouts, cancellation, tracing, and cost accounting.
2. **Task dashboard daemon** — a local daemon and a dark-mode-native, high-density
   web dashboard that shows, in real time, **what every agent is doing right now**:
   which node is running, which LLM call is in flight, which query it just issued,
   which page it is scraping, tokens streaming in, cost accruing, retries firing.

The second is not a status page. It is the primary UI. Observability is a product
feature, not instrumentation.

### Non-negotiables

- No LangChain, no LangGraph, no agent-framework dependency. The runtime is ours.
- Every agent action is an **event**. If it is not an event, the UI cannot show it,
  and it does not exist.
- Events are **ordered, persisted, and replayable**. A browser reconnecting mid-run
  reconstructs exact state — no gaps, no duplicates.
- The runtime has **zero domain imports**. `core/` never imports `domain/`.

---

## 2. Repository layout

```
historiador/
├── ARCHITECTURE.md              # this file — the contract
├── pyproject.toml               # src layout, ruff + mypy strict, pytest
├── Makefile
├── src/historiador/
│   ├── core/                    # ── agent runtime. product-agnostic. no domain imports.
│   │   ├── agent.py             # Agent protocol, AgentSpec, AgentContext, AgentResult
│   │   ├── run.py               # Run, RunNode, RunState, NodeState
│   │   ├── graph.py             # RunGraph: DAG construction + topological readiness
│   │   ├── scheduler.py         # concurrency-limited DAG executor
│   │   ├── dispatcher.py        # single-node execution: timeout, retry, cancel, trace
│   │   ├── retry.py             # RetryPolicy, backoff, jitter, classification
│   │   ├── cancel.py            # CancelScope, cooperative cancellation
│   │   ├── tracing.py           # Span, SpanKind, trace tree assembly
│   │   ├── clock.py             # Clock protocol (real + fake) — no bare time.time()
│   │   ├── errors.py            # typed error hierarchy
│   │   ├── events/
│   │   │   ├── types.py         # frozen event dataclasses + EventType enum
│   │   │   ├── bus.py           # async pub/sub, backpressure, subscriber isolation
│   │   │   └── sink.py          # EventSink protocol (persist / forward)
│   │   ├── llm/
│   │   │   ├── types.py         # Message, ChatRequest, ChatResponse, Usage, ToolCall
│   │   │   ├── client.py        # LLMClient facade: chat, stream, structured
│   │   │   ├── openai_compat.py # OpenAI-compatible HTTP transport
│   │   │   ├── structured.py    # schema-guided JSON + repair ladder
│   │   │   ├── cost.py          # pricing table, Usage → cost
│   │   │   └── router.py        # per-agent model routing
│   │   └── tools/
│   │       ├── base.py          # Tool protocol, ToolRegistry, ToolResult
│   │       └── errors.py
│   ├── domain/                  # ── Historiador product, built on core
│   │   ├── storyteller.py       # the orchestrator agent
│   │   ├── pipeline.py          # DAG definition for a generation run
│   │   ├── agents/              # scoping, research, compiler, writer, editor, profile
│   │   ├── prompts/             # prompt templates, versioned, hot-reloadable
│   │   └── tools/               # search providers, scraper — implement core.tools.base
│   ├── data/
│   │   ├── models.py            # SQLAlchemy 2.0 typed ORM
│   │   ├── repo/                # repositories, one per aggregate
│   │   ├── session.py           # engine, session factory, unit of work
│   │   └── migrations/          # Alembic
│   ├── api/
│   │   ├── app.py               # FastAPI factory
│   │   ├── routers/             # topics, subtopics, profiles, histories, pipeline,
│   │   │                        #   runs, config, notifications, auth
│   │   ├── ws.py                # /ws/runs — resumable event stream
│   │   └── deps.py
│   ├── auth/                    # Stytch magic links + hashed API tokens
│   ├── mcp/                     # MCP server (stdio + SSE) over the service layer
│   ├── services/                # use-cases shared by api/ and mcp/ — no duplication
│   ├── daemon/                  # supervisor + file watcher
│   ├── config.py                # layered settings
│   └── cli.py                   # `historiador` entrypoint
├── web/                         # Vite + React + TS + Tailwind dashboard
├── tests/
│   ├── unit/  integration/  e2e/
└── .env.example
```

### Dependency rule

```
core  ←  domain  ←  services  ←  api / mcp / daemon
              ↖  data  ↙
web → (HTTP + WS only)
```

`core` imports nothing from the layers to its right. Enforced by an import-linter
rule in CI, not by good intentions.

---

## 3. Core runtime contracts

### 3.1 Agent

```python
# core/agent.py
from typing import Protocol, TypeVar, Generic

I = TypeVar("I");  O = TypeVar("O")

@dataclass(frozen=True, slots=True)
class AgentSpec:
    name: str                    # stable id, e.g. "research"
    display_name: str            # UI label, e.g. "Research Agent"
    model_key: str               # routing key into LLMRouter, e.g. "research"
    timeout_s: float = 120.0
    retry: RetryPolicy = RetryPolicy.default()
    max_concurrency: int | None = None   # per-agent cap, None = inherit run cap

class AgentContext:
    """Everything an agent may touch. Passed in, never imported."""
    run_id: str
    node_id: str
    llm: LLMClient               # already bound to this agent's model + events
    tools: ToolRegistry          # already bound to this node for tool.* events
    emit: EventEmitter           # emit(EventType, **payload)
    cancel: CancelScope
    clock: Clock
    logger: Logger

    async def activity(self, text: str, *, pct: float | None = None) -> None:
        """Set the human-readable 'what am I doing right now' string.

        Drives the live UI. Call it liberally — before every meaningful step.
        Emits NODE_PROGRESS.
        """

class Agent(Protocol, Generic[I, O]):
    spec: AgentSpec
    async def run(self, ctx: AgentContext, inp: I) -> O: ...
```

Agents are **pure async functions over a context**. They do not open DB sessions,
do not read global config, do not construct LLM clients, and do not know they are
in a DAG. That is what makes them testable and what makes every action observable.

### 3.2 Run, nodes, states

```python
class RunState(StrEnum):
    PENDING; RUNNING; SUCCEEDED; FAILED; CANCELLED

class NodeState(StrEnum):
    BLOCKED      # deps unmet
    READY        # deps met, awaiting a concurrency slot
    RUNNING
    RETRYING
    SUCCEEDED
    FAILED
    CANCELLED
    SKIPPED      # upstream failed and node is not `optional`
```

```python
@dataclass(slots=True)
class RunNode:
    id: str
    agent: str                   # AgentSpec.name
    label: str                   # UI label, e.g. "Research · Economic causes"
    depends_on: tuple[str, ...]
    input_fn: Callable[[RunResults], Any]   # pulls input from upstream outputs
    optional: bool = False       # failure does not fail the run
    state: NodeState = BLOCKED
    attempt: int = 0
    activity: str = ""           # live 'doing now' text
    started_at: float | None = None
    ended_at: float | None = None
    usage: Usage = Usage.zero()
    error: RunError | None = None
```

`RunGraph` validates at construction: no cycles, no dangling `depends_on`, unique
ids. A malformed graph raises **before** the run starts — never mid-flight.

### 3.3 Scheduler

`Scheduler.execute(graph, *, max_concurrency)` runs the DAG:

- maintains a ready-set; dispatches while a semaphore slot is free
- per-agent concurrency caps layered under the global cap
- a node fails → dependents become `SKIPPED` unless `optional`
- cancellation propagates through `CancelScope`; in-flight nodes get a cooperative
  cancel and a bounded grace period before hard cancel
- the scheduler **never swallows an exception** — every failure becomes a typed
  `RunError` with the node id, attempt number, and cause chain
- deterministic under a `FakeClock`: no `asyncio.sleep` outside `Clock`

### 3.4 Dispatcher

Executes exactly one node attempt and owns the cross-cutting concerns:

```
NODE_STARTED
  → timeout scope (AgentSpec.timeout_s)
    → tracing span
      → agent.run(ctx, inp)
  → on retryable error: NODE_RETRYING, backoff via RetryPolicy, attempt += 1
  → NODE_SUCCEEDED | NODE_FAILED
```

Retry classification lives in `retry.py`, not in agents. Retryable: transport
errors, 429, 5xx, timeouts, malformed structured output. Not retryable: auth
failures, validation errors, cancellation.

---

## 4. Event model

This is the spine of the product. Get it wrong and the dashboard is a lie.

### 4.1 Envelope

```python
@dataclass(frozen=True, slots=True)
class Event:
    run_id: str
    seq: int            # monotonic, gapless, per-run. assigned by the bus, not callers.
    ts: float           # epoch seconds, from Clock
    type: EventType
    node_id: str | None
    agent: str | None
    payload: Mapping[str, Any]   # JSON-serializable. validated per type.
```

**`seq` is the contract.** It is assigned under a per-run lock at publish time,
starts at 1, and never skips. The client tracks the highest `seq` it has applied and
reconnects with `?since_seq=N`. That single integer is what makes the live UI
correct instead of merely animated.

### 4.2 Taxonomy

| Type | Emitted when | Key payload |
|---|---|---|
| `RUN_CREATED` | run persisted | `topic_id`, `graph` (nodes + edges) |
| `RUN_STARTED` | scheduler begins | — |
| `RUN_COMPLETED` | terminal success | `usage`, `cost_usd`, `duration_s` |
| `RUN_FAILED` | terminal failure | `error` |
| `RUN_CANCELLED` | cancelled | `reason` |
| `NODE_READY` | deps satisfied | — |
| `NODE_STARTED` | attempt begins | `attempt` |
| `NODE_PROGRESS` | `ctx.activity(...)` | `activity`, `pct?` |
| `NODE_RETRYING` | retryable failure | `attempt`, `delay_s`, `error` |
| `NODE_SUCCEEDED` | attempt succeeds | `duration_s`, `usage` |
| `NODE_FAILED` | attempts exhausted | `error` |
| `NODE_SKIPPED` | upstream failed | `because` |
| `LLM_REQUEST_STARTED` | request dispatched | `model`, `prompt_tokens_est` |
| `LLM_TOKEN` | streaming delta | `delta` (coalesced, see below) |
| `LLM_REQUEST_COMPLETED` | response done | `usage`, `cost_usd`, `latency_ms` |
| `LLM_REQUEST_FAILED` | request errored | `error`, `status?` |
| `TOOL_STARTED` | tool invoked | `tool`, `args` (redacted) |
| `TOOL_COMPLETED` | tool returned | `tool`, `summary`, `duration_ms` |
| `TOOL_FAILED` | tool errored | `tool`, `error` |
| `ARTIFACT_CREATED` | history/outline written | `kind`, `id`, `title` |
| `LOG` | structured log line | `level`, `message` |

`LLM_TOKEN` is coalesced: deltas are buffered and flushed at most every 50 ms or
256 chars, whichever comes first. Raw per-token events would flood the bus and the
socket for zero perceptual gain.

### 4.3 Bus

- publish is **non-blocking for the producer**; each subscriber has a bounded queue
- a slow subscriber is dropped from the live feed, never allowed to stall a run —
  it reconnects and replays from `since_seq`
- one subscriber raising never affects another (isolated tasks, errors logged)
- `EventSink` implementations: `SqliteEventSink` (durable log), `WebSocketSink`
- persistence is **synchronous with seq assignment** for ordering, batched on write

### 4.4 Replay

`GET /api/runs/{id}/events?since_seq=N` and the WS `subscribe` frame share one code
path: read persisted events `> N`, then attach to the live bus, de-duplicating on
`seq`. Reconnection is exact, not approximate.

---

## 5. LLM layer

```python
class LLMClient:
    async def chat(self, req: ChatRequest) -> ChatResponse
    def stream(self, req: ChatRequest) -> AsyncIterator[StreamChunk]
    async def structured[T](self, req: ChatRequest, schema: type[T]) -> T
```

- `structured` repair ladder: parse → extract fenced/embedded JSON → schema-guided
  re-ask (one attempt) → typed `StructuredOutputError`. Every rung logged.
- `Usage` carries `prompt_tokens`, `completion_tokens`, `cached_tokens`; `cost.py`
  maps to USD via a pricing table with an explicit `unknown_model` path (cost `None`,
  never a fabricated number).
- `LLMRouter` resolves an agent's `model_key` → `{base_url, api_key, model}` from
  layered config, so per-agent model selection survives from the old system.
- Every call emits `LLM_*` events bound to the calling node. This is automatic —
  agents cannot forget to instrument.
- Retries on 429/5xx honor `Retry-After`.

---

## 6. Data layer

SQLAlchemy 2.0, `Mapped[...]` typed models, async SQLite via aiosqlite, Alembic
migrations. Repositories per aggregate; **no ORM objects escape the service layer** —
routers see Pydantic schemas only.

Tables: `topics`, `subtopics`, `histories`, `profiles`, `feedback_records`,
`scoping_messages`, `research_sources`, `push_subscriptions`, `app_config`,
`api_tokens`, plus new: `runs`, `run_nodes`, `events`.

```
events(run_id TEXT, seq INTEGER, ts REAL, type TEXT, node_id TEXT,
       agent TEXT, payload JSON, PRIMARY KEY (run_id, seq))
```

The composite PK gives ordering, gapless-ness, and idempotent writes in one
constraint. Index `runs(status, created_at DESC)` for the dashboard's run list.

SQLite runs in WAL mode with `busy_timeout`; writes funnel through a single writer
task to keep the event log append-only and contention-free.

---

## 7. API surface

REST mirrors the README's endpoints (topics, subtopics, scoping, profiles,
histories, feedback, pipeline, config, notifications, auth), plus:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/runs` | list runs (filter status, topic) |
| GET | `/api/runs/{id}` | run detail: graph, node states, usage, cost |
| GET | `/api/runs/{id}/events?since_seq=` | replay |
| POST | `/api/runs/{id}/cancel` | cooperative cancel |
| WS | `/ws/runs` | live events |

### WebSocket protocol

```
client → {"op":"subscribe","run_id":"…","since_seq":0}
server → {"op":"snapshot","run":{…},"seq":N}        # authoritative state at N
server → {"op":"event","event":{…}}                 # then deltas, seq N+1, N+2, …
client → {"op":"ping"}  /  server → {"op":"pong"}
server → {"op":"error","code":"…","message":"…"}
```

Snapshot-then-delta with a shared `seq` watermark. The client never guesses.
Heartbeats every 20 s; server drops silent sockets at 60 s.

---

## 8. Daemon

`historiador daemon` supervises the API server, the event writer, and a
`watchfiles` watcher over `domain/prompts/` and config. On change: validate, hot-swap
the prompt registry, emit a `config.changed` event so open dashboards update without
a reload. PID/lock file prevents double-start. Graceful shutdown drains in-flight
runs within a bounded window, then cancels and persists terminal state — a killed
daemon never leaves a run stuck in `RUNNING`. Structured JSON logs.

---

## 9. Dashboard

Vite + React + TypeScript (strict) + Tailwind. Dark-mode native — dark is the
designed state, not an inverted afterthought.

- **Run view** — the centerpiece. Per-agent lanes on a live timeline; each running
  node shows its `activity` string, elapsed timer, attempt badge, streaming token
  counter, accruing cost.
- **Graph view** — the DAG with live node states.
- **Event stream** — virtualized, filterable by node/type/level, follows tail with a
  sticky "jump to live" affordance.
- **Kanban / history viewer / profiles / settings** — the README's product surface.
- **Command palette** (`⌘K`) for navigation and actions.

State: a single reducer over the event stream, so the UI is a pure function of
`(snapshot, events[])`. Same reducer runs in tests against recorded event logs.
Animation is spring-based and interruptible; motion respects
`prefers-reduced-motion`. Every interactive element is keyboard reachable and
labeled — density is not an excuse for inaccessibility.

---

## 10. Conventions

- Python ≥ 3.12, `ruff` (lint + format), `mypy --strict` on `src/`.
- No bare `except Exception` outside a designated boundary; no swallowed errors.
- No wall-clock or `asyncio.sleep` outside `Clock` — tests must be deterministic.
- Secrets never logged, never in events; `args` payloads pass a redactor.
- Every public function typed; no `Any` without a comment justifying it.
- Tests: `pytest` + `pytest-asyncio` with a `FakeLLM` and `FakeClock`; `vitest` +
  Testing Library for the UI; Playwright for the live-run e2e. The runtime is
  testable without network access — that is a design requirement, not a nicety.

---

## 11. Module ownership

Parallel work is partitioned so no two workstreams write the same file.

| # | Workstream | Owns | Depends on |
|---|---|---|---|
| 2 | Runtime | `core/{agent,run,graph,scheduler,dispatcher,retry,cancel,tracing,clock,errors}.py` | — |
| 3 | Events | `core/events/**` | clock, errors |
| 4 | LLM | `core/llm/**` | events, retry |
| 5 | Data | `data/**` | — |
| 6 | Domain agents | `domain/{storyteller,pipeline}.py`, `domain/agents/**`, `domain/prompts/**` | 2,3,4,7 |
| 7 | Tools | `core/tools/**`, `domain/tools/**` | events |
| 8 | API + auth | `api/**`, `auth/**`, `services/**` | 5,6 |
| 9 | Daemon | `daemon/**`, `cli.py` | 8 |
| 10 | Dashboard | `web/**` | 8 (protocol only) |
| 11 | MCP | `mcp/**` | services |
| 12 | Tests | `tests/**`, `web/**/*.test.tsx` | all |

Shared files — `pyproject.toml`, `Makefile`, this document — are edited by the
orchestrator only.
