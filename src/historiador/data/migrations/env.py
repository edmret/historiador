"""Alembic environment.

Two things here are load-bearing and easy to get wrong:

1. **The URL comes from the environment first.** ``$HISTORIADOR_DB_URL`` overrides
   ``alembic.ini`` so the test-suite, the daemon and a developer's shell can all point
   the same migration set at different files without ever editing a checked-in file.

2. **Foreign keys are switched on for the migration connection too.** SQLite defaults
   ``PRAGMA foreign_keys`` to OFF *per connection*, and Alembic opens its own. Without
   this, a data migration could insert rows that violate the very constraints the
   migration just created, and nothing would complain until production.

3. **The connection is committed explicitly.** Python's ``sqlite3`` driver
   auto-commits DDL but *not* DML, and Alembic marks SQLite as non-transactional-DDL.
   Without the explicit ``commit()`` a migration that both creates tables and seeds
   rows leaves the tables behind and silently discards the seed data *and* the
   ``alembic_version`` row — a half-migrated database that reports itself as
   un-migrated. This was observed, not theorised.

``render_as_batch`` is enabled because SQLite cannot ``ALTER TABLE ... DROP COLUMN``
or alter a constraint; Alembic's batch mode rebuilds the table instead. Turning it on
now means later migrations do not have to remember to.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, engine_from_config, make_url, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from historiador.data.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """Resolve the URL: environment wins, ``alembic.ini`` is the fallback."""
    env_url = os.environ.get("HISTORIADOR_DB_URL")
    if env_url:
        return env_url
    ini_url = config.get_main_option("sqlalchemy.url")
    if not ini_url:
        raise RuntimeError("No database URL: set HISTORIADOR_DB_URL or sqlalchemy.url")
    return ini_url


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
        compare_server_default=True,
    )


def _enable_foreign_keys(connection: Connection) -> None:
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DBAPI connection (``alembic upgrade head --sql``)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    _enable_foreign_keys(connection)
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_sync(url: str) -> None:
    """Run migrations over a blocking driver (e.g. ``sqlite:///``)."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = url
    engine = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            _do_run_migrations(connection)
            connection.commit()
    finally:
        engine.dispose()


async def run_migrations_async(url: str) -> None:
    """Run migrations over an async driver (``sqlite+aiosqlite:///``, the app default)."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = url
    engine = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_do_run_migrations)
            await connection.commit()
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    """Dispatch on the driver so the same env.py serves both URL flavours."""
    url = _database_url()
    if make_url(url).get_dialect().is_async:
        asyncio.run(run_migrations_async(url))
    else:
        run_migrations_sync(url)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
