"""FakeClock must be boringly deterministic — every runtime test depends on it."""

from __future__ import annotations

import asyncio

import pytest

from historiador.core.clock import Clock, FakeClock, SystemClock


def test_both_clocks_satisfy_the_protocol() -> None:
    assert isinstance(SystemClock(), Clock)
    assert isinstance(FakeClock(), Clock)


def test_fake_clock_starts_frozen() -> None:
    clock = FakeClock(start=100.0, monotonic_start=5.0)
    assert clock.now() == 100.0
    assert clock.monotonic() == 5.0
    assert clock.now() == 100.0  # time does not move on its own
    assert clock.pending_sleepers == 0
    assert clock.next_deadline is None


async def test_advance_moves_wall_and_monotonic_together() -> None:
    clock = FakeClock(start=1000.0, monotonic_start=0.0)
    await clock.advance(12.5)
    assert clock.monotonic() == 12.5
    assert clock.now() == 1012.5


async def test_advance_rejects_negative_deltas() -> None:
    clock = FakeClock()
    with pytest.raises(ValueError, match="backwards"):
        await clock.advance(-1.0)


async def test_sleepers_wake_in_wake_time_order() -> None:
    clock = FakeClock()
    woken: list[str] = []

    async def sleeper(name: str, delay: float) -> None:
        await clock.sleep(delay)
        woken.append(name)

    # Started in an order deliberately unrelated to their deadlines.
    tasks = [
        asyncio.create_task(sleeper("late", 3.0)),
        asyncio.create_task(sleeper("early", 1.0)),
        asyncio.create_task(sleeper("mid", 2.0)),
    ]
    await clock.wait_for_sleepers(3)

    await clock.advance(3.0)
    await asyncio.gather(*tasks)

    assert woken == ["early", "mid", "late"]
    assert clock.pending_sleepers == 0


async def test_equal_deadlines_break_ties_on_insertion_order() -> None:
    clock = FakeClock()
    woken: list[int] = []

    async def sleeper(index: int) -> None:
        await clock.sleep(1.0)
        woken.append(index)

    tasks: list[asyncio.Task[None]] = []
    for index in range(5):
        tasks.append(asyncio.create_task(sleeper(index)))
        # Register one at a time so "insertion order" is unambiguous.
        await clock.wait_for_sleepers(index + 1)

    await clock.advance(1.0)
    await asyncio.gather(*tasks)

    assert woken == [0, 1, 2, 3, 4]


async def test_partial_advance_leaves_later_sleepers_parked() -> None:
    clock = FakeClock()
    woken: list[str] = []

    async def sleeper(name: str, delay: float) -> None:
        await clock.sleep(delay)
        woken.append(name)

    tasks = [
        asyncio.create_task(sleeper("at_1", 1.0)),
        asyncio.create_task(sleeper("at_10", 10.0)),
    ]
    await clock.wait_for_sleepers(2)

    await clock.advance(1.0)
    assert woken == ["at_1"]
    assert clock.pending_sleepers == 1
    assert clock.next_deadline == 10.0

    await clock.advance(8.0)
    assert woken == ["at_1"]  # not yet due at t=9
    assert clock.monotonic() == 9.0

    await clock.advance(1.0)
    assert woken == ["at_1", "at_10"]
    assert clock.pending_sleepers == 0
    await asyncio.gather(*tasks)


async def test_woken_task_observes_its_own_deadline_not_the_advance_target() -> None:
    """A retry that sleeps 1s must see t=1, even inside an advance(100)."""
    clock = FakeClock(monotonic_start=0.0)
    observed: list[float] = []

    async def sleeper(delay: float) -> None:
        await clock.sleep(delay)
        observed.append(clock.monotonic())

    tasks = [asyncio.create_task(sleeper(d)) for d in (1.0, 4.0, 9.0)]
    await clock.wait_for_sleepers(3)

    await clock.advance(100.0)
    await asyncio.gather(*tasks)

    assert observed == [1.0, 4.0, 9.0]
    assert clock.monotonic() == 100.0


async def test_sleep_scheduled_during_advance_is_picked_up_in_the_same_window() -> None:
    """Backoff chains (sleep → work → sleep) must not need one advance() each."""
    clock = FakeClock()
    marks: list[float] = []

    async def chained() -> None:
        for _ in range(3):
            await clock.sleep(1.0)
            marks.append(clock.monotonic())

    task = asyncio.create_task(chained())
    await clock.wait_for_sleepers(1)

    await clock.advance(5.0)
    await task

    assert marks == [1.0, 2.0, 3.0]
    assert clock.pending_sleepers == 0


async def test_non_positive_sleep_is_a_yield_not_a_parked_sleeper() -> None:
    clock = FakeClock()
    done = False

    async def yielder() -> None:
        nonlocal done
        await clock.sleep(0)
        done = True

    task = asyncio.create_task(yielder())
    # No advance() at all: a zero sleep must resolve on the next loop turn.
    await asyncio.wait_for(task, timeout=1.0)
    assert done is True
    assert clock.pending_sleepers == 0
    assert clock.monotonic() == 0.0


async def test_cancelled_sleeper_stops_counting_toward_quiescence() -> None:
    clock = FakeClock()

    async def sleeper() -> None:
        await clock.sleep(30.0)

    task = asyncio.create_task(sleeper())
    await clock.wait_for_sleepers(1)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert clock.pending_sleepers == 0
    assert clock.next_deadline is None
    # And advancing past its deadline is a no-op rather than an error.
    await clock.advance(60.0)


async def test_wait_for_sleepers_fails_loudly_instead_of_hanging() -> None:
    clock = FakeClock()
    with pytest.raises(AssertionError, match="expected 1 parked sleeper"):
        await clock.wait_for_sleepers(1, max_yields=3)


async def test_system_clock_time_sources_are_sane() -> None:
    clock = SystemClock()
    assert clock.now() > 1_600_000_000  # after 2020, i.e. a real epoch value
    before = clock.monotonic()
    await clock.sleep(0)
    assert clock.monotonic() >= before
