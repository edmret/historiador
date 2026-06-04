"""Singleton service for reading/writing AppConfig from/to the database,
with .env fallback via ``backend.config.settings``.
"""

from __future__ import annotations

from typing import Any

import httpx

from backend.config import settings
from backend.database import async_session
from backend.models.app_config import AppConfig

# ---------------------------------------------------------------------------
# Agent type → model config key mapping
# ---------------------------------------------------------------------------
_AGENT_MODEL_KEYS: dict[str, str] = {
    "scoping": "scoping_model",
    "research": "research_model",
    "compiler": "compiler_model",
    "writer": "writer_model",
    "editor": "editor_model",
    "profile": "profile_model",
}


class AppConfigService:
    """Async service that manages the ``app_config`` key-value store.

    This is a singleton-style service with an in-memory cache.  Every public
    method creates its own async session so callers never need to pass one in.
    The cache (populated by :meth:`seed_defaults`) enables synchronous access
    for places where ``await`` isn't available (e.g. ``__init__``).

    **Lookup order (lower index wins):**
    1. Database / in-memory cache (``app_config`` table)
    2. :obj:`backend.config.settings` attribute (environment variable / .env)
    3. Hard-coded default in ``Settings`` class
    """

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}
        self._cache_loaded: bool = False

    # ------------------------------------------------------------------
    # Public API — async
    # ------------------------------------------------------------------

    async def get_config(self) -> dict[str, Any]:
        """Return *all* configuration as a flat dictionary.

        Database values override the matching key from ``settings``, which
        backs off to environment variables and ``.env`` defaults.
        """
        overrides = await self._load_all()
        merged = _settings_as_dict() | overrides
        return merged

    async def update_config(self, data: dict[str, Any]) -> dict[str, Any]:
        """Write one or more key-value pairs to the database.

        Returns the *full* merged config (DB + settings) *after* the write.
        """
        async with async_session() as session:
            for key, value in data.items():
                await session.merge(
                    AppConfig(key=str(key), value=str(value) if value is not None else None)
                )
            await session.commit()

        return await self.get_config()

    async def get_agent_config(self, agent_type: str) -> dict[str, str]:
        """Return ``{"base_url", "api_key", "model"}`` for *agent_type*.

        Accepts: ``scoping``, ``research``, ``compiler``, ``writer``,
        ``editor``, ``profile``.

        The model value is looked up with the agent-specific key (e.g.
        ``scoping_model``) and falls back to the global ``llm_model``.
        """
        agent_type = agent_type.lower()
        model_key = _AGENT_MODEL_KEYS.get(agent_type)
        if model_key is None:
            raise ValueError(
                f"Unknown agent type {agent_type!r}. "
                f"Expected one of: {', '.join(_AGENT_MODEL_KEYS)}"
            )

        config = await self.get_config()

        return {
            "base_url": config.get("llm_base_url", settings.llm_base_url),
            "api_key": config.get("llm_api_key", settings.llm_api_key),
            "model": config.get(model_key, config.get("llm_model", settings.llm_model)),
        }

    async def test_llm_connection(
        self,
        base_url: str,
        api_key: str,
        model: str,
    ) -> tuple[bool, str]:
        """Test an LLM provider connection with ``httpx``.

        Sends a minimal chat-completion request and returns
        ``(success, message)``.
        """
        url = base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with only the word OK."}],
            "max_tokens": 10,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                if not content:
                    return False, "Empty response from LLM"
                return True, content.strip()
        except httpx.TimeoutException:
            return False, "Request timed out after 15 seconds"
        except httpx.HTTPStatusError as exc:
            return False, f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        except Exception as exc:
            return False, str(exc)

    async def seed_defaults(self) -> None:
        """Seed all default values from ``settings`` into the database.

        Only writes keys that do **not** already exist in the DB, so the
        operation is idempotent across restarts.  Also populates the
        in-memory cache so synchronous accessors work immediately.
        """
        from sqlalchemy import select

        async with async_session() as session:
            result = await session.execute(select(AppConfig.key))
            existing_keys: set[str] = set(result.scalars().all())

            defaults = _settings_as_dict()
            for key, value in defaults.items():
                if key not in existing_keys and value is not None:
                    session.add(AppConfig(key=key, value=str(value)))

            await session.commit()

        # Reload cache after seeding
        self._cache = await self._load_all()
        self._cache_loaded = True

    # ------------------------------------------------------------------
    # Public API — synchronous (backed by in-memory cache)
    # ------------------------------------------------------------------

    def get_all_sync(self) -> dict[str, Any]:
        """Synchronous version of :meth:`get_config` using the in-memory cache.

        If the cache hasn't been loaded yet (e.g. before startup seed),
        falls back to ``settings`` only.
        """
        if self._cache_loaded:
            return _settings_as_dict() | self._cache
        return _settings_as_dict()

    def get_agent_config_sync(self, agent_type: str) -> dict[str, str]:
        """Synchronous version of :meth:`get_agent_config`.

        Raises ``ValueError`` for unknown agent types.
        """
        agent_type = agent_type.lower()
        model_key = _AGENT_MODEL_KEYS.get(agent_type)
        if model_key is None:
            raise ValueError(
                f"Unknown agent type {agent_type!r}. "
                f"Expected one of: {', '.join(_AGENT_MODEL_KEYS)}"
            )

        config = self.get_all_sync()
        return {
            "base_url": config.get("llm_base_url", settings.llm_base_url),
            "api_key": config.get("llm_api_key", settings.llm_api_key),
            "model": config.get(model_key, config.get("llm_model", settings.llm_model)),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _load_all(self) -> dict[str, str]:
        """Return all DB rows as a plain ``{key: value}`` dict."""
        from sqlalchemy import select

        async with async_session() as session:
            result = await session.execute(select(AppConfig))
            rows = result.scalars().all()
            return {row.key: row.value for row in rows if row.value is not None}


# ---------------------------------------------------------------------------
# Module-level singleton (lazily instantiated — FastAPI dependency style)
# ---------------------------------------------------------------------------
_service: AppConfigService | None = None


def get_app_config_service() -> AppConfigService:
    """Return the module-level :class:`AppConfigService` singleton."""
    global _service
    if _service is None:
        _service = AppConfigService()
    return _service


# ---------------------------------------------------------------------------
# Helper: turn pydantic-settings fields into a flat dict
# ---------------------------------------------------------------------------
def _settings_as_dict() -> dict[str, Any]:
    """Return a flat dictionary of every field in the ``settings`` singleton.

    Private / internal fields are excluded so we don't accidentally persist
    metadata into the DB.
    """
    return {
        k: getattr(settings, k)
        for k in settings.model_fields
        if not k.startswith("_") and not k.startswith("model_")
    }
