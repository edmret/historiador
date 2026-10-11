"""Initial Historiador schema.

Creates the product tables (topics, subtopics, histories, profiles, feedback,
scoping messages, research sources, push subscriptions, app config, API tokens) and
the observability tables (runs, run_nodes, events), then seeds the rows the
application cannot boot sensibly without: default app configuration and one writing
profile.

The DDL is written out explicitly rather than calling ``metadata.create_all`` so that
this revision is a *frozen* description of the schema at this point in history. A
migration that reads the current models would silently change meaning every time the
models change, which defeats the purpose of having migrations at all.
``tests/unit/test_models.py::test_migration_matches_models`` asserts the two agree
today, so the freeze cannot drift unnoticed.

Revision ID: 0001_initial
Revises:
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# A stable id for the seeded profile so later migrations, fixtures and the UI can all
# refer to it without a lookup-by-name that a rename would break.
DEFAULT_PROFILE_ID = "00000000-0000-4000-8000-000000000001"
DEFAULT_PROFILE_NAME = "Default"

# Only non-secret defaults are seeded. API keys and VAPID material are deliberately
# absent: a secret that ships in a migration is a secret in version control.
DEFAULT_APP_CONFIG: dict[str, str] = {
    "LLM_BASE_URL": "https://api.nan.builders/v1",
    "LLM_MODEL": "deepseek-v4-flash",
    "SEARCH_PROVIDER": "duckduckgo",
    "DEFAULT_NUM_HISTORIES": "2",
    "DEFAULT_NUM_RESEARCH_AGENTS": "3",
    "MAX_QUERIES_PER_AGENT": "3",
    "MAX_PAGES_PER_QUERY": "3",
    "MAX_CHARS_PER_PAGE": "10000",
    "RESEARCH_TIMEOUT_SECONDS": "60",
    "MAX_SCOPING_ROUNDS": "5",
    "MAX_RUN_CONCURRENCY": "4",
}


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "length(token_hash) = 64", name=op.f("ck_api_tokens_api_token_hash_is_sha256")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_api_tokens_token_hash")),
    )
    op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"], unique=False)

    op.create_table(
        "app_config",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_app_config")),
    )

    op.create_table(
        "profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "tone",
            sa.Enum(
                "dramatic",
                "educational",
                "humorous",
                "epic",
                "neutral",
                name="profile_tone",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("audience", sa.String(length=128), nullable=False),
        sa.Column(
            "preferred_length",
            sa.Enum(
                "short",
                "medium",
                "long",
                name="profile_length",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("style_notes", sa.Text(), nullable=True),
        sa.Column("creation_feedback", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profiles")),
        sa.UniqueConstraint("name", name=op.f("uq_profiles_name")),
    )

    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("endpoint", sa.String(length=2048), nullable=False),
        sa.Column("p256dh", sa.String(length=256), nullable=False),
        sa.Column("auth", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_push_subscriptions")),
        sa.UniqueConstraint("endpoint", name=op.f("uq_push_subscriptions_endpoint")),
    )

    op.create_table(
        "topics",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "scoping",
                "scoping_complete",
                "researching",
                "compiling",
                "writing",
                "histories_created",
                "failed",
                name="topic_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("profile_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            name=op.f("fk_topics_profile_id_profiles"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_topics")),
    )
    op.create_index(
        "ix_topics_status_created_at",
        "topics",
        ["status", sa.text("created_at DESC")],
        unique=False,
    )

    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("topic_id", sa.String(length=36), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "succeeded",
                "failed",
                "cancelled",
                name="run_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("started_at", sa.Float(), nullable=True),
        sa.Column("ended_at", sa.Float(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("graph", sa.JSON(), nullable=False),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.CheckConstraint(
            "cached_tokens >= 0", name=op.f("ck_runs_run_cached_tokens_non_negative")
        ),
        sa.CheckConstraint(
            "completion_tokens >= 0", name=op.f("ck_runs_run_completion_tokens_non_negative")
        ),
        sa.CheckConstraint(
            "cost_usd IS NULL OR cost_usd >= 0", name=op.f("ck_runs_run_cost_non_negative")
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR started_at IS NOT NULL",
            name=op.f("ck_runs_run_ended_implies_started"),
        ),
        sa.CheckConstraint(
            "prompt_tokens >= 0", name=op.f("ck_runs_run_prompt_tokens_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"], ["topics.id"], name=op.f("fk_runs_topic_id_topics"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
    )
    op.create_index("ix_runs_topic_id", "runs", ["topic_id"], unique=False)
    # The dashboard's run list: newest first, optionally filtered by status. DESC is
    # part of the index so the common query needs no sort step.
    op.create_index(
        "ix_runs_status_created_at",
        "runs",
        ["status", sa.text("created_at DESC")],
        unique=False,
    )

    op.create_table(
        "scoping_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("topic_id", sa.String(length=36), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "agent",
                "user",
                name="scoping_role",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["topics.id"],
            name=op.f("fk_scoping_messages_topic_id_topics"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scoping_messages")),
    )
    op.create_index(
        "ix_scoping_messages_topic_id_created_at",
        "scoping_messages",
        ["topic_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "subtopics",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("topic_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "todo",
                "selected",
                "researching",
                "researched",
                "done",
                name="subtopic_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("todo_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "todo_order >= 0", name=op.f("ck_subtopics_subtopic_order_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["topics.id"],
            name=op.f("fk_subtopics_topic_id_topics"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subtopics")),
    )
    op.create_index(
        "ix_subtopics_topic_id_todo_order", "subtopics", ["topic_id", "todo_order"], unique=False
    )

    op.create_table(
        "events",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("seq", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("ts", sa.Float(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=True),
        sa.Column("agent", sa.String(length=64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.CheckConstraint("seq >= 1", name=op.f("ck_events_event_seq_positive")),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_events_run_id_runs"), ondelete="CASCADE"
        ),
        # Ordering + gaplessness + idempotent append, in one constraint.
        sa.PrimaryKeyConstraint("run_id", "seq", name=op.f("pk_events")),
    )
    op.create_index("ix_events_run_id_type_seq", "events", ["run_id", "type", "seq"], unique=False)

    op.create_table(
        "histories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("topic_id", sa.String(length=36), nullable=False),
        sa.Column("subtopic_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "in_review",
                "refining",
                "accepted",
                "rejected",
                name="history_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("profile_id", sa.String(length=36), nullable=True),
        sa.Column("feedback_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "feedback_count >= 0", name=op.f("ck_histories_history_feedback_count_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            name=op.f("fk_histories_profile_id_profiles"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["subtopic_id"],
            ["subtopics.id"],
            name=op.f("fk_histories_subtopic_id_subtopics"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["topics.id"],
            name=op.f("fk_histories_topic_id_topics"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_histories")),
    )
    op.create_index("ix_histories_topic_id", "histories", ["topic_id"], unique=False)
    op.create_index(
        "ix_histories_status_created_at",
        "histories",
        ["status", sa.text("created_at DESC")],
        unique=False,
    )

    op.create_table(
        "research_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subtopic_id", sa.String(length=36), nullable=False),
        sa.Column("agent_name", sa.String(length=64), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("content_snippet", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["subtopic_id"],
            ["subtopics.id"],
            name=op.f("fk_research_sources_subtopic_id_subtopics"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_sources")),
        sa.UniqueConstraint("subtopic_id", "url", name="uq_research_sources_subtopic_id_url"),
    )

    op.create_table(
        "run_nodes",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("agent", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=256), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "blocked",
                "ready",
                "running",
                "retrying",
                "succeeded",
                "failed",
                "cancelled",
                "skipped",
                name="run_node_state",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("activity", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Float(), nullable=True),
        sa.Column("ended_at", sa.Float(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.CheckConstraint("attempt >= 0", name=op.f("ck_run_nodes_run_node_attempt_non_negative")),
        sa.CheckConstraint(
            "cached_tokens >= 0", name=op.f("ck_run_nodes_run_node_cached_tokens_non_negative")
        ),
        sa.CheckConstraint(
            "completion_tokens >= 0",
            name=op.f("ck_run_nodes_run_node_completion_tokens_non_negative"),
        ),
        sa.CheckConstraint(
            "cost_usd IS NULL OR cost_usd >= 0",
            name=op.f("ck_run_nodes_run_node_cost_non_negative"),
        ),
        sa.CheckConstraint(
            "prompt_tokens >= 0", name=op.f("ck_run_nodes_run_node_prompt_tokens_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_run_nodes_run_id_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("run_id", "node_id", name=op.f("pk_run_nodes")),
    )
    op.create_index("ix_run_nodes_run_id_state", "run_nodes", ["run_id", "state"], unique=False)

    op.create_table(
        "feedback_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("history_id", sa.String(length=36), nullable=True),
        sa.Column("profile_id", sa.String(length=36), nullable=True),
        sa.Column(
            "feedback_type",
            sa.Enum(
                "accept",
                "reject",
                "refine_request",
                name="feedback_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("feedback_text", sa.Text(), nullable=True),
        sa.Column("applied", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "history_id IS NOT NULL OR profile_id IS NOT NULL",
            name=op.f("ck_feedback_records_feedback_has_target"),
        ),
        sa.ForeignKeyConstraint(
            ["history_id"],
            ["histories.id"],
            name=op.f("fk_feedback_records_history_id_histories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            name=op.f("fk_feedback_records_profile_id_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback_records")),
    )
    op.create_index(
        "ix_feedback_records_history_id", "feedback_records", ["history_id"], unique=False
    )
    op.create_index(
        "ix_feedback_records_profile_id", "feedback_records", ["profile_id"], unique=False
    )

    _seed()


def _seed() -> None:
    """Insert the rows a fresh install needs to be usable at all.

    Without a writing profile the writer agent has no tone/length to honour, and
    without base config the settings panel opens empty and the first run fails on a
    missing model name. Seeding here — rather than at daemon startup — means the
    invariant is created exactly once, transactionally, alongside the tables.
    """
    now = datetime.now(tz=UTC)

    app_config = sa.table(
        "app_config",
        sa.column("key", sa.String),
        sa.column("value", sa.Text),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        app_config,
        [{"key": k, "value": v, "updated_at": now} for k, v in DEFAULT_APP_CONFIG.items()],
    )

    profiles = sa.table(
        "profiles",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("tone", sa.String),
        sa.column("audience", sa.String),
        sa.column("preferred_length", sa.String),
        sa.column("style_notes", sa.Text),
        sa.column("creation_feedback", sa.JSON),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        profiles,
        [
            {
                "id": DEFAULT_PROFILE_ID,
                "name": DEFAULT_PROFILE_NAME,
                "description": "Balanced narrative history for a general audience.",
                "tone": "neutral",
                "audience": "general",
                "preferred_length": "medium",
                "style_notes": None,
                "creation_feedback": None,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_feedback_records_profile_id", table_name="feedback_records")
    op.drop_index("ix_feedback_records_history_id", table_name="feedback_records")
    op.drop_table("feedback_records")
    op.drop_index("ix_run_nodes_run_id_state", table_name="run_nodes")
    op.drop_table("run_nodes")
    op.drop_table("research_sources")
    op.drop_index("ix_histories_status_created_at", table_name="histories")
    op.drop_index("ix_histories_topic_id", table_name="histories")
    op.drop_table("histories")
    op.drop_index("ix_events_run_id_type_seq", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_subtopics_topic_id_todo_order", table_name="subtopics")
    op.drop_table("subtopics")
    op.drop_index("ix_scoping_messages_topic_id_created_at", table_name="scoping_messages")
    op.drop_table("scoping_messages")
    op.drop_index("ix_runs_status_created_at", table_name="runs")
    op.drop_index("ix_runs_topic_id", table_name="runs")
    op.drop_table("runs")
    op.drop_index("ix_topics_status_created_at", table_name="topics")
    op.drop_table("topics")
    op.drop_table("push_subscriptions")
    op.drop_table("profiles")
    op.drop_table("app_config")
    op.drop_index("ix_api_tokens_user_id", table_name="api_tokens")
    op.drop_table("api_tokens")
