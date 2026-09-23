"""Provider failover scheduler (007 US1 / T007).

``ResilientLLMClient`` wraps an ordered list of providers (primary first, then
backups) and implements the ``BaseLLMClient`` surface. On a *retryable* failure it
switches to the next provider; on a *non-retryable* failure (401/403) it fails
immediately. If every provider fails, it raises ``AllProvidersFailedError``
carrying each provider's reason (FR-1 / FR-10).

Single-provider behavior is a strict no-op: the wrapper simply delegates, so
existing call sites are unaffected (FR-9).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Iterable, List, Optional, Type

from pydantic import BaseModel

from ...llm.base import BaseLLMClient
from ...llm.types import LLMResponse, Message
from .errors import (
    AllProvidersFailedError,
    NonRetryableLLMError,
    classify_error,
)
from .events import failover_fields
from .retry import RetryPolicy, retry_with_backoff


@dataclass
class ProviderEntry:
    """A configured provider: a name + a factory that builds its client."""

    name: str
    factory: Callable[[], BaseLLMClient]
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)


@dataclass
class FailoverResult:
    """Metadata about which provider ultimately served a call."""

    provider: str
    attempts: int
    failed_providers: list[str] = field(default_factory=list)
    log_fields: dict[str, Any] = field(default_factory=dict)


class ResilientLLMClient(BaseLLMClient):
    """A ``BaseLLMClient`` that fails over across an ordered provider list."""

    def __init__(
        self,
        providers: Iterable[ProviderEntry],
        *,
        on_event: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> None:
        entries = list(providers)
        if not entries:
            raise ValueError("ResilientLLMClient requires at least one provider")
        self._providers = entries
        self._on_event = on_event
        self.last_result: Optional[FailoverResult] = None

    @property
    def provider_names(self) -> list[str]:
        return [entry.name for entry in self._providers]

    def _emit(self, fields: dict[str, Any]) -> None:
        if self._on_event is not None:
            self._on_event(fields)

    async def _run_with_failover(self, operation_factory: Callable[[BaseLLMClient], Any]) -> Any:
        """Try each provider in order; return the first successful result."""
        failures: list[dict[str, Any]] = []
        failed_providers: list[str] = []
        log_fields: dict[str, Any] = {}

        for index, entry in enumerate(self._providers):
            client = entry.factory()
            attempt_no = {"n": 0}

            def _on_retry(attempt: int, error: BaseException) -> None:
                attempt_no["n"] = attempt

            try:
                result = await retry_with_backoff(
                    lambda c=client: operation_factory(c),
                    policy=entry.retry_policy,
                    on_retry=_on_retry,
                )
            except NonRetryableLLMError:
                # Auth failures must not fail over — surface immediately.
                raise
            except BaseException as error:  # noqa: BLE001
                classified = classify_error(error, provider=entry.name)
                failures.append({"provider": entry.name, "reason": str(classified)})
                failed_providers.append(entry.name)
                if index + 1 < len(self._providers):
                    next_name = self._providers[index + 1].name
                    log_fields = failover_fields(entry.name, next_name, attempt=max(1, attempt_no["n"]))
                    self._emit(log_fields)
                continue

            # Success: if we had failed over, record from -> to.
            if failed_providers:
                fields = failover_fields(failed_providers[-1], entry.name)
                fields.update(log_fields)
                log_fields = fields
            self.last_result = FailoverResult(
                provider=entry.name,
                attempts=index + 1,
                failed_providers=failed_providers,
                log_fields=log_fields,
            )
            return result

        raise AllProvidersFailedError(failures)

    async def ainvoke(self, messages: List[Message], **kwargs: Any) -> LLMResponse:
        return await self._run_with_failover(lambda client: client.ainvoke(messages, **kwargs))

    async def ainvoke_structured(
        self, messages: List[Message], schema: Type[BaseModel], **kwargs: Any
    ) -> BaseModel:
        return await self._run_with_failover(
            lambda client: client.ainvoke_structured(messages, schema, **kwargs)
        )

    async def astream(
        self, messages: List[Message], **kwargs: Any
    ) -> AsyncGenerator[LLMResponse, None]:
        # Streaming failover is best-effort: we fail over only if the very first
        # chunk fails. Once tokens have been emitted, switching providers would
        # duplicate output, so we let the error propagate.
        started = False
        async for chunk in self._stream_with_failover(messages, started_ref={"started": started}, **kwargs):
            started = True
            yield chunk

    async def _stream_with_failover(
        self, messages: List[Message], *, started_ref: dict[str, bool], **kwargs: Any
    ) -> AsyncGenerator[LLMResponse, None]:
        failures: list[dict[str, Any]] = []
        for index, entry in enumerate(self._providers):
            client = entry.factory()
            try:
                async for chunk in client.astream(messages, **kwargs):
                    started_ref["started"] = True
                    yield chunk
                return
            except NonRetryableLLMError:
                raise
            except BaseException as error:  # noqa: BLE001
                if started_ref["started"]:
                    raise
                classified = classify_error(error, provider=entry.name)
                failures.append({"provider": entry.name, "reason": str(classified)})
                if index + 1 < len(self._providers):
                    self._emit(
                        failover_fields(entry.name, self._providers[index + 1].name)
                    )
                continue
        raise AllProvidersFailedError(failures)
