"""Async pub/sub event bus with per-subscriber backpressure and isolation.

Architecture contract (ARCHITECTURE.md §4.3)
--------------------------------------------
* **Publish is non-blocking for the producer.**  Slow subscribers never stall
  a run — they are dropped from the live feed and may replay via
  ``since_seq``.
* **Each subscriber has a bounded queue.**  When the queue is full the
  subscriber is considered overloaded; it is forcibly removed so the producer
  can continue.
* **Subscriber isolation.**  One subscriber raising an exception does not
  affect any other subscriber; errors are logged, not propagated.
* **``seq`` is assigned under a per-run lock** so it is monotonic, gapless,
  and ordered with respect to the durable persistence path
  (``EventSink.write`` is called inside the lock before the event is fanned
  out to live subscribers).

Usage
-----
::

    bus = EventBus(run_id="run-1", clock=SystemClock())
    token = bus.subscribe(queue_size=256)

    async def consumer() -> None:
        async for event in bus.listen(token):
            process(event)

    consumer_task = asyncio.create_task(consumer())

    await bus.publish(EventType.RUN_STARTED, payload={})
    await bus.close()
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from historiador.core.events.types import Event, EventType

if TYPE_CHECKING:
    from historiador.core.clock import Clock
    from historiador.core.events.sink import EventSink

__all__ = ["EventBus", "SubscriberToken"]

_log = logging.getLogger(__name__)

# The sentinel placed on a subscriber queue to signal that the bus is closed
# and no further events will arrive.
_SENTINEL: object = object()

# Default queue depth.  256 events is roughly 2-3 minutes of a busy run at
# the expected publish rate (coalesced LLM tokens + node transitions).
_DEFAULT_QUEUE_SIZE: int = 256


@dataclass(frozen=True, slots=True)
class SubscriberToken:
    """Opaque handle returned by :meth:`EventBus.subscribe`.

    Pass this to :meth:`EventBus.listen` or :meth:`EventBus.unsubscribe`.
    Equality is identity-based — two tokens from the same bus are always
    distinct even if they were created with the same arguments.
    """

    _id: int


@dataclass
class _Subscriber:
    """Internal per-subscriber state."""

    token: SubscriberToken
    queue: asyncio.Queue[Event | object]  # object = sentinel


class EventBus:
    """Per-run async event bus.

    One bus per run; the bus lifetime matches the run lifetime.  Create it
    before the scheduler starts and close it after the terminal event has been
    published.

    Parameters
    ----------
    run_id:
        Stable identifier for the run.  Stamped onto every :class:`Event`.
    clock:
        Time source; ``clock.now()`` provides ``Event.ts``.
    sink:
        Optional :class:`~historiador.core.events.sink.EventSink` that
        receives every event before it is fanned out to live subscribers.
        Persistence is synchronous-with-``seq``-assignment: the sink writes
        inside the lock so the event is durable before any subscriber sees it.
    """

    def __init__(
        self,
        run_id: str,
        clock: Clock,
        sink: EventSink | None = None,
    ) -> None:
        self._run_id = run_id
        self._clock = clock
        self._sink = sink
        self._lock: asyncio.Lock = asyncio.Lock()
        self._seq: int = 0
        self._subscribers: dict[int, _Subscriber] = {}
        self._next_id: int = 0
        self._closed: bool = False

    # ── subscribe / unsubscribe ────────────────────────────────────────────

    def subscribe(self, *, queue_size: int = _DEFAULT_QUEUE_SIZE) -> SubscriberToken:
        """Register a new subscriber and return an opaque token.

        The subscriber will receive every event published *after* this call.
        Prior events are not replayed; use the sink for historical replay.

        Parameters
        ----------
        queue_size:
            Maximum number of events buffered before the subscriber is
            considered overloaded and forcibly dropped.  Default: 256.

        Returns
        -------
        SubscriberToken
            Pass this to :meth:`listen` or :meth:`unsubscribe`.
        """
        sub_id = self._next_id
        self._next_id += 1
        token = SubscriberToken(_id=sub_id)
        queue: asyncio.Queue[Event | object] = asyncio.Queue(maxsize=queue_size)
        self._subscribers[sub_id] = _Subscriber(token=token, queue=queue)
        return token

    def unsubscribe(self, token: SubscriberToken) -> None:
        """Remove a subscriber.  Safe to call even if already unsubscribed."""
        sub = self._subscribers.pop(token._id, None)
        if sub is not None:
            # Unblock any task blocked in `listen` by placing the sentinel.
            try:
                sub.queue.put_nowait(_SENTINEL)
            except asyncio.QueueFull:
                # Queue full — the listener task will time out on next event
                # delivery anyway, but place sentinel to at least try.
                pass

    async def listen(self, token: SubscriberToken) -> AsyncIterator[Event]:
        """Yield events for the given subscriber until the bus is closed.

        The iterator terminates when:
        * the bus is closed (via :meth:`close`), or
        * the subscriber is dropped for being overloaded.

        Parameters
        ----------
        token:
            The token returned by :meth:`subscribe`.

        Yields
        ------
        Event
            Events in ``seq`` order.

        Raises
        ------
        KeyError
            If ``token`` was never registered with this bus.
        """
        sub = self._subscribers.get(token._id)
        if sub is None:
            raise KeyError(f"unknown subscriber token: {token}")

        while True:
            item = await sub.queue.get()
            if item is _SENTINEL:
                break
            # item is guaranteed to be an Event here (only sentinel and Events
            # are ever placed on the queue).
            yield item  # type: ignore[misc]

    # ── publish ────────────────────────────────────────────────────────────

    async def publish(
        self,
        event_type: EventType,
        *,
        payload: dict[str, object],
        node_id: str | None = None,
        agent: str | None = None,
    ) -> Event:
        """Assign a ``seq``, build the :class:`Event`, persist it, and fan out.

        The entire assign-persist-fan-out pipeline runs under a single
        ``asyncio.Lock``, which guarantees:

        * ``seq`` values are gapless and monotonically increasing.
        * The sink receives events in the same order as subscribers.
        * Concurrent publishers do not interleave their ``seq`` slots.

        Slow subscribers (full queue) are silently dropped; they can replay
        missed events from the sink's durable store.

        Parameters
        ----------
        event_type:
            The :class:`EventType` discriminator.
        payload:
            A flat dict of JSON-serialisable values.  The caller is
            responsible for redacting secrets before this point.
        node_id:
            The emitting ``RunNode.id``, or ``None`` for run-level events.
        agent:
            The emitting ``AgentSpec.name``, or ``None`` for run-level events.

        Returns
        -------
        Event
            The fully-assembled event with its assigned ``seq``.

        Raises
        ------
        RuntimeError
            If called after :meth:`close`.
        """
        async with self._lock:
            if self._closed:
                raise RuntimeError(
                    f"EventBus for run {self._run_id!r} is closed; cannot publish"
                )
            self._seq += 1
            event = Event(
                run_id=self._run_id,
                seq=self._seq,
                ts=self._clock.now(),
                type=event_type,
                node_id=node_id,
                agent=agent,
                payload=payload,
            )

            # Persist before fan-out — the sink is the source of truth.
            if self._sink is not None:
                try:
                    await self._sink.write(event)
                except Exception:
                    _log.exception(
                        "EventSink.write failed for run=%s seq=%d type=%s — "
                        "continuing without persistence",
                        self._run_id,
                        event.seq,
                        event.type,
                    )

            # Fan-out: try non-blocking put; drop slow subscribers.
            overloaded: list[int] = []
            for sub_id, sub in self._subscribers.items():
                try:
                    sub.queue.put_nowait(event)
                except asyncio.QueueFull:
                    overloaded.append(sub_id)
                    _log.warning(
                        "Subscriber %d is too slow (queue full at capacity %d) "
                        "for run=%s — dropping from live feed",
                        sub_id,
                        sub.queue.maxsize,
                        self._run_id,
                    )

            for sub_id in overloaded:
                sub = self._subscribers.pop(sub_id, None)
                if sub is not None:
                    # Attempt to wake the listener so it exits cleanly.
                    try:
                        sub.queue.put_nowait(_SENTINEL)
                    except asyncio.QueueFull:
                        pass  # listener will be stuck; nothing more we can do

        return event

    # ── lifecycle ──────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Signal all subscribers that the bus is done and no further events
        will arrive.

        Idempotent: safe to call multiple times.
        """
        async with self._lock:
            if self._closed:
                return
            self._closed = True

        # Signal every active subscriber outside the lock so we don't hold it
        # while they process the sentinel.
        for sub in list(self._subscribers.values()):
            try:
                sub.queue.put_nowait(_SENTINEL)
            except asyncio.QueueFull:
                pass  # subscriber is already overloaded; it will be dropped

    @property
    def run_id(self) -> str:
        """The run identifier this bus is scoped to."""
        return self._run_id

    @property
    def last_seq(self) -> int:
        """The highest ``seq`` published so far (0 before first publish)."""
        return self._seq

    @property
    def is_closed(self) -> bool:
        """``True`` once :meth:`close` has been called."""
        return self._closed

    @property
    def subscriber_count(self) -> int:
        """Number of currently active subscribers."""
        return len(self._subscribers)

    # ── context manager ────────────────────────────────────────────────────

    async def __aenter__(self) -> EventBus:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()


# ── helpers for emitters ──────────────────────────────────────────────────

#: A callable that agents and system components use to emit events without
#: holding a direct reference to the bus.
#:
#: Signature::
#:
#:     async def emit(event_type, *, payload, node_id=None, agent=None) -> Event
#:
#: Built by :func:`make_emitter`.
EventEmitter = "EventBus.publish"  # alias for documentation only


def make_emitter(
    bus: EventBus,
    *,
    node_id: str | None = None,
    agent: str | None = None,
) -> "BoundEmitter":
    """Return a partially-applied publish function pre-loaded with node context.

    The returned callable has the signature::

        async def emit(event_type, *, payload) -> Event

    so agent code never sees the bus directly and cannot accidentally publish
    events for a different node.

    Parameters
    ----------
    bus:
        The bus to publish on.
    node_id:
        Bound ``RunNode.id`` for all emitted events.
    agent:
        Bound ``AgentSpec.name`` for all emitted events.
    """

    async def emit(
        event_type: EventType,
        *,
        payload: dict[str, object],
    ) -> Event:
        return await bus.publish(
            event_type,
            payload=payload,
            node_id=node_id,
            agent=agent,
        )

    return emit


#: Type alias for the partial emitter returned by :func:`make_emitter`.
from collections.abc import Callable, Coroutine  # noqa: E402 — after the function definition

BoundEmitter = Callable[[EventType, str], Coroutine[None, None, Event]]
