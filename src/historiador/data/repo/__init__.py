"""Repositories — the only sanctioned way in or out of the database.

Contract for every class here: **no ORM object escapes**. Methods accept and return
Pydantic models, so a router, a service, or an MCP tool can never accidentally hold a
live ``Session``-bound instance, trigger a lazy load after the session closed, or
serialize a detached object. That is the single rule that keeps the data layer
swappable and the service layer honest (ARCHITECTURE.md §6).

Three small repositories live directly in this module — :class:`AppConfigRepo`,
:class:`ApiTokenRepo` and :class:`PushSubscriptionRepo`. Their tables
(``app_config``, ``api_tokens``, ``push_subscriptions``) are singleton/keyed
application state rather than product aggregates, and the data-layer file allocation
gave them no module of their own. They are kept here, small and dependency-free,
rather than being bolted onto an unrelated aggregate's repository where nobody would
find them.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from typing import Any, cast

from pydantic import BaseModel, ConfigDict
from sqlalchemy import CursorResult, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from historiador.data import models as orm
from historiador.data.repo.event_repo import DEFAULT_REPLAY_LIMIT, EventRecord, EventRepo
from historiador.data.repo.feedback_repo import Feedback, FeedbackRepo
from historiador.data.repo.history_repo import History, HistoryRepo, HistorySummary
from historiador.data.repo.profile_repo import DEFAULT_PROFILE_NAME, Profile, ProfileRepo
from historiador.data.repo.run_repo import RunNodeRecord, RunRecord, RunRepo, Usage
from historiador.data.repo.topic_repo import (
    ResearchSource,
    ScopingMessage,
    Subtopic,
    Topic,
    TopicRepo,
)
from historiador.data.session import Clock, SystemClock, now_datetime

API_TOKEN_PREFIX = "ht_"


def hash_token(raw_token: str) -> str:
    """SHA-256 hex digest of a raw API token.

    Module-level (not a method) so the auth layer can hash an incoming
    ``x-api-key`` header for lookup without instantiating a repository or touching
    the database.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_token() -> str:
    """Mint a raw API token. 256 bits of entropy from :mod:`secrets`, never :mod:`random`."""
    return API_TOKEN_PREFIX + secrets.token_hex(32)


# ── app_config ──────────────────────────────────────────────────────────────────


class ConfigEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    value: str | None
    updated_at: datetime


class AppConfigRepo:
    """Key/value application settings."""

    def __init__(self, session: AsyncSession, *, clock: Clock | None = None) -> None:
        self._session = session
        self._clock: Clock = clock if clock is not None else SystemClock()

    async def get(self, key: str) -> str | None:
        row = await self._session.get(orm.AppConfig, key)
        return None if row is None else row.value

    async def all_values(self) -> dict[str, str | None]:
        """Whole config as a plain dict — what ``GET /api/config`` renders (masked upstream)."""
        stmt = select(orm.AppConfig).order_by(orm.AppConfig.key.asc())
        rows = (await self._session.execute(stmt)).scalars().all()
        return {row.key: row.value for row in rows}

    async def set_many(self, values: dict[str, str | None]) -> int:
        """Upsert several keys in one statement.

        Upsert rather than select-then-insert: config writes come from a settings
        panel that submits the whole form, and the caller should not have to know
        which keys already exist.
        """
        if not values:
            return 0
        now = now_datetime(self._clock)
        stmt = sqlite_insert(orm.AppConfig).values(
            [{"key": k, "value": v, "updated_at": now} for k, v in values.items()]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["key"],
            set_={"value": stmt.excluded.value, "updated_at": stmt.excluded.updated_at},
        )
        result = cast("CursorResult[Any]", await self._session.execute(stmt))
        return int(result.rowcount)

    async def delete(self, key: str) -> bool:
        row = await self._session.get(orm.AppConfig, key)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True


# ── api_tokens ──────────────────────────────────────────────────────────────────


class ApiTokenRecord(BaseModel):
    """An API token *without* the secret.

    There is deliberately no field that could hold the raw token: the only moment it
    exists is the return value of :meth:`ApiTokenRepo.create`.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    user_id: str
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    is_active: bool


def _to_token(row: orm.ApiToken) -> ApiTokenRecord:
    return ApiTokenRecord(
        id=row.id,
        label=row.label,
        user_id=row.user_id,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        is_active=row.is_active,
    )


class ApiTokenRepo:
    """Hashed bearer tokens for headless / MCP access."""

    def __init__(self, session: AsyncSession, *, clock: Clock | None = None) -> None:
        self._session = session
        self._clock: Clock = clock if clock is not None else SystemClock()

    async def create(
        self, *, label: str, user_id: str, expires_at: datetime | None = None
    ) -> tuple[str, ApiTokenRecord]:
        """Mint a token. Returns ``(raw_token, record)``.

        The raw token is returned once and never persisted — only its SHA-256 digest
        reaches the database. A dump of ``api_tokens`` therefore contains no usable
        credential.
        """
        raw = generate_token()
        row = orm.ApiToken(
            id=orm.new_id(),
            token_hash=hash_token(raw),
            label=label,
            user_id=user_id,
            created_at=now_datetime(self._clock),
            last_used_at=None,
            expires_at=expires_at,
            is_active=True,
        )
        self._session.add(row)
        await self._session.flush()
        return raw, _to_token(row)

    async def find_active_by_raw(self, raw_token: str) -> ApiTokenRecord | None:
        """Authenticate a presented token.

        Looks up by digest, then rejects inactive and expired tokens in Python so the
        caller gets one unambiguous ``None`` for every "not a valid credential" case.
        """
        stmt = select(orm.ApiToken).where(orm.ApiToken.token_hash == hash_token(raw_token))
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None or not row.is_active:
            return None
        if row.expires_at is not None and row.expires_at <= now_datetime(self._clock):
            return None
        return _to_token(row)

    async def touch(self, token_id: str) -> None:
        """Record last use. Best-effort telemetry for the token list UI."""
        row = await self._session.get(orm.ApiToken, token_id)
        if row is not None:
            row.last_used_at = now_datetime(self._clock)
            await self._session.flush()

    async def list_for_user(self, user_id: str) -> list[ApiTokenRecord]:
        stmt = (
            select(orm.ApiToken)
            .where(orm.ApiToken.user_id == user_id)
            .order_by(orm.ApiToken.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_token(row) for row in rows]

    async def revoke(self, token_id: str) -> bool:
        """Deactivate rather than delete, so an audit of past access survives revocation."""
        row = await self._session.get(orm.ApiToken, token_id)
        if row is None:
            return False
        row.is_active = False
        await self._session.flush()
        return True


# ── push_subscriptions ──────────────────────────────────────────────────────────


class PushSubscription(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    endpoint: str
    p256dh: str
    auth: str
    created_at: datetime


class PushSubscriptionRepo:
    """Web Push endpoints registered by browsers."""

    def __init__(self, session: AsyncSession, *, clock: Clock | None = None) -> None:
        self._session = session
        self._clock: Clock = clock if clock is not None else SystemClock()

    async def upsert(self, *, endpoint: str, p256dh: str, auth: str) -> PushSubscription:
        """Register or refresh a subscription.

        Browsers re-send the same endpoint on every page load and rotate their keys
        periodically, so this must be idempotent on ``endpoint`` or the table grows
        without bound and every notification is delivered N times.
        """
        stmt = select(orm.PushSubscription).where(orm.PushSubscription.endpoint == endpoint)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            row = orm.PushSubscription(
                id=orm.new_id(),
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                created_at=now_datetime(self._clock),
            )
            self._session.add(row)
        else:
            row.p256dh = p256dh
            row.auth = auth
        await self._session.flush()
        return PushSubscription(
            id=row.id,
            endpoint=row.endpoint,
            p256dh=row.p256dh,
            auth=row.auth,
            created_at=row.created_at,
        )

    async def list_all(self) -> list[PushSubscription]:
        stmt = select(orm.PushSubscription).order_by(orm.PushSubscription.created_at.asc())
        rows = (await self._session.execute(stmt)).scalars().all()
        return [
            PushSubscription(
                id=row.id,
                endpoint=row.endpoint,
                p256dh=row.p256dh,
                auth=row.auth,
                created_at=row.created_at,
            )
            for row in rows
        ]

    async def delete_by_endpoint(self, endpoint: str) -> bool:
        """Drop a subscription the push service reported as gone (404/410)."""
        stmt = select(orm.PushSubscription).where(orm.PushSubscription.endpoint == endpoint)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True


__all__ = [
    "API_TOKEN_PREFIX",
    "DEFAULT_PROFILE_NAME",
    "DEFAULT_REPLAY_LIMIT",
    "ApiTokenRecord",
    "ApiTokenRepo",
    "AppConfigRepo",
    "ConfigEntry",
    "EventRecord",
    "EventRepo",
    "Feedback",
    "FeedbackRepo",
    "History",
    "HistoryRepo",
    "HistorySummary",
    "Profile",
    "ProfileRepo",
    "PushSubscription",
    "PushSubscriptionRepo",
    "ResearchSource",
    "RunNodeRecord",
    "RunRecord",
    "RunRepo",
    "ScopingMessage",
    "Subtopic",
    "Topic",
    "TopicRepo",
    "Usage",
    "generate_token",
    "hash_token",
]
