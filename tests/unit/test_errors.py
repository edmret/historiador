"""The error hierarchy is a contract: retry classification and wire safety."""

from __future__ import annotations

import json
import traceback

import pytest

from historiador.core.errors import (
    AgentError,
    CancelledError,
    ConfigError,
    GraphError,
    HistoriadorError,
    LLMError,
    LLMStatusError,
    LLMTransportError,
    RunError,
    StructuredOutputError,
    TimeoutError,  # noqa: A004 - the runtime's own timeout type, deliberately named
    ToolError,
)

SECRET = "sk-live-DO-NOT-LEAK-1234567890"


def _all_error_types() -> list[type[HistoriadorError]]:
    return [
        ConfigError,
        GraphError,
        CancelledError,
        TimeoutError,
        AgentError,
        LLMError,
        LLMTransportError,
        LLMStatusError,
        StructuredOutputError,
        ToolError,
        RunError,
    ]


def test_every_error_is_a_historiador_error_with_a_unique_code() -> None:
    codes = [cls.code for cls in _all_error_types()]
    assert all(issubclass(cls, HistoriadorError) for cls in _all_error_types())
    assert len(codes) == len(set(codes)), f"duplicate wire codes: {codes}"


# ── retry classification ─────────────────────────────────────────────────


def test_base_default_is_not_retryable() -> None:
    """A new error type must opt in to being retried, never inherit it."""
    assert HistoriadorError("boom").retryable is False


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ConfigError("no key"), False),
        (GraphError("cycle"), False),
        (CancelledError("stopped"), False),
        (TimeoutError("slow", limit_s=30.0), True),
        (AgentError("bad input", agent="writer"), False),
        (LLMError("generic"), False),
        (LLMTransportError("connection reset"), True),
        (LLMTransportError("bad certificate", retryable=False), False),
        (StructuredOutputError("not json", raw="{"), True),
        (ToolError("parse failed", tool="scraper"), False),
        (ToolError("fetch failed", tool="scraper", retryable=True), True),
        (RunError("exhausted", node_id="n1", attempts=3), False),
    ],
)
def test_retryable_classification(error: HistoriadorError, expected: bool) -> None:
    assert error.retryable is expected


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, False),  # our request is wrong; retrying reproduces it
        (401, False),  # bad key; retrying is an infinite billing loop
        (403, False),
        (404, False),
        (422, False),
        (428, False),  # boundary just below 429
        (429, True),  # rate limited
        (430, False),  # boundary just above 429
        (499, False),  # last 4xx
        (500, True),  # first 5xx
        (502, True),
        (503, True),
        (504, True),
    ],
)
def test_llm_status_error_retryable_boundaries(status: int, expected: bool) -> None:
    assert LLMStatusError("http", status=status).retryable is expected


def test_llm_status_error_carries_retry_after_and_provider_code() -> None:
    error = LLMStatusError(
        "rate limited", status=429, retry_after_s=2.5, provider_code="rate_limit_exceeded"
    )
    details = error.to_payload()["details"]
    assert details == {
        "status": 429,
        "retry_after_s": 2.5,
        "provider_code": "rate_limit_exceeded",
    }


# ── payload safety ───────────────────────────────────────────────────────


def test_payload_is_json_serializable_for_every_error_type() -> None:
    errors: list[HistoriadorError] = [
        ConfigError("missing", key="LLM_API_KEY"),
        GraphError("cycle", node_id="n1"),
        CancelledError("stopped", reason="user"),
        TimeoutError("slow", limit_s=30.0),
        AgentError("bad", agent="writer"),
        LLMTransportError("reset"),
        LLMStatusError("http", status=503, retry_after_s=1.0),
        StructuredOutputError("bad json", raw="{}", schema="Outline"),
        ToolError("failed", tool="search"),
        RunError("failed", node_id="n1", attempts=2, agent="research"),
    ]
    for error in errors:
        payload = error.to_payload()
        assert json.loads(json.dumps(payload)) == payload
        assert payload["code"] == type(error).code
        assert payload["type"] == type(error).__name__
        assert payload["retryable"] is error.retryable


def test_payload_never_contains_a_traceback() -> None:
    try:
        raise LLMTransportError("connection reset")
    except LLMTransportError as exc:
        error = RunError("node failed", node_id="n1", attempts=3, cause=exc)

    blob = json.dumps(error.to_payload())
    for forbidden in ("Traceback", "test_errors.py", "__traceback__", 'File "'):
        assert forbidden not in blob
    # The traceback is genuinely reachable from the exception, so the payload's
    # silence is a deliberate omission rather than an empty chain.
    cause = error.__cause__
    assert cause is not None
    assert "test_errors.py" in "".join(traceback.format_exception(cause))


def test_payload_does_not_leak_a_foreign_exceptions_message() -> None:
    """httpx-style exceptions embed the request URL, which embeds the API key."""
    foreign = RuntimeError(f"GET https://api.example.com/v1/chat?api_key={SECRET} failed")
    error = LLMTransportError("upstream request failed", cause=foreign)

    blob = json.dumps(error.to_payload())
    assert SECRET not in blob
    assert "api.example.com" not in blob
    # The type name still survives, which is what a dashboard needs.
    assert error.to_payload()["cause"] == {
        "code": "foreign_error",
        "type": "RuntimeError",
        "retryable": False,
    }


def test_config_error_reports_the_key_name_never_its_value() -> None:
    error = ConfigError("LLM_API_KEY is not set", key="LLM_API_KEY")
    blob = json.dumps(error.to_payload())
    assert "LLM_API_KEY" in blob
    assert SECRET not in blob


def test_structured_output_raw_is_truncated_hard_in_the_payload() -> None:
    raw = "x" * 5000
    error = StructuredOutputError("unparseable", raw=raw)
    details = error.to_payload()["details"]

    assert error.raw == raw  # full text stays available for local logs
    assert len(details["raw"]) == 512
    assert details["raw_truncated"] is True
    assert details["raw_len"] == 5000


def test_structured_output_short_raw_is_not_marked_truncated() -> None:
    error = StructuredOutputError("unparseable", raw="{oops}")
    details = error.to_payload()["details"]
    assert details["raw"] == "{oops}"
    assert details["raw_truncated"] is False


# ── cause chains ─────────────────────────────────────────────────────────


def test_run_error_preserves_its_cause_chain_via_dunder_cause() -> None:
    status = LLMStatusError("rate limited", status=429, retry_after_s=1.5)
    try:
        raise status
    except LLMStatusError as exc:
        agent = AgentError("research agent failed", agent="research", cause=exc)
    run = RunError(
        "node exhausted", node_id="research-2", attempts=3, agent="research", cause=agent
    )

    assert run.__cause__ is agent
    assert agent.__cause__ is status

    payload = run.to_payload()
    assert payload["details"] == {"node_id": "research-2", "attempts": 3, "agent": "research"}
    assert payload["cause"]["type"] == "AgentError"
    assert payload["cause"]["cause"]["type"] == "LLMStatusError"
    assert payload["cause"]["cause"]["details"]["status"] == 429
    assert payload["cause"]["cause"]["retryable"] is True


def test_raise_from_produces_the_same_chain_as_the_cause_argument() -> None:
    inner = LLMTransportError("reset")

    def wrap_and_raise() -> None:
        try:
            raise inner
        except LLMTransportError as exc:
            raise RunError("failed", node_id="n1", attempts=1) from exc

    with pytest.raises(RunError) as caught:
        wrap_and_raise()

    assert caught.value.__cause__ is inner
    assert caught.value.to_payload()["cause"]["code"] == "llm_transport_error"


def test_cause_chain_depth_is_bounded() -> None:
    """A pathological chain must not produce an unbounded payload."""
    error: HistoriadorError = LLMError("root")
    for index in range(20):
        error = AgentError(f"layer {index}", agent="a", cause=error)

    payload = error.to_payload()
    depth = 0
    node = payload
    while "cause" in node:
        node = node["cause"]
        depth += 1
    assert depth == 4


def test_self_referential_cause_chain_terminates() -> None:
    error = AgentError("loop", agent="a")
    error.__cause__ = error
    payload = error.to_payload()  # must not recurse forever
    assert payload["details"] == {"agent": "a"}


def test_errors_without_a_cause_omit_the_key() -> None:
    assert "cause" not in ConfigError("nope").to_payload()


def test_our_control_flow_errors_do_not_shadow_the_builtins_semantics() -> None:
    """Ours must stay catchable `Exception`s, not asyncio/BaseException lookalikes."""
    import asyncio
    import builtins

    assert not issubclass(CancelledError, asyncio.CancelledError)
    assert issubclass(CancelledError, Exception)
    assert not issubclass(TimeoutError, builtins.TimeoutError)
    assert issubclass(TimeoutError, Exception)
