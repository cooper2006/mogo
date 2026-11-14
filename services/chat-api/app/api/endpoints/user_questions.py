"""Authenticated bridge for DSH's native human-question tool."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.services.end_user_session import resolve_session_user
from app.core.db import get_db
from app.dsh_runtime.application import dsh_runtime_application
from app.dsh_runtime.bindings import KernelBindingRepository
from app.dsh_runtime.turn_cancellation import (
    CancelNotAllowedError,
    assert_run_initiator,
    member_conversation,
)
from app.dsh_runtime.conversation.participants_repository import SessionParticipantsRepository
from app.dsh_runtime.errors import DshRuntimeError
from app.dsh_runtime.conversation.question_answers import record_question_answer


router = APIRouter(prefix="/dsh/conversations", tags=["user-questions"])


class QuestionAnswer(BaseModel):
    id: str = Field(min_length=1)
    selected: list[str] = Field(default_factory=list)
    custom: str | None = None


class QuestionReply(BaseModel):
    answers: list[QuestionAnswer] = Field(min_length=1)


async def _owning_binding(
    conversation_id: str, authorization: str | None, *, allow_no_run: bool = False,
    require_initiator: bool = True,
) -> dict[str, Any]:
    resolved = await resolve_session_user(authorization)
    tenant_id = str(resolved["tenant_id"])
    user_id = str(resolved["user"]["_id"])
    db = get_db()
    try:
        conversation = await member_conversation(
            db, SessionParticipantsRepository(db), conversation_id,
            tenant_id=tenant_id, user_id=user_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="session_not_found") from exc
    except CancelNotAllowedError as exc:
        raise HTTPException(status_code=403, detail="question_owner_required") from exc
    if not conversation.get("active_run"):
        # 无进行中 run：读取侧语义上是「没有待定问题」，返回空列表（200）而非 404，
        # 避免前端轮询（useUserQuestions 每 8 秒重试）持续刷出 404 控制台噪音。
        # 作答（answer）侧仍保持 404：没有 run 时提交答案本就是无效操作。
        if allow_no_run:
            return {}
        raise HTTPException(status_code=404, detail="question_run_not_found")
    # initiator 检查只对「控制/作答」侧（cancel、answer）有意义：取消或提交答案
    # 必须由该 run 的发起者执行。读取（GET pending questions）是成员可见的读操作，
    # 不要求调用者是 run 发起者——运行终结窗口内 initiator 字段缺失/不匹配不应让
    # 成员读到 403（浏览器仍会打印 "Failed to load resource: 403" 噪音）。
    if require_initiator:
        try:
            assert_run_initiator(conversation, conversation_id=conversation_id, user_id=user_id)
        except CancelNotAllowedError as exc:
            raise HTTPException(status_code=403, detail="question_owner_required") from exc
    binding = await KernelBindingRepository(db).current(conversation_id, tenant_id=tenant_id, user_id=user_id)
    if binding is None or binding.get("execution_location") != "server":
        # 读侧宽松：会话成员可见但 kernel 绑定暂不可用（运行终结/迁移窗口），
        # 语义上同样是「没有可读的待定问题」→ 返回 200 空列表，而非 404。
        if not require_initiator:
            return {}
        raise HTTPException(status_code=404, detail="question_session_not_found")
    return {
        **binding, "_tenant_id": tenant_id, "_user_id": user_id,
        "_message_id": str(conversation["active_run"].get("message_id") or ""),
    }


def _question_path(binding: dict[str, Any], suffix: str = "") -> str:
    return (
        f"/v1/runtimes/{binding['runtime_id']}/sessions/"
        f"{binding['kernel_session_id']}/questions{suffix}"
    )


@router.get("/{conversation_id}/questions")
async def pending_questions(
    conversation_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    binding = await _owning_binding(conversation_id, authorization, allow_no_run=True, require_initiator=False)
    # 无进行中 run（allow_no_run 命中）：返回空待定问题列表，而非 404。
    if not binding:
        return {"questions": []}
    try:
        return await dsh_runtime_application.require_transport().request("GET", _question_path(binding))
    except DshRuntimeError as exc:
        raise HTTPException(status_code=503, detail="question_runtime_unavailable") from exc


@router.post("/{conversation_id}/questions/{question_id}/answer")
async def answer_question(
    conversation_id: str,
    question_id: str,
    payload: QuestionReply,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    binding = await _owning_binding(conversation_id, authorization)
    if not question_id or "/" in question_id or len(question_id) > 256:
        raise HTTPException(status_code=400, detail="invalid_question_id")
    transport = dsh_runtime_application.require_transport()
    try:
        pending = await transport.request("GET", _question_path(binding))
        item = next((row for row in pending.get("questions", []) if row.get("id") == question_id), None)
        receipt = await transport.request(
            "POST", _question_path(binding, f"/{question_id}/answer"),
            json=payload.model_dump(exclude_none=True),
        )
    except DshRuntimeError as exc:
        raise HTTPException(status_code=409, detail="question_no_longer_pending") from exc
    if not receipt.get("answered") or not binding["_message_id"]:
        raise HTTPException(status_code=409, detail="question_answer_not_accepted")
    questions = receipt.get("questions") or (item or {}).get("questions")
    if not questions:
        raise HTTPException(status_code=409, detail="question_snapshot_unavailable")
    await record_question_answer(
        get_db(), tenant_id=binding["_tenant_id"], user_id=binding["_user_id"],
        message_id=binding["_message_id"], question_id=question_id,
        questions=questions, answers=receipt.get("answers") or payload.model_dump(exclude_none=True)["answers"],
    )
    return {"answered": True, "questionId": question_id}
