"""Translate DSH model calls to ASKAI's existing configured-model clients."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
import logging
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.llm.base import BaseLLMClient
from app.llm.configured_models import (
    ModelConfigError,
    build_llm_client_from_config,
    get_llm_client_by_model_id,
    get_model_config,
)
from app.llm.types import Message, Role

from .token import ModelGatewayClaims
from .tool_schema import to_openai_chat_tools
from .tool_visibility import visible_tools

logger = logging.getLogger(__name__)


class ModelGatewayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profileVersion: str = Field(min_length=1)
    modelInstanceId: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    system: str | None = None
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    maxTokens: int | None = Field(default=None, ge=1)
    sessionId: str | None = None


class ModelGatewayResponse(BaseModel):
    text: str
    usage: dict[str, int] = Field(default_factory=dict)
    model_instance_id: str
    model_name: str


class ModelGatewayFailure(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


ClientFactory = Callable[[str, str, ModelGatewayRequest], Awaitable[BaseLLMClient]]


class ModelGatewayService:
    def __init__(self, client_factory: ClientFactory | None = None) -> None:
        self._client_factory = client_factory or self._configured_client

    async def generate(
        self,
        request: ModelGatewayRequest,
        claims: ModelGatewayClaims,
    ) -> ModelGatewayResponse:
        self._validate_scope(request, claims)
        try:
            client = await self._client_factory(claims.model_instance_id, claims.tenant_id, request)
            messages = self._messages(request)
            kwargs: dict[str, Any] = {}
            if request.maxTokens:
                kwargs["max_tokens"] = request.maxTokens
            tools = await visible_tools(
                request.tools, session_id=request.sessionId or "", tenant_id=claims.tenant_id
            )
            if tools:
                kwargs["tools"] = to_openai_chat_tools(tools)
                kwargs["tool_choice"] = "auto"
            response = await client.ainvoke(messages, **kwargs)
        except ModelConfigError as exc:
            raise ModelGatewayFailure(
                "model_configuration_invalid",
                self._safe_message(exc),
                retryable=False,
            ) from exc
        except Exception as exc:
            code, retryable = self._classify_provider_failure(exc)
            raise ModelGatewayFailure(code, self._safe_message(exc), retryable=retryable) from exc
        content = response.content
        text = content if isinstance(content, str) else str(content or "")
        usage = self._usage(response.usage or {})
        return ModelGatewayResponse(
            text=text,
            usage=usage,
            model_instance_id=claims.model_instance_id,
            model_name=request.model,
        )

    async def stream(
        self,
        request: ModelGatewayRequest,
        claims: ModelGatewayClaims,
    ) -> AsyncIterator[dict[str, Any]]:
        """Prepare an authenticated provider stream and expose incremental chunks."""
        self._validate_scope(request, claims)
        try:
            client = await self._client_factory(claims.model_instance_id, claims.tenant_id, request)
        except ModelConfigError as exc:
            raise ModelGatewayFailure(
                "model_configuration_invalid", self._safe_message(exc), retryable=False
            ) from exc
        except Exception as exc:
            code, retryable = self._classify_provider_failure(exc)
            raise ModelGatewayFailure(code, self._safe_message(exc), retryable=retryable) from exc

        messages = self._messages(request)
        kwargs: dict[str, Any] = {}
        if request.maxTokens:
            kwargs["max_tokens"] = request.maxTokens
        tools = await visible_tools(
            request.tools, session_id=request.sessionId or "", tenant_id=claims.tenant_id
        )
        if tools:
            kwargs["tools"] = to_openai_chat_tools(tools)
            kwargs["tool_choice"] = "auto"

        async def iterator() -> AsyncIterator[dict[str, Any]]:
            usage: dict[str, int] = {}
            tool_calls: dict[int, dict[str, str]] = {}
            try:
                async for chunk in client.astream(messages, **kwargs):
                    content = chunk.content
                    text = content if isinstance(content, str) else str(content or "")
                    if text:
                        yield {"type": "text-delta", "text": text}
                    for raw_call in list(chunk.tool_calls or []):
                        if not isinstance(raw_call, dict):
                            continue
                        index = int(raw_call.get("index") or 0)
                        current = tool_calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                        current["id"] = str(raw_call.get("id") or current["id"])
                        current["name"] = str(raw_call.get("name") or (raw_call.get("function") or {}).get("name") or current["name"])
                        if "arguments" in raw_call:
                            current["arguments"] = str(raw_call.get("arguments") or "{}")
                        else:
                            current["arguments"] += str(raw_call.get("arguments_delta") or "")
                    if chunk.usage:
                        usage = self._usage(chunk.usage)
                for index in sorted(tool_calls):
                    call = tool_calls[index]
                    if call["id"] and call["name"]:
                        yield {"type": "tool-call", **call}
                if usage:
                    yield {"type": "usage", "usage": usage}
                yield {"type": "finish", "reason": {"kind": "tool-calls" if tool_calls else "stop"}}
            except Exception as exc:
                code, retryable = self._classify_provider_failure(exc)
                yield {
                    "type": "error",
                    "error": {
                        "code": code,
                        "message": self._safe_message(exc),
                        "retryable": retryable,
                    },
                }

        return iterator()

    @staticmethod
    async def _configured_client(
        model_instance_id: str,
        tenant_id: str,
        request: ModelGatewayRequest,
    ) -> BaseLLMClient:
        # 007：走 get_llm_client_by_model_id，自动包含 wrap_resilient 与 fallback，
        # output_spec 不含 user_id 以跳过配额检查（网关层已独立校验）。
        return await get_llm_client_by_model_id(
            model_instance_id,
            main_id=tenant_id,
            streaming=True,
            intent="chat",
            stage="dsh_agent_turn",
            output_spec={
                "main_id": tenant_id,
                "model_instance_id": model_instance_id,
                "session_id": request.sessionId or "",
                "profile_version": request.profileVersion,
            },
        )

    @staticmethod
    def _validate_scope(request: ModelGatewayRequest, claims: ModelGatewayClaims) -> None:
        if request.profileVersion != claims.profile_version:
            raise ModelGatewayFailure("profile_scope_mismatch", "profile scope mismatch", retryable=False)
        if request.modelInstanceId != claims.model_instance_id:
            raise ModelGatewayFailure("model_scope_mismatch", "model scope mismatch", retryable=False)
        if request.provider != "askai-model-gateway":
            raise ModelGatewayFailure("provider_scope_mismatch", "provider scope mismatch", retryable=False)

    @staticmethod
    def _call_id(raw: dict[str, Any], block: dict[str, Any] | None = None) -> str:
        """Resolve the tool-call identity DSH correlates a tool result with.

        DSH puts the id on the message itself (``toolCallId``); older/other
        producers inline it in the content block. OpenAI-compatible providers
        reject a tool-role message without ``tool_call_id``, so both shapes are
        accepted instead of silently yielding an empty string.
        """
        sources = [raw, block or {}]
        for source in sources:
            for key in ("toolCallId", "tool_call_id", "tool_use_id", "callId", "call_id"):
                value = str(source.get(key) or "").strip()
                if value:
                    return value
        return ""

    @staticmethod
    def _messages(request: ModelGatewayRequest) -> list[Message]:
        result: list[Message] = []
        if request.system:
            result.append(Message(role=Role.SYSTEM, content=request.system))
        for raw in request.messages:
            role_value = str(raw.get("role") or "user")
            try:
                role = Role(role_value)
            except ValueError:
                role = Role.USER
            content = raw.get("content")
            message_call_id = ModelGatewayService._call_id(raw)
            if isinstance(content, list):
                blocks = [block for block in content if isinstance(block, dict)]
                tool_results = [block for block in blocks if block.get("type") == "tool-result"]
                if tool_results:
                    for block in tool_results:
                        result_text = "\n".join(
                            str(item.get("text") or "")
                            for item in list(block.get("content") or [])
                            if isinstance(item, dict) and item.get("type") == "text"
                        )
                        result.append(Message(
                            role=Role.TOOL,
                            content=result_text,
                            tool_call_id=ModelGatewayService._call_id(raw, block),
                        ))
                    continue
                text = "\n".join(str(block.get("text") or "") for block in blocks if block.get("type") == "text")
                calls = [
                    {
                        "id": str(block.get("id") or ""),
                        "type": "function",
                        "function": {
                            "name": str(block.get("name") or ""),
                            "arguments": str(block.get("arguments") or "{}"),
                        },
                    }
                    for block in blocks if block.get("type") == "tool-call"
                ]
            else:
                text = str(content or "")
                calls = []
            if role is Role.TOOL and not message_call_id:
                # OpenAI-compatible providers reject a tool-role message without
                # tool_call_id. Log the raw shape instead of turning an unknown
                # producer format into an opaque 400 on the next request.
                logger.warning(
                    "model_gateway_tool_message_without_call_id keys=%s",
                    sorted(str(key) for key in raw.keys()),
                )
            result.append(Message(
                role=role,
                content=text,
                tool_calls=calls or None,
                tool_call_id=message_call_id if role is Role.TOOL else None,
            ))
        return result

    @staticmethod
    def _usage(raw: dict[str, Any]) -> dict[str, int]:
        input_tokens = int(raw.get("inputTokens") or raw.get("prompt_tokens") or 0)
        output_tokens = int(raw.get("outputTokens") or raw.get("completion_tokens") or 0)
        result = {"inputTokens": input_tokens, "outputTokens": output_tokens}
        cache = int(raw.get("cacheReadTokens") or raw.get("cache_read_tokens") or 0)
        reasoning = int(raw.get("reasoningTokens") or raw.get("reasoning_tokens") or 0)
        if cache:
            result["cacheReadTokens"] = cache
        if reasoning:
            result["reasoningTokens"] = reasoning
        return result

    @staticmethod
    def _classify_provider_failure(exc: Exception) -> tuple[str, bool]:
        text = str(exc).lower()
        if any(value in text for value in ("401", "403", "unauthorized", "api key", "authentication")):
            return "model_authentication_failed", False
        if any(value in text for value in ("insufficient quota", "balance", "credits exhausted")):
            return "model_quota_exhausted", False
        if any(value in text for value in ("429", "rate limit")):
            return "model_rate_limited", True
        if any(value in text for value in ("timeout", "timed out")):
            return "model_timeout", True
        return "model_provider_failed", True

    @staticmethod
    def _safe_message(exc: Exception) -> str:
        message = str(exc)[:2000]
        message = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[REDACTED]", message)
        message = re.sub(
            r"(?i)\b(api[_ -]?key|authorization|bearer)(\s*[:=]?\s*)[^\s,;]+",
            r"\1\2[REDACTED]",
            message,
        )
        return message or "model provider request failed"
