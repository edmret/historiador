"""Engine, session factory, and the single-writer unit of work.

Why this file looks the way it does
-----------------------------------

**SQLite needs to be told the truth about itself.** Four pragmas are set on *every*
connection, because SQLite's defaults are wrong for a live multi-agent daemon:

``foreign_keys=ON``
    SQLite ships with foreign key enforcement **off**. Every ``ON DELETE CASCADE`` in
    ``models.py`` is inert without this, and orphaned rows accumulate silently — the
    classic SQLite bug. It is per-connection, not per-database, so it must be re-set
    on each pooled connection, not once at startup.

``journal_mode=WAL``
    Write-ahead logging lets readers proceed while the single writer commits. Without
    it the dashboard's polling reads would block the event writer and vice versa. WAL
    is persistent in the database file, but re-asserting it is free and makes a fresh
    file correct on first connect.

``busy_timeout``
    Turns "database is locked" from an immediate exception into a bounded wait. Even
    with one writer task, checkpointing and external readers (a ``sqlite3`` shell,
    a backup) can hold the file briefly.

``synchronous=NORMAL``
    The WAL-appropriate durability setting: safe against process crash, and only at
    risk from an OS-level crash. ``FULL`` would fsync on every commit and cap the
    event log at a few hundred writes/second, which the token stream would exceed.

**All writes funnel through one task** (ARCHITECTURE.md §6). A single
:class:`asyncio.Queue` consumer owns every mutating transaction. This buys three
things that matter more than write parallelism (which SQLite does not have anyway):

1. The event log stays genuinely append-only — no interleaved transactions can
   commit out of order.
2. ``SQLITE_BUSY`` contention between application tasks becomes structurally
   impossible instead of merely unlikely.
3. Backpressure is observable: :attr:`Database.write_backlog` is a real number the
   daemon can export, rather than a hidden pile of blocked tasks.

Reads bypass the queue entirely — under WAL they never block and never block anyone.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Final, Protocol, Self, runtime_checkable

from sqlalchemy import event, text
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import ConnectionPoolEntry, StaticPool

from historiador.data.models import Base

DEFAULT_BUSY_TIMEOUT_MS: Final[int] = 5_000


@runtime_checkable
class Clock(Protocol):
    """Minimal structural time source.

    Deliberately *not* imported from ``core.clock``: the data layer must stay
    importable on its own (ARCHITECTURE.md §2 dependency rule), and a structural
    Protocol means the real ``core`` clock — and any ``FakeClock`` in tests —
    satisfies it without either side depending on the other.
    """

    def now(self) -> float:
        """Epoch seconds. The only sanctioned source of 'now' in this layer."""
        ...


class SystemClock:
    """Wall-clock implementation of :class:`Clock`.

    Exists so that production code still receives a clock *object*: there is no code
    path in this layer that reads the wall clock directly.
    """

    __slots__ = ()

    def now(self) -> float:
        import time

        return time.time()


def now_datetime(clock: Clock) -> datetime:
    """The clock's epoch seconds as an aware UTC ``datetime``.

    Product tables store ``DATETIME``; the runtime speaks epoch floats. This is the
    single conversion point, so a ``FakeClock`` in tests controls both.
    """
    return datetime.fromtimestamp(clock.now(), tz=UTC)


class DatabaseNotStartedError(RuntimeError):
    """Raised when a write is submitted before the writer task exists.

    A dedicated type (rather than a bare ``RuntimeError``) so a supervisor can
    distinguish "you forgot to call start()" from a genuine runtime fault.
    """


def _is_memory_url(url: str) -> bool:
    return ":memory:" in url or "mode=memory" in url


def create_engine(
    url: str,
    *,
    echo: bool = False,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
) -> AsyncEngine:
    """Build an async engine with the SQLite pragmas this application requires.

    An in-memory URL is pinned to :class:`~sqlalchemy.pool.StaticPool`, because every
    new connection to ``:memory:`` is a *different, empty* database — pooling normally
    would make a test's schema vanish between statements.
    """
    kwargs: dict[str, Any] = {"echo": echo, "future": True}
    if _is_memory_url(url):
        kwargs["poolclass"] = StaticPool
        kwargs["connect_args"] = {"check_same_thread": False}

    engine = create_async_engine(url, **kwargs)

    if engine.dialect.name == "sqlite":

        @event.listens_for(engine.sync_engine, "connect")
        def _apply_pragmas(
            dbapi_connection: DBAPIConnection,
            _record: ConnectionPoolEntry,
        ) -> None:
            cursor = dbapi_connection.cursor()
            try:
                # Order matters: journal_mode must be set before the first write, and
                # foreign_keys must be set outside a transaction to take effect.
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
                cursor.execute("PRAGMA synchronous=NORMAL")
            finally:
                cursor.close()

    return engine


class Database:
    """Owns the engine, the session factory, and the single writer task.

    Usage::

        db = Database("sqlite+aiosqlite:///historiador.db")
        await db.start()
        try:
            run = await db.write(lambda s: RunRepo(s).create(new_run))
            async with db.read() as session:
                events = await EventRepo(session).read_since(run.id, 0, 100)
        finally:
            await db.aclose()
    """

    def __init__(
        self,
        url: str,
        *,
        echo: bool = False,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
        write_queue_maxsize: int = 0,
        clock: Clock | None = None,
    ) -> None:
        self._engine = create_engine(url, echo=echo, busy_timeout_ms=busy_timeout_ms)
        self._sessionmaker = async_sessionmaker(
            self._engine,
            expire_on_commit=False,
            autoflush=False,
        )
        # `Any` result type: the queue is heterogeneous by construction — each job
        # carries its own result type, recovered by the generic signature of `write`.
        self._queue: asyncio.Queue[
            tuple[Callable[[AsyncSession], Awaitable[Any]], asyncio.Future[Any]] | None
        ] = asyncio.Queue(maxsize=write_queue_maxsize)
        self._writer: asyncio.Task[None] | None = None
        self._clock: Clock = clock if clock is not None else SystemClock()

    # ── lifecycle ───────────────────────────────────────────────────────────────

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @property
    def clock(self) -> Clock:
        return self._clock

    @property
    def write_backlog(self) -> int:
        """Queued-but-not-yet-committed write jobs. Export this as a daemon metric."""
        return self._queue.qsize()

    async def start(self) -> None:
        """Spawn the single writer task. Idempotent."""
        if self._writer is None or self._writer.done():
            self._writer = asyncio.create_task(self._writer_loop(), name="historiador-db-writer")

    async def aclose(self) -> None:
        """Drain the write queue, stop the writer, and dispose the pool.

        Draining rather than cancelling is deliberate: ARCHITECTURE.md §8 requires a
        killed daemon to persist terminal state, so already-accepted writes must land
        before the engine goes away.
        """
        if self._writer is not None:
            await self._queue.put(None)
            await self._writer
            self._writer = None
        await self._engine.dispose()

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # ── schema bootstrap ────────────────────────────────────────────────────────

    async def create_all(self) -> None:
        """Create every table from the ORM metadata.

        Bootstrap/test convenience only. Alembic is the authority on production
        schema; ``tests/unit/test_models.py`` asserts the two agree, so this shortcut
        can never quietly diverge from the migration.
        """
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    # ── reads ───────────────────────────────────────────────────────────────────

    @asynccontextmanager
    async def read(self) -> AsyncIterator[AsyncSession]:
        """A read-only session. Concurrent with everything else, thanks to WAL."""
        async with self._sessionmaker() as session:
            yield session

    # ── writes ──────────────────────────────────────────────────────────────────

    async def write[T](self, op: Callable[[AsyncSession], Awaitable[T]]) -> T:
        """Run ``op`` on the single writer task, in its own transaction.

        The awaited result — or the exception ``op`` raised — is handed back to the
        caller, so callers experience an ordinary ``await`` while the database
        experiences exactly one writer.
        """
        if self._writer is None or self._writer.done():
            raise DatabaseNotStartedError(
                "Database.start() must be awaited before submitting writes"
            )
        future: asyncio.Future[T] = asyncio.get_running_loop().create_future()
        # `Any`-typed queue slot; the generic signature restores T for the caller.
        await self._queue.put((op, future))
        return await future

    async def _writer_loop(self) -> None:
        """Serially execute queued write jobs, one transaction each.

        This is the *designated error boundary* referred to in ARCHITECTURE.md §10:
        the writer task must survive any job failure, otherwise one bad write would
        silently stop every future write in the process. The exception is not
        swallowed — it is transferred to the caller's future and re-raised there.
        """
        while True:
            job = await self._queue.get()
            try:
                if job is None:
                    return
                op, future = job
                try:
                    async with self._sessionmaker() as session, session.begin():
                        result = await op(session)
                except asyncio.CancelledError:
                    if not future.done():
                        future.cancel()
                    raise
                except Exception as exc:  # designated boundary; re-raised in the caller
                    if not future.done():
                        future.set_exception(exc)
                else:
                    if not future.done():
                        future.set_result(result)
            finally:
                self._queue.task_done()


async def read_pragma(engine: AsyncEngine, pragma: str) -> Any:
    """Read a pragma back from a live connection.

    Used by the tests to prove the pragmas actually took effect rather than merely
    having been executed. Returns whatever SQLite returns — hence ``Any``.
    """
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(f"PRAGMA {pragma}")
        row = result.first()
    return None if row is None else row[0]


async def ping(engine: AsyncEngine) -> bool:
    """Cheap liveness probe for the daemon's health endpoint."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return True


__all__ = [
    "DEFAULT_BUSY_TIMEOUT_MS",
    "Clock",
    "Database",
    "DatabaseNotStartedError",
    "SystemClock",
    "create_engine",
    "now_datetime",
    "ping",
    "read_pragma",
]
