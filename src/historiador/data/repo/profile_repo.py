"""Writing profiles — tone/audience/length settings the writer agent is bound to."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from historiador.data import models as orm
from historiador.data.session import Clock, SystemClock, now_datetime

DEFAULT_PROFILE_NAME = "Default"


class Profile(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    description: str | None = None
    tone: orm.Tone
    audience: str
    preferred_length: orm.PreferredLength
    style_notes: str | None = None
    # Profile-agent Q&A; schema owned by the domain layer, opaque here.
    creation_feedback: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


def _to_profile(row: orm.Profile) -> Profile:
    return Profile(
        id=row.id,
        name=row.name,
        description=row.description,
        tone=row.tone,
        audience=row.audience,
        preferred_length=row.preferred_length,
        style_notes=row.style_notes,
        creation_feedback=row.creation_feedback,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class ProfileRepo:
    """Repository for the ``profiles`` aggregate."""

    def __init__(self, session: AsyncSession, *, clock: Clock | None = None) -> None:
        self._session = session
        self._clock: Clock = clock if clock is not None else SystemClock()

    async def create(
        self,
        *,
        name: str,
        description: str | None = None,
        tone: orm.Tone = orm.Tone.NEUTRAL,
        audience: str = "general",
        preferred_length: orm.PreferredLength = orm.PreferredLength.MEDIUM,
        style_notes: str | None = None,
        creation_feedback: dict[str, Any] | None = None,
        profile_id: str | None = None,
    ) -> Profile:
        """Create a profile. ``name`` is unique — a duplicate raises ``IntegrityError``
        rather than silently producing two profiles the UI cannot tell apart."""
        now = now_datetime(self._clock)
        row = orm.Profile(
            id=profile_id if profile_id is not None else orm.new_id(),
            name=name,
            description=description,
            tone=tone,
            audience=audience,
            preferred_length=preferred_length,
            style_notes=style_notes,
            creation_feedback=creation_feedback,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return _to_profile(row)

    async def get(self, profile_id: str) -> Profile | None:
        row = await self._session.get(orm.Profile, profile_id)
        return None if row is None else _to_profile(row)

    async def get_by_name(self, name: str) -> Profile | None:
        stmt = select(orm.Profile).where(orm.Profile.name == name)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _to_profile(row)

    async def list_profiles(self) -> list[Profile]:
        stmt = select(orm.Profile).order_by(orm.Profile.name.asc())
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_profile(row) for row in rows]

    async def update(
        self,
        profile_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        tone: orm.Tone | None = None,
        audience: str | None = None,
        preferred_length: orm.PreferredLength | None = None,
        style_notes: str | None = None,
        creation_feedback: dict[str, Any] | None = None,
    ) -> Profile | None:
        """Partial update.

        ``None`` means "leave unchanged", not "set to NULL". Clearing a nullable field
        is a separate, explicit operation precisely because conflating the two is how
        PATCH endpoints silently erase user data.
        """
        row = await self._session.get(orm.Profile, profile_id)
        if row is None:
            return None
        if name is not None:
            row.name = name
        if description is not None:
            row.description = description
        if tone is not None:
            row.tone = tone
        if audience is not None:
            row.audience = audience
        if preferred_length is not None:
            row.preferred_length = preferred_length
        if style_notes is not None:
            row.style_notes = style_notes
        if creation_feedback is not None:
            row.creation_feedback = creation_feedback
        row.updated_at = now_datetime(self._clock)
        await self._session.flush()
        return _to_profile(row)

    async def delete(self, profile_id: str) -> bool:
        """Delete a profile.

        Topics and histories referencing it keep their rows and have ``profile_id``
        set to NULL by the database (``ON DELETE SET NULL``); losing a style preference
        must never lose a generated history.
        """
        row = await self._session.get(orm.Profile, profile_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True


__all__ = ["DEFAULT_PROFILE_NAME", "Profile", "ProfileRepo"]
