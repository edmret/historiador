"""Layered application settings.

Precedence, highest first:

    process env  >  DB overlay (`app_config` rows)  >  .env file  >  code defaults

The DB overlay sits *below* the process environment on purpose: the Settings tab
is a convenience, but an operator who exports `LLM_API_KEY=...` before starting
the daemon must win over whatever a stale row says, otherwise a compromised or
simply wrong database row would be unoverridable from the shell.

Two rules keep this module honest:

* **No data-layer import.** `config.py` never imports `historiador.data`; the
  overlay arrives as an injected `ConfigOverlay`. The data layer needs settings
  (a database URL) to open a session at all, so importing it here would be a
  bootstrap cycle — and it would make settings untestable without a database.
* **Secrets are `SecretStr`, always.** The type is the enforcement: a stray
  f-string of a `SecretStr` renders `**********`, so the failure mode of
  forgetting to redact is a useless log line rather than a leaked key.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from functools import lru_cache
from typing import Any, Final, Literal, Protocol, Self, runtime_checkable

from pydantic import SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from historiador.core.errors import ConfigError

__all__ = [
    "AGENT_MODEL_KEYS",
    "ConfigOverlay",
    "SearchProvider",
    "Settings",
    "get_settings",
    "load_settings",
    "reset_settings_cache",
]

SearchProvider = Literal["duckduckgo", "direct", "hermes", "tavily", "serpapi", "mock"]

#: Routing keys accepted by `Settings.agent_model` (`AgentSpec.model_key`, §3.1/§5).
AGENT_MODEL_KEYS: Final[tuple[str, ...]] = (
    "storyteller",
    "scoping",
    "research",
    "compiler",
    "writer",
    "editor",
    "profile",
)


@runtime_checkable
class ConfigOverlay(Protocol):
    """Supplies configuration overrides from outside the process environment.

    Implemented by the data layer over the `app_config` table and injected, so
    this module stays free of DB imports. The method is synchronous and returns
    an already-materialized snapshot: the caller (which owns the async session)
    does the awaiting, and settings resolution stays a pure, testable function.

    **Contract:** return only keys that are *actually set*. An `app_config` row
    that exists but holds NULL/empty must be omitted, not returned as `""` —
    returning it would let an unset row silently blank out an env var, which is
    the classic "I set LLM_API_KEY and the app still says no key" bug.
    """

    def overrides(self) -> Mapping[str, object]:
        """The keys this overlay wants to override, and their values."""
        ...


class Settings(BaseSettings):
    """Every knob in the system, in one validated, typed object.

    Values are kept to JSON primitives (paths are `str`, not `Path`) because
    `redacted()` is serialized straight into the config API response and into
    log/event payloads.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Unknown env vars are the norm (PATH, HOME, CI, …) — refusing to boot
        # over them would be absurd.
        extra="ignore",
    )

    # ── LLM ───────────────────────────────────────────────────────────────
    llm_base_url: str = "https://api.nan.builders/v1"
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = "deepseek-v4-flash"
    llm_timeout_s: float = 120.0
    llm_max_retries: int = 3
    llm_temperature: float = 0.7
    #: LLM_TOKEN coalescing window (§4.2): flush on whichever fires first.
    llm_token_flush_ms: int = 50
    llm_token_flush_chars: int = 256

    # ── Per-agent model overrides ─────────────────────────────────────────
    # Empty string means "inherit `llm_model`". It is never a model name; see
    # `agent_model()`.
    storyteller_model: str = ""
    scoping_model: str = ""
    research_model: str = ""
    compiler_model: str = ""
    writer_model: str = ""
    editor_model: str = ""
    profile_model: str = ""

    # ── Search & crawl ────────────────────────────────────────────────────
    search_provider: SearchProvider = "duckduckgo"
    tavily_api_key: SecretStr = SecretStr("")
    serpapi_api_key: SecretStr = SecretStr("")
    hermes_path: str = "hermes"
    crawl_user_agent: str = "Historiador/1.0 (+historiador.app)"
    crawl_timeout_s: float = 20.0
    max_queries_per_agent: int = 3
    max_pages_per_query: int = 3
    max_chars_per_page: int = 10_000

    # ── Pipeline / runtime ────────────────────────────────────────────────
    default_num_histories: int = 2
    default_num_research_agents: int = 3
    research_timeout_seconds: float = 60.0
    max_scoping_rounds: int = 5
    run_max_concurrency: int = 4
    node_timeout_s: float = 120.0
    node_max_attempts: int = 3
    retry_backoff_base_s: float = 0.5
    retry_backoff_max_s: float = 30.0
    retry_jitter: float = 0.25

    # ── Data ──────────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./historiador.db"
    db_echo: bool = False
    sqlite_busy_timeout_ms: int = 5_000
    #: Per-subscriber bound on the event bus; a slower subscriber is dropped
    #: from the live feed and replays from `since_seq` (§4.3).
    event_queue_size: int = 512
    event_retention_days: int = 30

    # ── Server ────────────────────────────────────────────────────────────
    # Named `server_*` rather than `host`/`port` so an ambient PORT belonging to
    # some other process manager cannot silently move our listener.
    server_host: str = "0.0.0.0"
    server_port: int = 8080
    cors_origins: str = "*"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = True
    ws_heartbeat_s: float = 20.0
    ws_idle_timeout_s: float = 60.0

    # ── Auth (Stytch) ─────────────────────────────────────────────────────
    stytch_project_id: str = ""
    stytch_secret: SecretStr = SecretStr("")
    #: Public by design (it ships to the browser), so deliberately not a secret.
    stytch_public_token: str = ""
    stytch_environment: Literal["test", "live"] = "test"
    api_token_prefix: str = "ht_"

    # ── Web push ──────────────────────────────────────────────────────────
    vapid_public_key: str = ""
    vapid_private_key: SecretStr = SecretStr("")
    vapid_claim_email: str = "admin@historiador.app"

    # ── MCP ───────────────────────────────────────────────────────────────
    mcp_enabled: bool = True
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8081

    # ── Daemon ────────────────────────────────────────────────────────────
    daemon_pid_file: str = ".historiador/daemon.pid"
    daemon_shutdown_grace_s: float = 30.0
    prompts_dir: str = "src/historiador/domain/prompts"
    watch_enabled: bool = True

    # ── Derived views ─────────────────────────────────────────────────────

    @property
    def cors_origin_list(self) -> list[str]:
        """`CORS_ORIGINS` is a plain comma-separated string, not JSON.

        pydantic-settings parses list-typed fields as JSON, which would reject
        the documented `CORS_ORIGINS=*` outright. Keeping the field a `str` and
        splitting here means the documented format keeps working.
        """
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def stytch_configured(self) -> bool:
        """Whether auth can actually run, rather than a separate enable flag.

        One source of truth: credentials present means auth is on. A boolean
        that can disagree with the credentials is a way to accidentally ship an
        unauthenticated server.
        """
        return bool(self.stytch_project_id and self.stytch_secret.get_secret_value())

    def agent_model(self, key: str) -> str:
        """Resolve an agent routing key to a concrete model name.

        An empty (or whitespace-only) override means **inherit** `llm_model` —
        it is never a model name. The UI's per-agent dropdown submits `""` for
        "use default", and treating that as a real model would send the literal
        empty string to the provider and fail every call for that agent.

        An unknown key also inherits: adding an agent to `domain/` should not
        require a config migration before it can run, and the worst case of a
        typo'd key is the default model rather than a crash mid-run.
        """
        override = self._agent_model_overrides().get(key, "")
        return override.strip() or self.llm_model

    def _agent_model_overrides(self) -> dict[str, str]:
        # Explicit mapping rather than `getattr(self, f"{key}_model")`: it keeps
        # the routing surface typed and closed, so an arbitrary key cannot reach
        # an unrelated attribute.
        return {
            "storyteller": self.storyteller_model,
            "scoping": self.scoping_model,
            "research": self.research_model,
            "compiler": self.compiler_model,
            "writer": self.writer_model,
            "editor": self.editor_model,
            "profile": self.profile_model,
        }

    # ── Overlay ───────────────────────────────────────────────────────────

    def with_overlay(
        self,
        overlay: ConfigOverlay | Mapping[str, object],
        *,
        env: Mapping[str, str] | None = None,
    ) -> Self:
        """Return a new `Settings` with the overlay's keys applied and validated.

        Three filters, each with a failure it prevents:

        * **Keys set in the process environment are shielded.** The documented
          precedence is `env > DB overlay > .env`: an operator who exports
          `LLM_API_KEY` before starting the daemon must beat whatever the
          `app_config` table says, or a stale/hostile row would be
          unoverridable from the shell. Values that came from the `.env` file
          are *not* shielded (pydantic reads that file without touching
          `os.environ`), so the Settings UI can still override file defaults —
          which is the entire point of the overlay.
        * **Unknown keys are ignored** rather than rejected, so an older binary
          boots against a newer database: a rollback must not be blocked by a
          row for a setting this version has never heard of.
        * **`None` values are dropped** — a nullable column with no value means
          "not set", and letting it through would either blank a configured
          value or fail validation on a non-optional field.

        The result is fully re-validated (overlay values arrive as DB TEXT),
        with the current values passed as init arguments, which pydantic-settings
        ranks above env and `.env` — so applying an overlay never silently
        re-reads a changed environment mid-process.

        `env` is injectable so this precedence rule is testable without mutating
        the real process environment.
        """
        raw = overlay if isinstance(overlay, Mapping) else overlay.overrides()
        known = type(self).model_fields
        shielded = {key.upper() for key in (os.environ if env is None else env)}
        updates = {
            k: v
            for k, v in raw.items()
            if k in known and v is not None and k.upper() not in shielded
        }
        if not updates:
            return self
        merged: dict[str, Any] = {**self.model_dump(), **updates}
        try:
            return type(self)(**merged)
        except ValidationError as exc:
            raise ConfigError(
                f"database config overlay is invalid: {_describe(exc)}",
                cause=exc,
            ) from exc

    # ── Redaction ─────────────────────────────────────────────────────────

    def redacted(self) -> dict[str, Any]:
        """Settings as a wire-safe mapping: secrets become a presence flag.

        Used by the config API, structured logs and `config.changed` events —
        all three are places a key must never appear. A boolean (`True` = a
        value is set) rather than a mask string, because the UI's only real
        question is "is this configured?", and a mask like `sk-…abcd` still
        leaks the prefix and length.

        `Any` is intentional: the return value is heterogeneous JSON.
        """
        out: dict[str, Any] = {}
        for name in type(self).model_fields:
            value = getattr(self, name)
            out[name] = bool(value.get_secret_value()) if isinstance(value, SecretStr) else value
        # Derived views the settings UI needs and cannot compute itself.
        out["cors_origin_list"] = self.cors_origin_list
        out["stytch_configured"] = self.stytch_configured
        out["agent_models"] = {key: self.agent_model(key) for key in AGENT_MODEL_KEYS}
        return out

    @classmethod
    def secret_field_names(cls) -> frozenset[str]:
        """Names of the `SecretStr` fields, for redactors elsewhere in the stack."""
        return frozenset(
            name
            for name, field in cls.model_fields.items()
            if field.annotation is not None and field.annotation is SecretStr
        )


def _describe(exc: ValidationError) -> str:
    """Summarize a validation failure without echoing the offending value.

    pydantic's default rendering includes `input_value=...`, which for a bad
    `LLM_API_KEY` would print the key into a log line or an HTTP error body.
    Only the field location and the reason are safe to repeat.
    """
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}" for err in exc.errors()
    )


def load_settings(overlay: ConfigOverlay | Mapping[str, object] | None = None) -> Settings:
    """Build settings from env + `.env`, then apply an optional DB overlay."""
    try:
        settings = Settings()
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration: {_describe(exc)}", cause=exc) from exc
    return settings if overlay is None else settings.with_overlay(overlay)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings, resolved once from the environment.

    Deliberately excludes the DB overlay: the overlay needs a database, the
    database needs a URL from here, so the bootstrap order is
    `get_settings()` → open DB → `with_overlay()` → hand the result to the app.
    """
    return load_settings()


def reset_settings_cache() -> None:
    """Drop the cached settings (tests, and the daemon's config hot-reload)."""
    get_settings.cache_clear()
