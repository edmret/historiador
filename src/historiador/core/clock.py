"""Time as an injected dependency.

Every deadline, backoff, timeout and duration in the runtime flows through a
`Clock`. Nothing else in this codebase may call `time.*` or `asyncio.sleep`
directly: a scheduler that sleeps on the real event loop can only be tested by
actually waiting, which makes the DAG/retry/timeout tests slow *and* flaky. With
`FakeClock` the same code runs on virtual time, so a test for "retry three times
with exponential backoff up to 30s" finishes in microseconds and is exactly
reproducible.

`SystemClock` and `FakeClock` are the only two places in `src/` allowed to touch
the real clock or the loop's sleep primitive.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import time
from typing import Protocol, runtime_checkable

__all__ = ["Clock", "FakeClock", "SystemClock"]


@runtime_checkable
class Clock(Protocol):
    """The only time source the runtime is allowed to use.

    Wall time and monotonic time are deliberately separate methods. Wall time is
    what events and persisted rows carry (a human reading the dashboard needs a
    real timestamp); monotonic time is what durations, deadlines and backoff are
    measured with, because a wall clock can jump backwards during an NTP
    correction and would silently corrupt every elapsed-time measurement.
    """

    def now(self) -> float:
        """Epoch seconds. Use for event `ts` and anything a human will read."""
        ...

    def monotonic(self) -> float:
        """Monotonic seconds. Use for durations, deadlines and backoff."""
        ...

    async def sleep(self, seconds: float) -> None:
        """Suspend the calling task for `seconds` of this clock's time."""
        ...


class SystemClock:
    """Production clock: the real wall clock and the real event loop.

    Stateless, so a single instance can be shared by the whole process; it is
    still passed by injection rather than imported as a global, because that is
    what lets a test swap in `FakeClock` without patching modules.
    """

    __slots__ = ()

    def now(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        # The one sanctioned `asyncio.sleep` call in the codebase.
        await asyncio.sleep(seconds)

    def __repr__(self) -> str:
        return "SystemClock()"


class _Sleeper:
    """A parked task waiting for virtual time to reach `deadline`.

    A tiny class rather than a raw tuple so the heap entries stay comparable:
    heapq would otherwise try to order the futures when deadlines and sequence
    numbers tie, and `asyncio.Future` is not orderable.
    """

    __slots__ = ("deadline", "future", "seq")

    def __init__(self, deadline: float, seq: int, future: asyncio.Future[None]) -> None:
        self.deadline = deadline
        self.seq = seq
        self.future = future

    def __lt__(self, other: _Sleeper) -> bool:
        # Ties break on insertion order: two agents that both back off 5s must
        # resume in the order they went to sleep, or a "concurrent retries"
        # test would pass or fail depending on dict/heap internals.
        if self.deadline != other.deadline:
            return self.deadline < other.deadline
        return self.seq < other.seq


class FakeClock:
    """Deterministic virtual-time clock for tests.

    Time only moves when a test says so. Sleepers park on a heap keyed by their
    wake time; `advance()` releases everyone whose deadline falls inside the
    window, *in wake-time order*, setting the clock to each deadline before
    waking the task and yielding to the event loop in between. That ordering is
    the whole point: a woken task observes exactly the time it asked for, and
    work it schedules while running (a retry backoff, a nested timeout) is
    picked up by the same `advance()` call if it also falls inside the window.
    """

    __slots__ = ("_counter", "_monotonic", "_sleepers", "_wall")

    def __init__(self, *, start: float = 1_700_000_000.0, monotonic_start: float = 0.0) -> None:
        # A plausible epoch default (not 0.0) so anything that formats the
        # timestamp in a test renders a real date instead of 1970.
        self._wall = start
        self._monotonic = monotonic_start
        self._sleepers: list[_Sleeper] = []
        self._counter = itertools.count()

    # ── Clock protocol ────────────────────────────────────────────────────

    def now(self) -> float:
        return self._wall

    def monotonic(self) -> float:
        return self._monotonic

    async def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            # A non-positive sleep is a cooperative yield, not a parked
            # sleeper: counting it in `pending_sleepers` would make quiescence
            # checks report phantom waiters that no `advance()` can release.
            await self._yield()
            return

        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        sleeper = _Sleeper(self._monotonic + seconds, next(self._counter), future)
        heapq.heappush(self._sleepers, sleeper)
        try:
            await future
        except asyncio.CancelledError:
            # Leave the entry on the heap; `advance()` and `pending_sleepers`
            # both skip finished futures. Removing it here would cost O(n) on
            # every cancellation for no observable benefit.
            raise

    # ── Test-driver API ───────────────────────────────────────────────────

    async def advance(self, seconds: float) -> None:
        """Move virtual time forward by `seconds`, releasing sleepers in order.

        Raises `ValueError` on a negative delta: a clock that can run backwards
        would let a test "prove" behaviour the production clock can never
        produce.
        """
        if seconds < 0:
            raise ValueError(f"cannot advance a clock backwards: {seconds!r}")

        target = self._monotonic + seconds
        while True:
            sleeper = self._next_due(target)
            if sleeper is None:
                break
            self._set_monotonic(sleeper.deadline)
            sleeper.future.set_result(None)
            # Yield between wakes so the woken task runs to its next suspension
            # point while the clock still reads *its* deadline, before the next
            # sleeper is released.
            await self._yield()

        self._set_monotonic(target)
        # Final yield so tasks woken exactly at `target` have run before the
        # caller starts asserting on their side effects.
        await self._yield()

    @property
    def pending_sleepers(self) -> int:
        """How many tasks are parked in `sleep()` right now.

        Quiescence assertion: after a run completes, this must be 0. A non-zero
        count means a task is still waiting on a timer nobody will fire — a leak
        that in production becomes a node stuck in RUNNING forever.
        """
        return sum(1 for s in self._sleepers if not s.future.done())

    @property
    def next_deadline(self) -> float | None:
        """Monotonic time of the earliest parked sleeper, or None if quiescent."""
        candidates = [s.deadline for s in self._sleepers if not s.future.done()]
        return min(candidates) if candidates else None

    async def wait_for_sleepers(self, count: int, *, max_yields: int = 1000) -> None:
        """Yield until at least `count` tasks are parked in `sleep()`.

        Tests need a deterministic point at which every concurrent sleeper has
        registered, otherwise `advance()` can run before a task has even reached
        its `sleep()` call and the wake order becomes a scheduling accident.
        Bounded so a never-arriving sleeper fails loudly instead of hanging.
        """
        for _ in range(max_yields):
            if self.pending_sleepers >= count:
                return
            await self._yield()
        raise AssertionError(
            f"expected {count} parked sleeper(s), got {self.pending_sleepers} "
            f"after {max_yields} event-loop yields"
        )

    # ── internals ─────────────────────────────────────────────────────────

    def _next_due(self, target: float) -> _Sleeper | None:
        """Pop the earliest sleeper due at or before `target`, skipping cancelled ones."""
        while self._sleepers:
            if self._sleepers[0].deadline > target:
                return None
            sleeper = heapq.heappop(self._sleepers)
            if not sleeper.future.done():
                return sleeper
        return None

    def _set_monotonic(self, value: float) -> None:
        # Wall and monotonic advance by the same delta so a test that mixes
        # `now()` (event timestamps) and `monotonic()` (durations) stays
        # self-consistent.
        delta = value - self._monotonic
        if delta <= 0:
            return
        self._monotonic = value
        self._wall += delta

    @staticmethod
    async def _yield() -> None:
        # `asyncio.sleep(0)` is the documented way to hand control back to the
        # loop for exactly one iteration; sanctioned here for the same reason as
        # in SystemClock — this module is the boundary.
        await asyncio.sleep(0)

    def __repr__(self) -> str:
        return (
            f"FakeClock(now={self._wall!r}, monotonic={self._monotonic!r}, "
            f"pending_sleepers={self.pending_sleepers})"
        )
