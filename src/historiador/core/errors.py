"""Typed error hierarchy for the runtime.

Two properties make this hierarchy load-bearing:

1. **`retryable` is data, not a guess.** `retry.py` classifies a failure by
   asking the error, never by string-matching a message. The default is
   `False` — a newly added error type is *not* retried until someone decides it
   should be, because a wrongly-retried failure burns money and time on every
   run, while a wrongly-terminal one fails loudly once.
2. **`to_payload()` is the wire format.** Errors travel into events, into the
   SQLite event log, and out over the WebSocket to a browser. So the payload is
   assembled from explicitly whitelisted fields: never a traceback (it leaks
   file paths and local variables), never the exception's `repr` of an
   arbitrary foreign object (which is where API keys hide, e.g. inside an httpx
   request URL).
"""

from __future__ import annotations

from typing import Any, ClassVar

__all__ = [
    "AgentError",
    "CancelledError",
    "ConfigError",
    "GraphError",
    "HistoriadorError",
    "LLMError",
    "LLMStatusError",
    "LLMTransportError",
    "RunError",
    "StructuredOutputError",
    "TimeoutError",
    "ToolError",
]

# How far down a `__cause__` chain `to_payload()` will walk. Deep enough to
# explain a failure (node → agent → llm → transport), shallow enough that a
# pathological or self-referential chain cannot produce an unbounded payload.
_MAX_CAUSE_DEPTH = 4

# Structured output can be a whole document. The payload is broadcast to every
# connected dashboard on every retry, so the raw text is truncated hard; the
# untruncated value stays on the exception for local logging only.
_MAX_RAW_CHARS = 512


class HistoriadorError(Exception):
    """Base class for every error the runtime raises deliberately.

    `code` is the stable machine-readable discriminator the UI switches on;
    class names are refactorable, wire codes are not.
    """

    code: ClassVar[str] = "historiador_error"

    #: Whether `retry.py` may re-run the failed operation. Instances may narrow
    #: or widen this (see `LLMStatusError`), so it is a plain attribute rather
    #: than a ClassVar.
    retryable: bool = False

    def __init__(self, message: str = "", *, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.message = message
        if cause is not None:
            # Assigning `__cause__` gives `raise Err(..., cause=e)` the same
            # chain as `raise Err(...) from e`, so a wrapper constructed outside
            # an `except` block (the dispatcher builds RunError after the retry
            # loop has ended) still preserves what actually went wrong.
            self.__cause__ = cause

    # ── wire format ───────────────────────────────────────────────────────

    def to_payload(self) -> dict[str, Any]:
        """A JSON-serializable, credential-free, traceback-free description.

        `Any` is unavoidable here: the payload is heterogeneous JSON by design
        (that is what the event bus carries).
        """
        return self._payload(depth=_MAX_CAUSE_DEPTH)

    def _payload(self, *, depth: int) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "type": type(self).__name__,
            "message": self.message,
            "retryable": self.retryable,
        }
        details = self._details()
        if details:
            payload["details"] = details
        cause = self.__cause__
        if cause is not None and depth > 0:
            payload["cause"] = _cause_payload(cause, depth=depth - 1)
        return payload

    def _details(self) -> dict[str, Any]:
        """Subclass hook: the extra fields this error type puts on the wire.

        Whitelist, never a `__dict__` dump — that is how a credential would
        eventually leak in via some future field nobody re-reviewed.
        """
        return {}

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.message!r})"


def _cause_payload(exc: BaseException, *, depth: int) -> dict[str, Any]:
    """Describe a cause without trusting its string form.

    Our own errors are safe to render fully: every field on them was chosen by
    us. A foreign exception (httpx, sqlite, json) is reduced to its type name —
    its message routinely embeds the request URL, which routinely embeds an API
    key.
    """
    if isinstance(exc, HistoriadorError):
        return exc._payload(depth=depth)
    return {"code": "foreign_error", "type": type(exc).__name__, "retryable": False}


# ── configuration & graph ────────────────────────────────────────────────


class ConfigError(HistoriadorError):
    """Missing or invalid configuration. Never retryable: nothing will change."""

    code: ClassVar[str] = "config_error"

    def __init__(
        self, message: str = "", *, key: str | None = None, cause: BaseException | None = None
    ) -> None:
        super().__init__(message, cause=cause)
        self.key = key

    def _details(self) -> dict[str, Any]:
        # The offending key's *name*, never its value — the value is the secret.
        return {"key": self.key} if self.key is not None else {}


class GraphError(HistoriadorError):
    """Malformed DAG: cycle, dangling dependency, duplicate node id.

    Raised at construction so a bad graph fails before the run starts, never
    halfway through when half the nodes have already spent tokens.
    """

    code: ClassVar[str] = "graph_error"

    def __init__(
        self, message: str = "", *, node_id: str | None = None, cause: BaseException | None = None
    ) -> None:
        super().__init__(message, cause=cause)
        self.node_id = node_id

    def _details(self) -> dict[str, Any]:
        return {"node_id": self.node_id} if self.node_id is not None else {}


# ── control flow ─────────────────────────────────────────────────────────


class CancelledError(HistoriadorError):
    """A run or node was cancelled cooperatively.

    Deliberately *not* a subclass of `asyncio.CancelledError`: that one is a
    `BaseException` the event loop uses for its own bookkeeping and which must
    propagate untouched. This is an ordinary error that can be caught, stored on
    a node, and serialized into a `RUN_CANCELLED` event.
    """

    code: ClassVar[str] = "cancelled"

    def __init__(
        self, message: str = "", *, reason: str | None = None, cause: BaseException | None = None
    ) -> None:
        super().__init__(message, cause=cause)
        self.reason = reason

    def _details(self) -> dict[str, Any]:
        return {"reason": self.reason} if self.reason is not None else {}


class TimeoutError(HistoriadorError):  # noqa: A001 - deliberately mirrors the builtin name
    """A bounded operation exceeded its deadline.

    Retryable: a timeout is usually a slow provider, and the dispatcher's whole
    reason for owning `AgentSpec.timeout_s` is to convert a hang into a bounded,
    retryable failure.
    """

    code: ClassVar[str] = "timeout"
    retryable: bool = True

    def __init__(
        self, message: str = "", *, limit_s: float, cause: BaseException | None = None
    ) -> None:
        super().__init__(message, cause=cause)
        self.limit_s = limit_s

    def _details(self) -> dict[str, Any]:
        return {"limit_s": self.limit_s}


# ── agents, tools, LLM ───────────────────────────────────────────────────


class AgentError(HistoriadorError):
    """An agent failed on its own terms (bad input, unusable upstream result).

    Not retryable by default: re-running the same agent over the same input
    reproduces the same failure. A subclass or an explicit `retryable = True`
    is the way to say otherwise.
    """

    code: ClassVar[str] = "agent_error"

    def __init__(
        self, message: str = "", *, agent: str, cause: BaseException | None = None
    ) -> None:
        super().__init__(message, cause=cause)
        self.agent = agent

    def _details(self) -> dict[str, Any]:
        return {"agent": self.agent}


class ToolError(HistoriadorError):
    """A tool invocation failed (search provider, scraper, …)."""

    code: ClassVar[str] = "tool_error"

    def __init__(
        self,
        message: str = "",
        *,
        tool: str,
        retryable: bool = False,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message, cause=cause)
        self.tool = tool
        # Tools span everything from a pure parse (never retryable) to an HTTP
        # fetch (usually retryable), so the caller that knows which kind it is
        # decides — but silence still means "do not retry".
        self.retryable = retryable

    def _details(self) -> dict[str, Any]:
        return {"tool": self.tool}


class LLMError(HistoriadorError):
    """Base for every failure of the LLM layer."""

    code: ClassVar[str] = "llm_error"


class LLMTransportError(LLMError):
    """The request never produced an HTTP response: DNS, TLS, connect, read.

    Retryable by default — this is the canonical transient failure. The flag is
    still a parameter because a permanent transport fault (unresolvable host,
    invalid certificate) should not be hammered.
    """

    code: ClassVar[str] = "llm_transport_error"
    retryable: bool = True

    def __init__(
        self, message: str = "", *, retryable: bool = True, cause: BaseException | None = None
    ) -> None:
        super().__init__(message, cause=cause)
        self.retryable = retryable


class LLMStatusError(LLMError):
    """The provider answered with a non-2xx status.

    Retryability is derived from the status, never passed in, so no call site
    can accidentally mark a 401 as retryable and turn a bad API key into an
    infinite billing loop: 429 (rate limited) and 5xx (provider-side) are worth
    another attempt; 4xx otherwise means the request itself is wrong.
    """

    code: ClassVar[str] = "llm_status_error"

    def __init__(
        self,
        message: str = "",
        *,
        status: int,
        retry_after_s: float | None = None,
        provider_code: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message, cause=cause)
        self.status = status
        # Honored by retry.py in preference to computed backoff (§5).
        self.retry_after_s = retry_after_s
        # The provider's own error slug, e.g. "context_length_exceeded".
        self.provider_code = provider_code
        self.retryable = status == 429 or status >= 500

    def _details(self) -> dict[str, Any]:
        details: dict[str, Any] = {"status": self.status}
        if self.retry_after_s is not None:
            details["retry_after_s"] = self.retry_after_s
        if self.provider_code is not None:
            details["provider_code"] = self.provider_code
        return details


class StructuredOutputError(LLMError):
    """The model's output could not be coerced into the requested schema.

    Retryable: the repair ladder in `structured.py` has already tried parsing,
    extraction, and one schema-guided re-ask, and a fresh sample from a
    non-deterministic model genuinely may succeed.
    """

    code: ClassVar[str] = "structured_output_error"
    retryable: bool = True

    def __init__(
        self,
        message: str = "",
        *,
        raw: str = "",
        schema: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message, cause=cause)
        #: The full offending text. Kept for local logs; never sent whole.
        self.raw = raw
        self.schema = schema

    def _details(self) -> dict[str, Any]:
        truncated = len(self.raw) > _MAX_RAW_CHARS
        details: dict[str, Any] = {
            "raw": self.raw[:_MAX_RAW_CHARS],
            "raw_truncated": truncated,
            "raw_len": len(self.raw),
        }
        if self.schema is not None:
            details["schema"] = self.schema
        return details


# ── run-level wrapper ────────────────────────────────────────────────────


class RunError(HistoriadorError):
    """A node's attempts are exhausted; this is what the run records and shows.

    Never retryable: by the time a `RunError` exists the retry policy has
    already given up, so treating it as retryable would restart an
    already-finished decision. The underlying failure survives on `__cause__`
    and in `to_payload()["cause"]`, which is what makes a dashboard able to say
    *"node research-2 failed after 3 attempts: 429 from the provider"* instead
    of just *"failed"*.
    """

    code: ClassVar[str] = "run_error"

    def __init__(
        self,
        message: str = "",
        *,
        node_id: str,
        attempts: int,
        agent: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message, cause=cause)
        self.node_id = node_id
        self.attempts = attempts
        self.agent = agent

    def _details(self) -> dict[str, Any]:
        details: dict[str, Any] = {"node_id": self.node_id, "attempts": self.attempts}
        if self.agent is not None:
            details["agent"] = self.agent
        return details
