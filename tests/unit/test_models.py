"""Schema-level tests: the ORM, the constraints, and the Alembic migration.

These are deliberately *assertions about the database*, not about Python objects. A
model file can look correct and still produce a schema with foreign keys that do
nothing, so almost every test here inspects the DDL SQLite actually built.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from historiador.data import models as orm

# Alembic migration modules start with numbers, so they can't be imported directly.
# Use importlib.import_module() to load by string path.
_migration_0001 = import_module("historiador.data.migrations.versions.0001_initial")
DEFAULT_APP_CONFIG = _migration_0001.DEFAULT_APP_CONFIG
DEFAULT_PROFILE_ID = _migration_0001.DEFAULT_PROFILE_ID

PROJECT_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_TABLES = {
    "api_tokens",
    "app_config",
    "events",
    "feedback_records",
    "histories",
    "profiles",
    "push_subscriptions",
    "research_sources",
    "run_nodes",
    "runs",
    "scoping_messages",
    "subtopics",
    "topics",
}


# ── helpers ─────────────────────────────────────────────────────────────────────


def _alembic_config(db_path: Path) -> Config:
    """An Alembic config pinned to absolute paths so CWD cannot change the outcome."""
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "src/historiador/data/migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    return cfg


def _upgrade_head(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # env.py prefers $HISTORIADOR_DB_URL; point it at the temp file so an ambient
    # value in the developer's shell cannot make this test write to the real DB.
    monkeypatch.setenv("HISTORIADOR_DB_URL", f"sqlite+aiosqlite:///{db_path}")
    command.upgrade(_alembic_config(db_path), "head")


def _check_constraint_names(conn: sqlite3.Connection, table: str) -> set[str]:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if row is None or row[0] is None:
        return set()
    return set(re.findall(r'CONSTRAINT\s+"?([A-Za-z0-9_]+)"?\s+CHECK', row[0]))


def _snapshot(db_path: Path) -> dict[str, Any]:
    """Structural fingerprint of a SQLite file, for comparing two build routes."""
    conn = sqlite3.connect(db_path)
    try:
        tables = sorted(
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if r[0] not in {"alembic_version"} and not r[0].startswith("sqlite_")
        )
        snap: dict[str, Any] = {"tables": tables, "columns": {}, "fks": {}, "checks": {}}
        for table in tables:
            snap["columns"][table] = [
                (r[1], r[2].upper(), r[3], r[5])  # name, type, notnull, pk position
                for r in conn.execute(f"PRAGMA table_info('{table}')")
            ]
            snap["fks"][table] = sorted(
                (r[2], r[3], r[4], r[6])  # referenced table, from col, to col, on_delete
                for r in conn.execute(f"PRAGMA foreign_key_list('{table}')")
            )
            snap["checks"][table] = sorted(_check_constraint_names(conn, table))
        snap["indexes"] = sorted(
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
            if not r[0].startswith("sqlite_autoindex")
        )
        return snap
    finally:
        conn.close()


@pytest.fixture
def migrated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    db_path = tmp_path / "migrated.db"
    _upgrade_head(db_path, monkeypatch)
    yield db_path


# ── the legacy bug ──────────────────────────────────────────────────────────────


def test_topic_status_has_no_scoring_typo() -> None:
    """The legacy model defaulted Topic.status to "scoring" — a typo for "scoping".

    A bare string column could not catch it. A StrEnum can, and this test pins it.
    """
    values = {member.value for member in orm.TopicStatus}
    assert "scoping" in values
    assert "scoring" not in values
    assert orm.TopicStatus.SCOPING.value == "scoping"


def test_topic_status_column_default_is_scoping() -> None:
    default = orm.Topic.__table__.c.status.default
    assert default is not None
    assert default.arg is orm.TopicStatus.SCOPING


# ── metadata shape ──────────────────────────────────────────────────────────────


def test_all_contract_tables_exist() -> None:
    assert set(orm.Base.metadata.tables) == EXPECTED_TABLES


def test_events_primary_key_is_run_id_and_seq() -> None:
    """The composite PK is the ordering/gaplessness/idempotency contract of §4."""
    pk = [c.name for c in orm.Event.__table__.primary_key.columns]
    assert pk == ["run_id", "seq"]


def test_events_columns_match_the_fixed_contract() -> None:
    cols = {c.name: c for c in orm.Event.__table__.columns}
    assert set(cols) == {"run_id", "seq", "ts", "type", "node_id", "agent", "payload"}
    assert not cols["ts"].nullable
    assert not cols["type"].nullable
    assert cols["node_id"].nullable
    assert cols["agent"].nullable
    assert not cols["payload"].nullable


def test_run_cost_is_nullable_never_zero_defaulted() -> None:
    """Unknown cost must be NULL. A 0.0 default would render as "free" — a lie."""
    cost = orm.Run.__table__.c.cost_usd
    assert cost.nullable
    assert cost.default is None
    assert cost.server_default is None


def test_api_tokens_store_only_a_hash() -> None:
    cols = set(orm.ApiToken.__table__.columns.keys())
    assert "token_hash" in cols
    assert not {"token", "raw_token", "secret"} & cols


def test_run_node_primary_key_is_composite() -> None:
    pk = [c.name for c in orm.RunNode.__table__.primary_key.columns]
    assert pk == ["run_id", "node_id"]


# ── the built schema ────────────────────────────────────────────────────────────


def test_alembic_upgrade_head_builds_the_full_schema(migrated_db: Path) -> None:
    snap = _snapshot(migrated_db)
    assert set(snap["tables"]) == EXPECTED_TABLES

    conn = sqlite3.connect(migrated_db)
    try:
        version = conn.execute("SELECT version_num FROM alembic_version").fetchall()
    finally:
        conn.close()
    assert version == [("0001_initial",)]


def test_migration_seeds_config_and_a_default_profile(migrated_db: Path) -> None:
    conn = sqlite3.connect(migrated_db)
    try:
        config = dict(conn.execute("SELECT key, value FROM app_config"))
        profiles = conn.execute(
            "SELECT id, name, tone, preferred_length FROM profiles"
        ).fetchall()
    finally:
        conn.close()

    assert config == DEFAULT_APP_CONFIG
    assert profiles == [(DEFAULT_PROFILE_ID, "Default", "neutral", "medium")]
    # A seeded secret would be a secret in version control.
    assert not any("KEY" in key or "SECRET" in key for key in config)


def test_migration_matches_the_orm_models(migrated_db: Path, tmp_path: Path) -> None:
    """The hand-written migration and ``metadata.create_all`` must agree.

    This is what makes it safe for the migration to be a frozen copy of the DDL: any
    future model change that is not mirrored into a migration fails here.
    """
    from_models = tmp_path / "from_models.db"
    engine = create_engine(f"sqlite:///{from_models}")
    try:
        orm.Base.metadata.create_all(engine)
    finally:
        engine.dispose()

    assert _snapshot(migrated_db) == _snapshot(from_models)


def test_foreign_keys_declare_on_delete_behaviour(migrated_db: Path) -> None:
    """Every FK must say what happens on parent delete — the legacy schema said nothing."""
    conn = sqlite3.connect(migrated_db)
    try:
        found: dict[tuple[str, str], str] = {}
        for table in sorted(EXPECTED_TABLES):
            for row in conn.execute(f"PRAGMA foreign_key_list('{table}')"):
                found[(table, row[3])] = row[6]
    finally:
        conn.close()

    assert found == {
        ("events", "run_id"): "CASCADE",
        ("feedback_records", "history_id"): "CASCADE",
        ("feedback_records", "profile_id"): "CASCADE",
        ("histories", "profile_id"): "SET NULL",
        ("histories", "subtopic_id"): "SET NULL",
        ("histories", "topic_id"): "CASCADE",
        ("research_sources", "subtopic_id"): "CASCADE",
        ("run_nodes", "run_id"): "CASCADE",
        ("runs", "topic_id"): "SET NULL",
        ("scoping_messages", "topic_id"): "CASCADE",
        ("subtopics", "topic_id"): "CASCADE",
        ("topics", "profile_id"): "SET NULL",
    }
    assert "NO ACTION" not in set(found.values())


def test_status_columns_are_check_constrained(migrated_db: Path) -> None:
    """Free-form status strings are how "scoring" happened. Every one is now checked."""
    conn = sqlite3.connect(migrated_db)
    try:
        expected = {
            "topics": "topic_status",
            "subtopics": "subtopic_status",
            "histories": "history_status",
            "feedback_records": "feedback_type",
            "scoping_messages": "scoping_role",
            "runs": "run_status",
            "run_nodes": "run_node_state",
        }
        for table, constraint in expected.items():
            assert constraint in _check_constraint_names(conn, table), (table, constraint)
        assert "event_seq_positive" in _check_constraint_names(conn, "events")
        assert "api_token_hash_is_sha256" in _check_constraint_names(conn, "api_tokens")
    finally:
        conn.close()


def test_dashboard_indexes_exist(migrated_db: Path) -> None:
    snap = _snapshot(migrated_db)
    assert "ix_runs_status_created_at" in snap["indexes"]
    assert "ix_events_run_id_type_seq" in snap["indexes"]

    conn = sqlite3.connect(migrated_db)
    try:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='ix_runs_status_created_at'"
        ).fetchone()[0]
    finally:
        conn.close()
    # DESC must be part of the index, or the dashboard's newest-first list sorts.
    assert "DESC" in sql.upper()


def test_event_replay_scan_is_covered_by_the_primary_key(migrated_db: Path) -> None:
    """``WHERE run_id=? AND seq>?`` must be an index scan, not a table scan."""
    conn = sqlite3.connect(migrated_db)
    try:
        plan = conn.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT * FROM events WHERE run_id = 'r' AND seq > 5 ORDER BY seq"
        ).fetchall()
    finally:
        conn.close()
    detail = " ".join(str(row[-1]) for row in plan)
    assert "SCAN events" not in detail, detail
    assert "USING" in detail and "INDEX" in detail.upper(), detail


def test_downgrade_removes_every_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "roundtrip.db"
    _upgrade_head(db_path, monkeypatch)
    command.downgrade(_alembic_config(db_path), "base")

    conn = sqlite3.connect(db_path)
    try:
        remaining = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not r[0].startswith("sqlite_")
        }
    finally:
        conn.close()
    assert remaining == {"alembic_version"}
