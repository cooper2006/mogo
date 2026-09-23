"""Tests for LLM gateway resilience (feature 007, US1 failover MVP).

These exercise the failover scheduler, error classification, and backoff retry
with in-memory fake clients — no network, no MongoDB.
"""

from __future__ import annotations

import asyncio

import pytest

from app.llm.base import BaseLLMClient
from app.llm.resilience.errors import (
    AllProvidersFailedError,
    NonRetryableLLMError,
    RetryableLLMError,
    classify_error,
    is_retryable,
)
from app.llm.resilience.events import (
    DegradationReason,
    degradation_fields,
    failover_fields,
    reason_from_status,
)
from app.llm.resilience.failover import ProviderEntry, ResilientLLMClient
from app.llm.resilience.retry import RetryPolicy, retry_with_backoff
from app.llm.types import LLMResponse, Message, Role


def _response(text: str = "ok") -> LLMResponse:
    return LLMResponse(message=Message(role=Role.ASSISTANT, content=text))


class _HTTPError(Exception):
    def __init__(self, status_code: int, message: str = "http error") -> None:
        super().__init__(message)
        self.status_code = status_code


class _FakeClient(BaseLLMClient):
    """A fake client that fails ``fail_times`` then succeeds (or always fails)."""

    def __init__(self, name: str, *, fail_status: int | None = None, fail_times: int = 0, text: str = "ok") -> None:
        self.name = name
        self._fail_status = fail_status
        self._fail_times = fail_times
        self._calls = 0
        self.text = text

    async def ainvoke(self, messages, **kwargs) -> LLMResponse:
        self._calls += 1
        if self._fail_status is not None and self._calls <= self._fail_times:
            raise _HTTPError(self._fail_status)
        return _response(f"{self.text}:{self.name}")

    async def astream(self, messages, **kwargs):
        self._calls += 1
        if self._fail_status is not None and self._calls <= self._fail_times:
            raise _HTTPError(self._fail_status)
        yield _response(f"{self.text}:{self.name}")

    async def ainvoke_structured(self, messages, schema, **kwargs):
        return await self.ainvoke(messages, **kwargs)


# --- error classification ---------------------------------------------------

def test_classify_retryable_status_codes() -> None:
    for status in (429, 500, 502, 503, 504, 408):
        assert isinstance(classify_error(_HTTPError(status)), RetryableLLMError)
        assert is_retryable(_HTTPError(status))


def test_classify_non_retryable_auth_errors() -> None:
    for status in (401, 403):
        classified = classify_error(_HTTPError(status))
        assert isinstance(classified, NonRetryableLLMError)
        assert not is_retryable(_HTTPError(status))


def test_classify_timeout_and_connection_are_retryable() -> None:
    assert is_retryable(asyncio.TimeoutError())
    assert is_retryable(ConnectionError("reset"))


# --- events ------------------------------------------------------------------

def test_failover_fields_shape() -> None:
    fields = failover_fields("primary", "backup")
    assert fields["failover_from"] == "primary"
    assert fields["failover_to"] == "backup"
    assert fields["resilience_event"] == "failover"


def test_degradation_fields_shape() -> None:
    fields = degradation_fields(2, provider="mid", reason="429")
    assert fields["degradation_step"] == 2
    assert fields["degradation_reason"] == "429"


def test_reason_from_status_enumerates() -> None:
    assert reason_from_status(429) is DegradationReason.UPSTREAM_429
    assert reason_from_status(503) is DegradationReason.UPSTREAM_5XX
    assert reason_from_status(408) is DegradationReason.TIMEOUT
    assert reason_from_status(None) is DegradationReason.MANUAL


# --- failover ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_failover_to_backup_on_primary_5xx() -> None:
    events: list[dict] = []
    primary = _FakeClient("primary", fail_status=500, fail_times=99)
    backup = _FakeClient("backup", text="ok")
    client = ResilientLLMClient(
        [
            ProviderEntry("primary", lambda: primary, RetryPolicy(max_attempts=1)),
            ProviderEntry("backup", lambda: backup, RetryPolicy(max_attempts=1)),
        ],
        on_event=events.append,
    )

    result = await client.ainvoke([Message(role=Role.USER, content="hi")])

    assert result.content.endswith("backup")
    assert client.last_result is not None
    assert client.last_result.provider == "backup"
    assert any(e.get("failover_from") == "primary" and e.get("failover_to") == "backup" for e in events)


@pytest.mark.asyncio
async def test_single_provider_is_noop_when_healthy() -> None:
    solo = _FakeClient("solo")
    client = ResilientLLMClient([ProviderEntry("solo", lambda: solo)])

    result = await client.ainvoke([Message(role=Role.USER, content="hi")])

    assert result.content.endswith("solo")
    assert solo._calls == 1  # exactly one attempt, no extra work


@pytest.mark.asyncio
async def test_single_provider_failure_raises_aggregated_error() -> None:
    solo = _FakeClient("solo", fail_status=500, fail_times=99)
    client = ResilientLLMClient([ProviderEntry("solo", lambda: solo, RetryPolicy(max_attempts=1))])

    with pytest.raises(AllProvidersFailedError) as excinfo:
        await client.ainvoke([Message(role=Role.USER, content="hi")])

    assert excinfo.value.failures[0]["provider"] == "solo"


@pytest.mark.asyncio
async def test_all_providers_failed_aggregates_each_reason() -> None:
    primary = _FakeClient("primary", fail_status=500, fail_times=99)
    backup = _FakeClient("backup", fail_status=503, fail_times=99)
    client = ResilientLLMClient(
        [
            ProviderEntry("primary", lambda: primary, RetryPolicy(max_attempts=1)),
            ProviderEntry("backup", lambda: backup, RetryPolicy(max_attempts=1)),
        ]
    )

    with pytest.raises(AllProvidersFailedError) as excinfo:
        await client.ainvoke([Message(role=Role.USER, content="hi")])

    providers = {item["provider"] for item in excinfo.value.failures}
    assert providers == {"primary", "backup"}


@pytest.mark.asyncio
async def test_auth_error_does_not_failover() -> None:
    primary = _FakeClient("primary", fail_status=401, fail_times=99)
    backup = _FakeClient("backup")
    client = ResilientLLMClient(
        [
            ProviderEntry("primary", lambda: primary, RetryPolicy(max_attempts=1)),
            ProviderEntry("backup", lambda: backup, RetryPolicy(max_attempts=1)),
        ]
    )

    with pytest.raises(NonRetryableLLMError):
        await client.ainvoke([Message(role=Role.USER, content="hi")])
    assert backup._calls == 0, "auth failure must not fail over to backup"


# --- backoff retry -----------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_succeeds_after_transient_failures() -> None:
    calls = {"n": 0}

    async def op() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise _HTTPError(429)
        return "done"

    result = await retry_with_backoff(
        op, policy=RetryPolicy(base_seconds=0.001, max_seconds=0.01, jitter_seconds=0, max_attempts=5)
    )

    assert result == "done"
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_retry_does_not_retry_auth_error() -> None:
    calls = {"n": 0}

    async def op() -> str:
        calls["n"] += 1
        raise _HTTPError(403)

    with pytest.raises(NonRetryableLLMError):
        await retry_with_backoff(
            op, policy=RetryPolicy(base_seconds=0.001, max_seconds=0.01, jitter_seconds=0, max_attempts=5)
        )
    assert calls["n"] == 1, "401/403 must not be retried"


@pytest.mark.asyncio
async def test_retry_exhausts_and_reraises() -> None:
    calls = {"n": 0}

    async def op() -> str:
        calls["n"] += 1
        raise _HTTPError(503)

    with pytest.raises(RetryableLLMError):
        await retry_with_backoff(
            op, policy=RetryPolicy(base_seconds=0.001, max_seconds=0.01, jitter_seconds=0, max_attempts=3)
        )
    assert calls["n"] == 3


# --- provider config (T005) --------------------------------------------------

def test_build_provider_entries_from_config() -> None:
    from app.llm.resilience.providers import build_provider_entries

    entries = build_provider_entries(
        {
            "providers": [
                {"name": "primary", "kind": "default", "model": "m1"},
                {"name": "backup", "kind": "azure", "model": "m2"},
            ],
            "retry": {"max_attempts": 5, "base_seconds": 0.5},
        }
    )
    assert [e.name for e in entries] == ["primary", "backup"]
    assert entries[0].retry_policy.max_attempts == 5
    assert entries[0].retry_policy.base_seconds == 0.5


def test_build_provider_entries_defaults_to_single_when_unset() -> None:
    from app.llm.resilience.providers import build_provider_entries

    sentinel = _FakeClient("sentinel")
    entries = build_provider_entries({}, default=lambda: sentinel)
    assert len(entries) == 1
    assert entries[0].name == "default"
    assert entries[0].factory() is sentinel


def test_load_resilience_config_missing_file_is_empty(tmp_path) -> None:
    from app.llm.resilience.providers import load_resilience_config

    assert load_resilience_config(tmp_path / "does-not-exist.yaml") == {}


def test_load_resilience_config_reads_yaml(tmp_path) -> None:
    from app.llm.resilience.providers import load_resilience_config

    path = tmp_path / "resilience.yaml"
    path.write_text("providers:\n  - name: p1\n", encoding="utf-8")
    document = load_resilience_config(path)
    assert document["providers"][0]["name"] == "p1"


# --- degradation chain (T011-T014) -------------------------------------------

def test_default_degradation_chain_order() -> None:
    from app.llm.resilience.degradation import DEFAULT_DEGRADATION_CHAIN

    assert DEFAULT_DEGRADATION_CHAIN == ("high", "mid", "light")


def test_build_chain_maps_models() -> None:
    from app.llm.resilience.degradation import build_chain

    chain = build_chain(models={"high": "gpt-5.4", "mid": "gpt-5.2"})
    assert [step.tier for step in chain] == ["high", "mid", "light"]
    assert chain[0].model == "gpt-5.4"


@pytest.mark.asyncio
async def test_primary_success_no_degradation() -> None:
    from app.llm.resilience.degradation import build_chain, run_with_degradation

    async def caller(step):
        return f"ok:{step.tier}"

    output, result = await run_with_degradation(build_chain(), caller)
    assert output == "ok:high"
    assert result.degraded is False
    assert result.step == 1


@pytest.mark.asyncio
async def test_degrades_to_next_tier_on_failure() -> None:
    from app.llm.resilience.degradation import build_chain, run_with_degradation

    async def caller(step):
        if step.tier == "high":
            raise _HTTPError(500)
        return f"ok:{step.tier}"

    events: list[dict] = []
    output, result = await run_with_degradation(build_chain(), caller, on_event=events.append)
    assert output == "ok:mid"
    assert result.degraded is True
    assert result.step == 2
    assert result.log_fields["degradation_step"] == 2
    assert events and events[0]["degradation_step"] == 1


@pytest.mark.asyncio
async def test_chain_exhausted_raises_clear_error() -> None:
    from app.llm.resilience.degradation import DegradationError, build_chain, run_with_degradation

    async def caller(step):
        raise _HTTPError(503)

    with pytest.raises(DegradationError) as excinfo:
        await run_with_degradation(build_chain(), caller)
    assert len(excinfo.value.chain) == 3
    assert all(item["reason"] == "5xx" for item in excinfo.value.failures)


@pytest.mark.asyncio
async def test_auth_failure_aborts_degradation() -> None:
    from app.llm.resilience.degradation import build_chain, run_with_degradation

    async def caller(step):
        raise _HTTPError(401)

    with pytest.raises(NonRetryableLLMError):
        await run_with_degradation(build_chain(), caller)


@pytest.mark.asyncio
async def test_degradation_reason_enumerated() -> None:
    from app.llm.resilience.degradation import build_chain, run_with_degradation

    async def caller(step):
        if step.tier == "high":
            raise _HTTPError(429)
        return "ok"

    events: list[dict] = []
    await run_with_degradation(build_chain(), caller, on_event=events.append)
    assert events[0]["degradation_reason"] == "429"
