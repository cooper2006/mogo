"""032-eval-gate: evaluation executor (chat-api model gateway).

Calls the chat-api **model gateway** endpoint over ``settings.backend_base_url``
using the admin-api service credential (``settings.backend_service_token``).
Retry/backoff resilience lives on the chat-api side (007); admin-api only bounds
its own wait via ``urllib`` timeouts and an overall evaluation deadline.

Only judgement summaries are stored — never the full LLM output (FR-009).
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from typing import Any

from app.core.config import settings

from .gateway_auth import build_generate_request, issue_model_gateway_token
from .judges import aggregate, judge_case
from .models import (
    DEFAULT_LLM_TIMEOUT_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    EvalCaseResult,
    Metrics,
)


class GatewayError(RuntimeError):
    """chat-api gateway call failed (timeout / unavailable / bad payload)."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class EvaluationTimeoutError(RuntimeError):
    """Overall evaluation deadline exceeded (fail-closed)."""


class EvaluationExecutionError(RuntimeError):
    """A case could not be evaluated (no output produced)."""


# ---------------------------------------------------------------------------
# chat-api gateway HTTP call (urllib, in a worker thread — do not block the loop)
# ---------------------------------------------------------------------------


def _call_gateway_blocking(
    prompt: str,
    *,
    tenant_id: str,
    model: str | None = None,
    timeout: float = DEFAULT_LLM_TIMEOUT_SECONDS,
    profile_version: str | None = None,
    model_instance_id: str | None = None,
) -> str:
    """Single blocking HTTP call to the chat-api model gateway.

    The gateway only accepts `Authorization: Bearer <HMAC 令牌>` and a
    `ModelGatewayRequest` body (`extra="forbid"`); the service-token scheme of
    `app/security/service_token.py` is NOT accepted (spec R-12).

    Returns the assembled text output.  Raises ``GatewayError`` on any failure.
    """
    base_url = str(settings.backend_base_url or "http://127.0.0.1:8000").rstrip("/")
    url = f"{base_url}/internal/dsh/model/generate"
    payload, resolved_profile, resolved_instance = build_generate_request(
        prompt=prompt,
        model=model,
        profile_version=profile_version,
        model_instance_id=model_instance_id,
    )
    token = issue_model_gateway_token(  # pragma: allowlist secret
        tenant_id=tenant_id,
        profile_version=resolved_profile,
        model_instance_id=resolved_instance,
    )
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Accept": "application/x-ndjson",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:  # pragma: no cover - defensive
            detail = ""
        raise GatewayError(f"模型网关返回 {exc.code}: {detail or exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GatewayError(f"模型网关不可用或超时：{exc}", retryable=True) from exc

    return _assemble_ndjson(raw)


def _assemble_ndjson(raw: str) -> str:
    """Assemble text from the NDJSON event stream of the model gateway.

    Event contract mirrors ``chat-api/dsh_runtime/model_gateway/service.py``:
    ``{"type":"text-delta","text":...}``, ``{"type":"finish",...}``,
    ``{"type":"error","error":{"code","message","retryable"}}``.  A small
    tolerance set is kept for older gateways emitting ``delta``/``content``.
    """
    text_parts: list[str] = []
    errors: list[str] = []
    finished = False
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        etype = event.get("type")
        if etype in ("text-delta", "delta", "text", "content"):
            # text-delta carries the text directly; delta/content may nest it
            # inside a "delta"/"content" object.
            payload = event.get("text")
            if payload is None and etype != "text-delta":
                nested = event.get("delta") or event.get("content")
                payload = nested.get("content") if isinstance(nested, dict) else nested
            if payload:
                text_parts.append(str(payload))
        elif etype in ("error", "failure"):
            payload = event.get("error") or event.get("message") or event
            message = payload.get("message") if isinstance(payload, dict) else str(payload)
            errors.append(str(message or "gateway error"))
        elif etype in ("done", "complete", "finish"):
            finished = True
    if errors and not text_parts:
        raise GatewayError("模型网关流式返回错误：%s" % "; ".join(errors))
    output = "".join(text_parts).strip()
    if not output and not finished and not errors:
        raise GatewayError("模型网关返回空结果")
    return output


# ---------------------------------------------------------------------------
# Async orchestration (each HTTP call runs in a thread; the overall run is
# bounded by ``timeout_seconds``).
# ---------------------------------------------------------------------------


async def _call_gateway(
    prompt: str,
    *,
    tenant_id: str,
    model: str | None = None,
    timeout: float = DEFAULT_LLM_TIMEOUT_SECONDS,
    retries: int = 2,
) -> str:
    """Call the gateway with a small retry budget for transient failures."""
    last_error: GatewayError | None = None
    for attempt in range(max(1, retries)):
        try:
            return await asyncio.to_thread(
                _call_gateway_blocking, prompt, tenant_id=tenant_id, model=model, timeout=timeout
            )
        except GatewayError as exc:
            last_error = exc
            if not exc.retryable or attempt + 1 >= max(1, retries):
                break
            await asyncio.sleep(min(0.5 * (2 ** attempt), 2.0))
    assert last_error is not None
    raise last_error


def _build_prompt(skill_draft: dict[str, Any], case_input: str) -> str:
    name = str(skill_draft.get("name") or "")
    description = str(skill_draft.get("description") or "")
    scenario = str(skill_draft.get("scenario") or "")
    parts = ["你是一个严格遵循给定技能指令的助手。请直接回答用户提问，不要输出与问题无关的内容。"]
    if name:
        parts.append(f"技能名称：{name}")
    if description:
        parts.append(f"技能说明：{description}")
    if scenario:
        parts.append(f"适用场景：{scenario}")
    parts.append("")
    parts.append("用户提问：")
    parts.append(case_input)
    return "\n".join(parts)


async def run_eval_case(
    *,
    tenant_id: str,
    case: dict[str, Any],
    skill_draft: dict[str, Any],
    model: str | None = None,
    llm_timeout: float = DEFAULT_LLM_TIMEOUT_SECONDS,
    retries: int = 2,
    llm_call=None,
) -> EvalCaseResult:
    """Evaluate a single golden case against the skill draft."""
    from .judges import judge_case as _judge

    started = time.monotonic()
    output = ""
    if llm_call is not None:
        output = await llm_call(_build_prompt(skill_draft, str(case.get("input") or "")))
    else:
        output = await _call_gateway(
            _build_prompt(skill_draft, str(case.get("input") or "")),
            tenant_id=tenant_id,
            model=model,
            timeout=llm_timeout,
            retries=retries,
        )
    result = _judge(case, output)
    result.duration_ms = int((time.monotonic() - started) * 1000)
    return result


async def run_evaluation(
    *,
    tenant_id: str,
    cases: list[dict[str, Any]],
    skill_draft: dict[str, Any],
    model: str | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    llm_timeout: float = DEFAULT_LLM_TIMEOUT_SECONDS,
    retries: int = 2,
    llm_call=None,
) -> tuple[list[EvalCaseResult], Metrics]:
    """Run every golden case and return (case_results, metrics).

    Raises ``EvaluationTimeoutError`` / ``EvaluationExecutionError`` /
    ``GatewayError`` when the run cannot produce a result — the gate treats any
    of these as fail-closed.
    """
    started = time.monotonic()
    loop = asyncio.get_running_loop()

    async def _run() -> list[EvalCaseResult]:
        results: list[EvalCaseResult] = []
        for case in cases:
            if llm_call is None:
                # Re-check the overall deadline before each case.
                elapsed = time.monotonic() - started
                if elapsed >= float(timeout_seconds or DEFAULT_TIMEOUT_SECONDS):
                    raise EvaluationTimeoutError(
                        f"评测整体超时（已用 {elapsed:.0f}s，上限 {timeout_seconds}s）"
                    )
                remaining = float(timeout_seconds or DEFAULT_TIMEOUT_SECONDS) - elapsed
                case_timeout = min(float(llm_timeout or DEFAULT_LLM_TIMEOUT_SECONDS), max(1.0, remaining))
            else:
                case_timeout = float(llm_timeout or DEFAULT_LLM_TIMEOUT_SECONDS)
            try:
                result = await run_eval_case(
                    tenant_id=tenant_id,
                    case=case,
                    skill_draft=skill_draft,
                    model=model,
                    llm_timeout=case_timeout,
                    retries=retries,
                    llm_call=llm_call,
                )
            except GatewayError as exc:
                raise EvaluationExecutionError(f"用例 {case.get('_id') or case.get('id')} 执行失败：{exc}") from exc
            except asyncio.TimeoutError as exc:
                raise EvaluationTimeoutError("评测单用例超时") from exc
            results.append(result)
        return results

    try:
        results = await asyncio.wait_for(_run(), timeout=float(timeout_seconds or DEFAULT_TIMEOUT_SECONDS))
    except asyncio.TimeoutError as exc:
        raise EvaluationTimeoutError(f"评测整体超时（上限 {timeout_seconds}s）") from exc
    return results, Metrics(**aggregate(results))