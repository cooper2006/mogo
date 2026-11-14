from typing import Any, Dict

from app.core.config import get_settings
from app.infrastructure.observability.config import log_print
from app.llm.capabilities import infer_structured_output_mode
from app.llm.model_router import ModelSelection, get_model_router
from app.infrastructure.observability.execution_trace import ensure_trace_id, log_trace
from app.infrastructure.request_context import get_request_context

from app.llm.base import BaseLLMClient
from app.llm.configured_models import build_llm_client_from_config, get_configured_model_context
from app.llm.instrumented_client import InstrumentedLLMClient
from app.llm.providers.azure_openai import AzureOpenAIClient
from app.llm.providers.default_openai import DefaultOpenAIClient
from app.llm.providers.qwen import QwenClient


def _validate_api_key_ascii(*, api_key: str, provider: str) -> None:
    key = str(api_key or "")
    if key and not key.isascii():
        raise ValueError(
            f"Invalid {provider} API key: contains non-ASCII characters. "
            "Please set a real API key in backend/.env (do not use Chinese placeholder text)."
        )


def _resolve_azure_deployment(*, selected_model: str, intent: str | None, stage: str | None) -> tuple[str, str]:
    settings = get_settings()
    dep_chat = str(settings.AZURE_DEPLOYMENT_CHAT or "").strip()
    dep_general = str(settings.AZURE_DEPLOYMENT_GENERAL or "").strip()
    dep_coding = str(settings.AZURE_DEPLOYMENT_CODING or "").strip()
    dep_default = str(settings.AZURE_DEPLOYMENT_NAME or "").strip()

    model_chat = str(settings.OPENAI_MODEL_CHAT or "").strip().lower()
    model_general = str(settings.OPENAI_MODEL_GENERAL or "").strip().lower()
    model_coding = str(settings.OPENAI_MODEL_CODING or "").strip().lower()
    selected = str(selected_model or "").strip().lower()
    stage_s = str(stage or "").strip().lower()
    intent_s = str(intent or "").strip().lower()

    route_key = "general"
    if selected and selected == model_coding:
        route_key = "coding"
    elif selected and selected == model_chat:
        route_key = "chat"
    elif selected and selected == model_general:
        route_key = "general"
    elif "codex" in selected or "coding" in selected or stage_s == "coding" or intent_s == "coding":
        route_key = "coding"
    elif stage_s in {"browser_planning", "research_query_refine"} or intent_s in {"chat", "browser_automation"}:
        route_key = "chat"

    deployment = {
        "chat": dep_chat,
        "general": dep_general,
        "coding": dep_coding,
    }.get(route_key, "")

    if not deployment:
        deployment = dep_default or dep_general or dep_chat or dep_coding
    return deployment, route_key


def _merge_output_spec(output_spec: Dict[str, Any] | None) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    merged.update(get_request_context())
    if isinstance(output_spec, dict):
        merged.update(output_spec)
    return merged


def _configured_model_from(output_spec: Dict[str, Any]) -> Dict[str, Any]:
    configured = output_spec.get("configured_model")
    if not isinstance(configured, dict) or not configured:
        configured = get_configured_model_context()
    return configured if isinstance(configured, dict) else {}


def _record_tier(output_spec: Dict[str, Any], selection: "ModelSelection") -> None:
    """把实际档位写回请求上下文，供 008/计量读取（R-10）。"""

    if not isinstance(output_spec, dict) or not selection.tier:
        return
    output_spec["model_tier"] = selection.tier
    if selection.tier_declared and selection.tier_declared != selection.tier:
        output_spec["model_tier_declared"] = selection.tier_declared


def _trace_model_routed(
    *,
    trace_id: str,
    output_spec: Dict[str, Any],
    selection: "ModelSelection",
    intent: str | None,
    stage: str | None,
    node_id: str | None,
) -> None:
    """R-8：命中档位即发 ``model_routed``；R-14：静态映射命中补 skip 原因。"""

    if not selection.model_config_id and not (isinstance(output_spec, dict) and output_spec):
        return
    payload: Dict[str, Any] = {
        "stage": str(stage or ""),
        "intent": str(intent or ""),
        "node_id": str(node_id or ""),
        "model": str(selection.model or ""),
        "source": str(selection.source or ""),
    }
    if selection.model_config_id:
        payload["model_config_id"] = selection.model_config_id
    if selection.tier:
        payload["tier"] = selection.tier
    else:
        payload["tier"] = ""
        if selection.tier_skipped_reason:
            payload["tier_skipped_reason"] = selection.tier_skipped_reason
    log_trace(trace_id=trace_id, scope="llm.factory", event="model_routed", **payload)


def _tier_routing_fallback(*, output_spec: Dict[str, Any], selection: "ModelSelection", code: str) -> None:
    log_print(
        f"[llm.tier_routing] {code} tier={selection.tier} source={selection.source}",
        flush=True,
    )
    try:
        log_trace(
            trace_id=ensure_trace_id(output_spec or {}),
            scope="llm.factory",
            event="tier_routing_fallback",
            code=code,
            tier=str(selection.tier or ""),
            source=str(selection.source or ""),
        )
    except Exception as exc:  # pragma: no cover - 观测失败不影响选型
        log_print(f"[llm.factory._tier_routing_fallback] suppressed {type(exc).__name__}: {exc}", flush=True)


def get_llm_client(
    *,
    streaming: bool = True,
    model_name: str | None = None,
    intent: str | None = None,
    stage: str | None = None,
    node_id: str | None = None,
    output_spec: Dict[str, Any] | None = None,
    prompt_chars: int | None = None,
    tool_count: int | None = None,
    multi_turn: int | None = None,
) -> BaseLLMClient:
    output_spec = _merge_output_spec(output_spec)
    configured_model = _configured_model_from(output_spec)
    if configured_model:
        return build_llm_client_from_config(
            configured_model,
            streaming=streaming,
            intent=intent,
            stage=stage,
            node_id=node_id,
            output_spec=output_spec,
        )
    settings = get_settings()
    selection = get_model_router().resolve(
        explicit_model=model_name,
        intent=intent,
        stage=stage,
        node_id=node_id,
        output_spec=output_spec or {},
        prompt_chars=prompt_chars,
        tool_count=tool_count,
        multi_turn=multi_turn,
    )
    if selection.model_config_id:
        # 同步入口无法 await 031 的模型配置解析：如实回退到静态链并告警，由
        # 异步入口 ``aget_llm_client`` 承担分层生效路径（spec R-12）。
        _tier_routing_fallback(output_spec=output_spec, selection=selection, code="model_config_missing")
        selection = get_model_router().resolve(
            explicit_model=model_name,
            intent=intent,
            stage=stage,
            node_id=node_id,
            output_spec=output_spec or {},
            prompt_chars=prompt_chars,
            tool_count=tool_count,
            multi_turn=multi_turn,
            skip_tiering=True,
        )
    _record_tier(output_spec, selection)
    trace_id = ensure_trace_id(output_spec or {})
    selected_model = selection.model
    _trace_model_routed(
        trace_id=trace_id,
        output_spec=output_spec,
        selection=selection,
        intent=intent,
        stage=stage,
        node_id=node_id,
    )

    if settings.USE_AZURE:
        _validate_api_key_ascii(api_key=settings.OPENAI_API_KEY, provider="Azure OpenAI")
        azure_deployment, route_key = _resolve_azure_deployment(
            selected_model=selected_model,
            intent=intent,
            stage=stage,
        )
        
        if isinstance(output_spec, dict) and output_spec:
            log_trace(
                trace_id=trace_id,
                scope="llm.factory",
                event="azure_deployment_resolved",
                route_key=route_key,
                deployment=azure_deployment,
            )
            
        client = AzureOpenAIClient(
            api_key=settings.OPENAI_API_KEY,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_version=settings.AZURE_OPENAI_API_VERSION,
            azure_deployment=azure_deployment,
            streaming=streaming,
        )
        return InstrumentedLLMClient(
            client,
            model_name=selected_model,
            model_id=azure_deployment or selected_model,
            stage=stage,
            intent=intent,
            node_id=node_id,
            output_spec=output_spec,
        )
        
    if settings.USE_QWEN:
        _validate_api_key_ascii(api_key=(settings.QWEN_API_KEY or settings.OPENAI_API_KEY), provider="Qwen")
        client = QwenClient(
            api_key=settings.QWEN_API_KEY or settings.OPENAI_API_KEY,
            base_url=settings.QWEN_BASE_URL,
            model=settings.QWEN_MODEL,
            streaming=streaming,
            structured_output_mode="prompt_json",
        )
        return InstrumentedLLMClient(
            client,
            model_name=selected_model or settings.QWEN_MODEL,
            model_id=settings.QWEN_MODEL,
            stage=stage,
            intent=intent,
            node_id=node_id,
            output_spec=output_spec,
        )
        
    _validate_api_key_ascii(api_key=settings.OPENAI_API_KEY, provider="OpenAI")
    base_url = str(settings.OPENAI_BASE_URL or "").strip()
    structured_output_mode = (
        "native"
        if not base_url or "openai.com" in base_url.lower()
        else infer_structured_output_mode(
            provider_type="openai_compatible",
            provider_name=base_url,
            model_name=selected_model,
        )
    )
    client = DefaultOpenAIClient(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        model=selected_model,
        streaming=streaming,
        structured_output_mode=structured_output_mode,
    )
    return InstrumentedLLMClient(
        client,
        model_name=selected_model,
        model_id=selected_model,
        stage=stage,
        intent=intent,
        node_id=node_id,
        output_spec=output_spec,
    )


async def aget_llm_client(
    *,
    streaming: bool = True,
    model_name: str | None = None,
    intent: str | None = None,
    stage: str | None = None,
    node_id: str | None = None,
    output_spec: Dict[str, Any] | None = None,
    prompt_chars: int | None = None,
    tool_count: int | None = None,
    multi_turn: int | None = None,
) -> BaseLLMClient:
    """分层路由的异步入口（040）。

    与同步 ``get_llm_client`` 的差别只有一处：档位命中后可以 ``await`` 031 的模型
    实例解析（``get_llm_client_by_model_id``，自带 007 韧性包装与计量），因此是
    tier 真正生效的路径。异步调用点应优先使用它；同步调用点保持既有行为（分层
    未命中即回退静态链）。
    """

    output_spec = _merge_output_spec(output_spec)
    configured_model = _configured_model_from(output_spec)
    if configured_model:
        return build_llm_client_from_config(
            configured_model,
            streaming=streaming,
            intent=intent,
            stage=stage,
            node_id=node_id,
            output_spec=output_spec,
        )

    selection = get_model_router().resolve(
        explicit_model=model_name,
        intent=intent,
        stage=stage,
        node_id=node_id,
        output_spec=output_spec or {},
        prompt_chars=prompt_chars,
        tool_count=tool_count,
        multi_turn=multi_turn,
    )

    if selection.model_config_id:
        from app.llm.configured_models import ModelConfigError, get_llm_client_by_model_id

        tenant_id = str(
            output_spec.get("tenant_id") or output_spec.get("tenantId") or ""
        ).strip()
        try:
            client = await get_llm_client_by_model_id(
                selection.model_config_id,
                tenant_id=tenant_id,
                streaming=streaming,
                intent=intent,
                stage=stage,
                node_id=node_id,
                output_spec=output_spec,
            )
        except ModelConfigError as exc:
            _tier_routing_fallback(output_spec=output_spec, selection=selection, code="model_config_missing")
            log_print(
                f"[llm.tier_routing] model_config_missing detail={type(exc).__name__}: {exc}",
                flush=True,
            )
        else:
            _record_tier(output_spec, selection)
            _trace_model_routed(
                trace_id=ensure_trace_id(output_spec or {}),
                output_spec=output_spec,
                selection=selection,
                intent=intent,
                stage=stage,
                node_id=node_id,
            )
            return client

    return get_llm_client(
        streaming=streaming,
        model_name=model_name,
        intent=intent,
        stage=stage,
        node_id=node_id,
        output_spec=output_spec,
        prompt_chars=prompt_chars,
        tool_count=tool_count,
        multi_turn=multi_turn,
    )


def get_request_scoped_llm_client(
    *,
    streaming: bool = True,
    model_name: str | None = None,
    intent: str | None = None,
    stage: str | None = None,
    node_id: str | None = None,
    output_spec: Dict[str, Any] | None = None,
) -> BaseLLMClient:
    """Proxy for long-lived services; resolves the current request model per call."""
    from app.llm.request_scoped_client import RequestScopedLLMClient

    return RequestScopedLLMClient(
        streaming=streaming,
        model_name=model_name,
        intent=intent,
        stage=stage,
        node_id=node_id,
        output_spec=output_spec,
    )


def get_openai_compatible_client(
    *,
    api_key: str,
    base_url: str,
    model_name: str,
    streaming: bool = True,
    intent: str | None = None,
    stage: str | None = None,
    node_id: str | None = None,
    output_spec: Dict[str, Any] | None = None,
) -> BaseLLMClient:
    merged_output_spec: Dict[str, Any] = {}
    merged_output_spec.update(get_request_context())
    if isinstance(output_spec, dict):
        merged_output_spec.update(output_spec)
    _validate_api_key_ascii(api_key=api_key, provider="OpenAI Compatible")
    client = DefaultOpenAIClient(
        api_key=api_key,
        base_url=base_url,
        model=model_name,
        streaming=streaming,
        structured_output_mode=(
            str((merged_output_spec.get("configured_model") or {}).get("structured_output_mode") or "").strip()
            if isinstance(merged_output_spec.get("configured_model"), dict)
            and str((merged_output_spec.get("configured_model") or {}).get("structured_output_mode") or "").strip()
            else infer_structured_output_mode(
                provider_type="openai_compatible",
                model_name=model_name,
                settings=(merged_output_spec.get("configured_model") or {}).get("settings")
                if isinstance(merged_output_spec.get("configured_model"), dict)
                else None,
            )
        ),
    )
    return InstrumentedLLMClient(
        client,
        model_name=model_name,
        model_id=model_name,
        stage=stage,
        intent=intent,
        node_id=node_id,
        output_spec=merged_output_spec,
    )

def supports_json_schema() -> bool:
    # This means "the LLM layer can return a Pydantic-shaped result", not
    # necessarily native OpenAI/Azure response_format support.  Non-native
    # providers are handled by prompt-json fallback inside ainvoke_structured().
    return True
