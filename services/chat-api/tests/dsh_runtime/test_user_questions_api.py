from __future__ import annotations

import asyncio
from bson import ObjectId
from fastapi import HTTPException
import pytest

from app.api.endpoints import user_questions as endpoint


class _Transport:
    def __init__(self) -> None:
        self.calls = []

    async def request(self, method, path, *, json=None):
        self.calls.append((method, path, json))
        return {"questions": [{"id": "call", "questions": [{"id": "q", "question": "Which?"}]}]} if method == "GET" else {"answered": True}


def test_question_bridge_uses_current_binding_and_structured_answers(monkeypatch):
    user_id = str(ObjectId())
    conversation_id = str(ObjectId())
    transport = _Transport()

    async def identity(_authorization):
        return {"tenant_id": "tenant", "user": {"_id": ObjectId(user_id)}}

    async def conversation(_db, _participants, _conversation_id, **_kwargs):
        return {"active_run": {"initiator_user_id": user_id, "message_id": "assistant-turn"}}

    class Bindings:
        def __init__(self, _db):
            pass

        async def current(self, *_args, **_kwargs):
            return {"execution_location": "server", "runtime_id": "runtime", "kernel_session_id": "kernel"}

    monkeypatch.setattr(endpoint, "resolve_session_user", identity)
    monkeypatch.setattr(endpoint, "member_conversation", conversation)
    monkeypatch.setattr(endpoint, "get_db", lambda: object())
    monkeypatch.setattr(endpoint, "SessionParticipantsRepository", lambda _db: object())
    monkeypatch.setattr(endpoint, "KernelBindingRepository", Bindings)
    monkeypatch.setattr(endpoint.dsh_runtime_application, "require_transport", lambda: transport)
    recorded_calls = []
    async def recorded(*_args, **kwargs):
        recorded_calls.append(kwargs)
        return {}
    monkeypatch.setattr(endpoint, "record_question_answer", recorded)

    assert asyncio.run(endpoint.pending_questions(conversation_id, "Bearer token")) == {"questions": [{"id": "call", "questions": [{"id": "q", "question": "Which?"}]}]}
    reply = endpoint.QuestionReply(answers=[endpoint.QuestionAnswer(id="q", selected=["A"])])
    assert asyncio.run(endpoint.answer_question(conversation_id, "call", reply, "Bearer token")) == {"answered": True, "questionId": "call"}
    assert recorded_calls[0]["questions"] == [{"id": "q", "question": "Which?"}]
    assert recorded_calls[0]["answers"] == [{"id": "q", "selected": ["A"]}]
    assert transport.calls == [
        ("GET", "/v1/runtimes/runtime/sessions/kernel/questions", None),
        ("GET", "/v1/runtimes/runtime/sessions/kernel/questions", None),
        ("POST", "/v1/runtimes/runtime/sessions/kernel/questions/call/answer", {"answers": [{"id": "q", "selected": ["A"]}]}),
    ]


def test_other_shared_member_cannot_answer(monkeypatch):
    async def identity(_authorization):
        return {"tenant_id": "tenant", "user": {"_id": ObjectId()}}

    async def conversation(_db, _participants, _conversation_id, **_kwargs):
        return {"active_run": {"initiator_user_id": "someone-else"}}

    class NoBinding:
        def __init__(self, _db):
            pass

        async def current(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(endpoint, "resolve_session_user", identity)
    monkeypatch.setattr(endpoint, "member_conversation", conversation)
    monkeypatch.setattr(endpoint, "get_db", lambda: object())
    monkeypatch.setattr(endpoint, "SessionParticipantsRepository", lambda _db: object())
    monkeypatch.setattr(endpoint, "KernelBindingRepository", NoBinding)
    # 读侧宽松（7630ef99）：GET pending questions 是成员可见的读操作，不要求
    # 调用者是 run 发起者；kernel 绑定不可用时返回 200 空列表而不是 403/404，
    # 避免浏览器轮询刷噪音。控制/作答侧的 403 语义由 test_answer_requires_initiator 覆盖。
    assert asyncio.run(endpoint.pending_questions(str(ObjectId()), "Bearer token")) == {"questions": []}


def test_answer_requires_initiator(monkeypatch):
    """作答（POST）侧仍要求 run 发起者：非发起者提交答案必须 403。"""
    async def identity(_authorization):
        return {"tenant_id": "tenant", "user": {"_id": ObjectId()}}

    async def conversation(_db, _participants, _conversation_id, **_kwargs):
        return {"active_run": {"initiator_user_id": "someone-else", "message_id": "assistant-turn"}}

    class Bindings:
        def __init__(self, _db):
            pass

        async def current(self, *_args, **_kwargs):
            return {"execution_location": "server", "runtime_id": "runtime", "kernel_session_id": "kernel"}

    monkeypatch.setattr(endpoint, "resolve_session_user", identity)
    monkeypatch.setattr(endpoint, "member_conversation", conversation)
    monkeypatch.setattr(endpoint, "get_db", lambda: object())
    monkeypatch.setattr(endpoint, "SessionParticipantsRepository", lambda _db: object())
    monkeypatch.setattr(endpoint, "KernelBindingRepository", Bindings)
    reply = endpoint.QuestionReply(answers=[endpoint.QuestionAnswer(id="q", selected=["A"])])
    with pytest.raises(HTTPException) as error:
        asyncio.run(endpoint.answer_question(str(ObjectId()), "q", reply, "Bearer token"))
    assert error.value.status_code == 403


def test_completed_run_has_no_answerable_question(monkeypatch):
    async def identity(_authorization):
        return {"tenant_id": "tenant", "user": {"_id": ObjectId()}}

    async def conversation(_db, _participants, _conversation_id, **_kwargs):
        return {}

    monkeypatch.setattr(endpoint, "resolve_session_user", identity)
    monkeypatch.setattr(endpoint, "member_conversation", conversation)
    monkeypatch.setattr(endpoint, "get_db", lambda: object())
    monkeypatch.setattr(endpoint, "SessionParticipantsRepository", lambda _db: object())
    # 读侧宽松（af3794af）：无进行中 run 时 GET 返回 200 空列表；404 只保留在
    # 作答侧（没有 run 时提交答案本就是无效操作）。
    assert asyncio.run(endpoint.pending_questions(str(ObjectId()), "Bearer token")) == {"questions": []}


def test_answer_without_run_is_rejected(monkeypatch):
    """作答侧（POST）无 run 时仍返回 404。"""
    async def identity(_authorization):
        return {"tenant_id": "tenant", "user": {"_id": ObjectId()}}

    async def conversation(_db, _participants, _conversation_id, **_kwargs):
        return {}

    monkeypatch.setattr(endpoint, "resolve_session_user", identity)
    monkeypatch.setattr(endpoint, "member_conversation", conversation)
    monkeypatch.setattr(endpoint, "get_db", lambda: object())
    monkeypatch.setattr(endpoint, "SessionParticipantsRepository", lambda _db: object())
    reply = endpoint.QuestionReply(answers=[endpoint.QuestionAnswer(id="q", selected=["A"])])
    with pytest.raises(HTTPException) as error:
        asyncio.run(endpoint.answer_question(str(ObjectId()), "q", reply, "Bearer token"))
    assert error.value.status_code == 404
