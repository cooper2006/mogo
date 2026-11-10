"""051 B2 IM 意图路由契约测试（T020 / T025，SC-004）。

覆盖：关键词命中路由 / 默认员工兜底 / 无默认回落 / 多默认 fail-closed /
空关键词忽略 / 大小写与空白归一 / 绑定存储读写（租户隔离）。全部
DB-free 或 fake DB，不触真实 Mongo。
"""

from __future__ import annotations

import pytest

from app.im_gateway.binding_store import BindingStore
from app.im_gateway.router import ChannelRouter
from app.im_gateway.routing import (
    ROUTE_DEFAULT,
    ROUTE_FALLBACK,
    ROUTE_MATCHED,
    ChannelEmployeeBinding,
    RoutingRuleError,
    resolve_employee,
    validate_bindings,
)


def _b(channel="feishu", emp="emp-a", keywords=None, is_default=False):
    return ChannelEmployeeBinding(
        channel=channel, employee_id=emp, keywords=keywords or [], is_default=is_default
    )


# --- 确定性规则求值（SC-004） ---------------------------------------------


def test_route_keyword_match_wins():
    """命中关键词 → 该员工（确定性 100%）。"""
    bindings = [_b(emp="emp-a", keywords=["财务", "报销"]), _b(emp="emp-b", is_default=True)]
    employee, kind = resolve_employee(bindings, "帮我报销发票")
    assert employee == "emp-a"
    assert kind == ROUTE_MATCHED


def test_route_falls_back_to_default():
    """未命中关键词 → 默认员工兜底。"""
    bindings = [_b(emp="emp-a", keywords=["财务"]), _b(emp="emp-b", is_default=True)]
    employee, kind = resolve_employee(bindings, "你好")
    assert employee == "emp-b"
    assert kind == ROUTE_DEFAULT


def test_route_falls_back_when_no_default():
    """无默认员工 → (None, fallback)，调用方回落既有行为（不拒绝消息）。"""
    bindings = [_b(emp="emp-a", keywords=["财务"])]
    employee, kind = resolve_employee(bindings, "你好")
    assert employee is None
    assert kind == ROUTE_FALLBACK


def test_route_empty_bindings_falls_back():
    employee, kind = resolve_employee([], "任何消息")
    assert employee is None
    assert kind == ROUTE_FALLBACK


def test_route_keyword_normalizes_case_and_whitespace():
    """关键词大小写与空白归一（命中不区分大小写）。"""
    bindings = [_b(emp="emp-a", keywords=["  财务 "])]
    employee, _ = resolve_employee(bindings, "关于 FINANCE 的讨论")
    # 'FINANCE' 大小写归一后与 '财务' 无关，不命中；但 '财务' 需在文本中。
    assert employee is None
    employee2, _ = resolve_employee(bindings, "财务报销")
    assert employee2 == "emp-a"


def test_route_multiple_keywords_any_match():
    bindings = [_b(emp="emp-a", keywords=["财务", "报销", "发票"])]
    assert resolve_employee(bindings, "发票抬头")[0] == "emp-a"


def test_route_first_binding_wins_on_multiple_match():
    """多个绑定都命中时，按绑定序首个胜出（确定性）。"""
    bindings = [_b(emp="emp-a", keywords=["财务"]), _b(emp="emp-b", keywords=["财务"])]
    assert resolve_employee(bindings, "财务报销")[0] == "emp-a"


def test_route_ignores_empty_keywords():
    bindings = [_b(emp="emp-a", keywords=[]), _b(emp="emp-b", is_default=True)]
    assert resolve_employee(bindings, "任何")[0] == "emp-b"


# --- 规则校验（fail-closed） ----------------------------------------------


def test_validate_rejects_multiple_defaults_same_channel():
    bindings = [_b(emp="emp-a", is_default=True), _b(emp="emp-b", is_default=True)]
    with pytest.raises(RoutingRuleError, match="more than one default"):
        validate_bindings(bindings)


def test_validate_allows_one_default_per_channel():
    bindings = [_b(channel="feishu", emp="emp-a", is_default=True), _b(channel="dingtalk", emp="emp-b", is_default=True)]
    validate_bindings(bindings)


def test_binding_requires_channel_and_employee():
    with pytest.raises(RoutingRuleError, match="channel"):
        ChannelEmployeeBinding(channel="", employee_id="emp-a")
    with pytest.raises(RoutingRuleError, match="employee_id"):
        ChannelEmployeeBinding(channel="feishu", employee_id="")


def test_channel_router_resolve_employee_proxy():
    """ChannelRouter 暴露 DB-free 路由（代理）。"""
    router = ChannelRouter()
    bindings = [_b(emp="emp-a", keywords=["财务"]), _b(emp="emp-b", is_default=True)]
    assert router.resolve_employee(bindings, "财务问题")[0] == "emp-a"
    assert router.resolve_employee(bindings, "随便")[0] == "emp-b"
    router.validate_bindings(bindings)


# --- 绑定存储（租户隔离） -------------------------------------------------


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length=None):
        return self._docs[:length] if length else list(self._docs)


class _FakeCol:
    def __init__(self):
        self.docs = []

    async def update_one(self, scope, update, upsert=False):
        for d in self.docs:
            if all(d.get(k) == v for k, v in scope.items()):
                d.update(update.get("$set") or {})
                return type("R", (), {"matched_count": 1})()
        if upsert:
            row = dict(scope)
            row.update(update.get("$set") or {})
            self.docs.append(row)

    def find(self, scope, projection=None):
        return _FakeCursor([d for d in self.docs if all(d.get(k) == v for k, v in scope.items())])

    async def delete_one(self, scope):
        for i, d in enumerate(self.docs):
            if all(d.get(k) == v for k, v in scope.items()):
                self.docs.pop(i)
                return type("R", (), {"deleted_count": 1})()
        return type("R", (), {"deleted_count": 0})


class _FakeDB:
    def __init__(self):
        self._cols = {}

    def __getitem__(self, name):
        return self._cols.setdefault(name, _FakeCol())


async def test_binding_store_roundtrip_and_tenant_isolated():
    db = _FakeDB()
    store = BindingStore(db)
    binding = _b(emp="emp-a", keywords=["财务"], is_default=True)
    await store.save_binding(binding)
    rows = await store.list_bindings("default", "feishu")
    assert len(rows) == 1
    assert rows[0].employee_id == "emp-a"
    assert rows[0].is_default is True
    assert rows[0].keywords == ["财务"]
    # 其他租户读不到（隔离）。
    other = await store.list_bindings("other", "feishu")
    assert other == []
    # 删除。
    assert await store.delete_binding("default", "feishu", "emp-a") is True
    assert await store.list_bindings("default", "feishu") == []
