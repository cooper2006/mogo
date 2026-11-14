"""053-plaza-template-distribution：SOP 模板克隆消费侧（T016）契约测试.

验证 chat-api ``store.py`` 的两个克隆消费辅助：

* ``reparse_approver_for_tenant`` —— 050 联动：human_approval 节点审批人按
  克隆者租户重解析（原审批人引用不跨租户携带）；
* ``register_cloned_definition`` —— 克隆副本文档写入 dag_definitions（克隆者
  名下），保持"副本即普通实体"（plan Structure Decision）。

纯逻辑 + fake DB（与 050 ``fixtures/memory_db`` 范式一致），不依赖真实 Mongo。
"""

from __future__ import annotations

import asyncio

import pytest

from app.orchestration import store
from app.orchestration.store import reparse_approver_for_tenant


def test_reparse_approver_for_tenant_human_approval() -> None:
    payload = {"type": "human_approval", "approver": "admin-cross-tenant", "prompt": "批准"}
    result = reparse_approver_for_tenant(payload, tenant_id="tenant-b")
    assert "approver" not in result
    assert result["approver_tenant_id"] == "tenant-b"
    assert result["approver_pending"] is True
    assert result["prompt"] == "批准"


def test_reparse_approver_non_approval_unchanged() -> None:
    payload = {"skill": "s1", "tools": ["t"]}
    result = reparse_approver_for_tenant(payload, tenant_id="tenant-b")
    assert result == payload
    assert result["skill"] == "s1"


def test_reparse_approver_missing_type() -> None:
    payload = {"approver": "x"}
    result = reparse_approver_for_tenant(payload, tenant_id="t")
    assert "approver" in result  # 非 human_approval 不动


class _FakeCollection:
    def __init__(self) -> None:
        self.docs: list[dict] = []

    def _match(self, doc: dict, scope: dict) -> bool:
        return all(doc.get(k) == v for k, v in scope.items())

    async def find_one(self, scope: dict):
        return next((d for d in self.docs if self._match(d, scope)), None)

    async def update_one(self, scope: dict, update: dict, upsert: bool = False):
        doc = next((d for d in self.docs if self._match(d, scope)), None)
        if doc is None:
            if not upsert:
                return type("R", (), {"matched_count": 0})()
            doc = dict(scope)
            doc.update(update.get("$setOnInsert") or {})
            self.docs.append(doc)
        doc.update(update.get("$set") or {})
        return type("R", (), {"matched_count": 1})()


class _FakeDB:
    def __init__(self) -> None:
        self.dag_definitions = _FakeCollection()

    def __getitem__(self, name: str) -> _FakeCollection:
        if name == "dag_definitions":
            return self.dag_definitions
        raise KeyError(name)


def test_register_cloned_definition(monkeypatch) -> None:
    import app.core.db as db_mod

    db = _FakeDB()
    monkeypatch.setattr(db_mod, "get_db", lambda: db)
    document = {
        "orchestration": {"id": "orig_id", "version": "1", "mode": "graph"},
        "nodes": [{"id": "n", "payload": {"skill": "s"}}],
    }
    asyncio.get_event_loop().run_until_complete(
        store.register_cloned_definition(
            orchestration_id="clone_1",
            tenant_id="t1",
            user_id="u1",
            document=document,
            template_ref={"template_id": "tpl_1", "asset_type": "sop_template", "version": 1},
        )
    )
    assert db.dag_definitions.docs
    doc = db.dag_definitions.docs[0]
    assert doc["orchestration_id"] == "clone_1"
    assert doc["tenant_id"] == "t1"
    assert doc["user_id"] == "u1"
    assert doc["template_ref"]["template_id"] == "tpl_1"
    assert doc["document"]["orchestration"]["id"] == "clone_1"
    assert doc["document"]["orchestration"]["template_ref"]["version"] == 1
