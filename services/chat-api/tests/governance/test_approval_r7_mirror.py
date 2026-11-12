"""056 R-7 — 迁移期旁路双写 / 影子镜像 / 统一待办回归。

覆盖：
* 开关默认关闭 → mirror_issue/mirror_decision 零写入（零副作用，可随时回退）
* 开关开启 → 三来源（tool/portal/sop）签发 + 决策闭环，统一待办可见
* 影子票据 ``token_hash=""`` 不可被 Kernel.decide 消费（不会双重放行）
* 旁路抛异常 → 适配器吞掉（fail-open 降级，不影响旧状态机）
"""
from __future__ import annotations

import importlib.util
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_SERVICE_ROOT = str(Path(__file__).resolve().parents[2])
if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ak = _load("ak_r7", str(Path(_SERVICE_ROOT) / "app/common/approval_kernel.py"))
mirror = _load("am_r7", str(Path(_SERVICE_ROOT) / "app/common/approval_mirror.py"))

FIXED_NOW = datetime(2026, 11, 12, 20, 0, 0, tzinfo=timezone.utc)


class _Result:
    def __init__(self, modified_count=0, inserted_id=""):
        self.modified_count = modified_count
        self.inserted_id = inserted_id


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    async def to_list(self, length=None):
        rows = [dict(r) for r in self._rows]
        return rows[:length] if length else rows


def _matches(doc, query):
    for k, cond in query.items():
        v = doc.get(k)
        if isinstance(cond, dict):
            if "$in" in cond and v not in cond["$in"]:
                return False
            if "$lt" in cond and not (v is not None and v < cond["$lt"]):
                return False
        elif v != cond:
            return False
    return True


class FakeCollection:
    def __init__(self, fail_writes=False):
        self.docs = {}
        self.fail_writes = fail_writes

    async def insert_one(self, doc):
        if self.fail_writes:
            raise RuntimeError("simulated mirror storage outage")
        row = dict(doc)
        row.setdefault("_id", uuid.uuid4().hex)
        self.docs[row["_id"]] = row
        return _Result(inserted_id=row["_id"])

    async def find_one(self, query):
        for r in self.docs.values():
            if _matches(r, query):
                return dict(r)
        return None

    def find(self, query):
        return _Cursor([r for r in self.docs.values() if _matches(r, query)])

    async def update_one(self, flt, update):
        for _id, row in self.docs.items():
            if not _matches(row, flt):
                continue
            for k, v in (update.get("$set") or {}).items():
                row[k] = v
            for k, v in (update.get("$inc") or {}).items():
                row[k] = int(row.get(k) or 0) + v
            self.docs[_id] = row
            return _Result(modified_count=1)
        return _Result(modified_count=0)


class FakeDB:
    def __init__(self, fail_writes=False):
        self._c = {}
        self.fail_writes = fail_writes

    def __getitem__(self, name):
        return self._c.setdefault(name, FakeCollection(self.fail_writes))


@pytest.fixture
def env(monkeypatch):
    db = FakeDB()
    # 适配器通过 app.core.db.get_db / app.common.* 惰性导入；这里直接注入到模块全局
    import types

    core_db = types.ModuleType("app.core.db")
    core_db.get_db = lambda: db
    core_pkg = types.ModuleType("app.core")
    core_pkg.db = core_db
    common_pkg = types.ModuleType("app.common")
    common_pkg.__path__ = []
    app_pkg = types.ModuleType("app")
    app_pkg.__path__ = []
    monkeypatch.setitem(sys.modules, "app", app_pkg)
    monkeypatch.setitem(sys.modules, "app.core", core_pkg)
    monkeypatch.setitem(sys.modules, "app.core.db", core_db)
    monkeypatch.setitem(sys.modules, "app.common", common_pkg)
    monkeypatch.setitem(sys.modules, "app.common.approval_kernel", ak)
    monkeypatch.setitem(sys.modules, "app.common.shared_constants",
                        _load("sc_r7", str(Path(_SERVICE_ROOT) / "app/common/shared_constants.py")))
    monkeypatch.delenv("APPROVAL_KERNEL_ENABLED", raising=False)
    monkeypatch.delenv("MOGO_FLAG_APPROVAL_KERNEL_ENABLED", raising=False)
    return types.SimpleNamespace(db=db)


def _tickets(env):
    return env.db[ak.TICKETS_COLLECTION]


def _events(env):
    return env.db[ak.GATE_EVENTS_COLLECTION]


# ── 开关语义 ─────────────────────────────────────────────────────────
def test_flag_defaults_to_false(env):
    assert mirror.approval_kernel_enabled() is False


def test_flag_env_variants(monkeypatch, env):
    for val in ("1", "true", "YES", "on"):
        monkeypatch.setenv("APPROVAL_KERNEL_ENABLED", val)
        assert mirror.approval_kernel_enabled() is True
    monkeypatch.setenv("APPROVAL_KERNEL_ENABLED", "false")
    assert mirror.approval_kernel_enabled() is False
    monkeypatch.delenv("APPROVAL_KERNEL_ENABLED")
    monkeypatch.setenv("MOGO_FLAG_APPROVAL_KERNEL_ENABLED", "true")
    assert mirror.approval_kernel_enabled() is True


@pytest.mark.asyncio
async def test_switched_off_has_zero_writes(env):
    await mirror.mirror_issue(
        source="tool", source_id="a-1", tenant_id="t-1",
        actor_id="u-1", approver_id="", deadline=FIXED_NOW + timedelta(minutes=5),
    )
    await mirror.mirror_decision(
        source="tool", source_id="a-1", tenant_id="t-1", actor_id="approver", approved=True,
    )
    assert _tickets(env).docs == {}
    assert _events(env).docs == {}


# ── 三来源镜像闭环 ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_three_sources_issue_then_decide(env, monkeypatch):
    monkeypatch.setenv("APPROVAL_KERNEL_ENABLED", "true")
    cases = [
        ("tool", "tool-1", "t-1", "approver-1", True),
        ("portal", "portal-1", "t-1", "approver-2", False),
        ("sop", "run-1:node-a", "t-1", "approver-3", True),
    ]
    for source, sid, tenant, approver, _ in cases:
        await mirror.mirror_issue(
            source=source, source_id=sid, tenant_id=tenant,
            actor_id="requester", approver_id=approver,
            deadline=FIXED_NOW + timedelta(minutes=5),
        )

    kernel = ak.ApprovalKernel(db=env.db, audit_db=env.db, clock=lambda: FIXED_NOW)
    todos = await kernel.list_todos(tenant_id="t-1", approver_id="")  # 全量按 tenant
    assert len(todos) == 3
    assert {t.source_type for t in todos} == {"tool", "portal", "sop"}

    for source, sid, tenant, approver, approved in cases:
        await mirror.mirror_decision(
            source=source, source_id=sid, tenant_id=tenant,
            actor_id=approver, approved=approved,
        )

    remaining = await kernel.list_todos(tenant_id="t-1", approver_id="")
    assert remaining == []  # 三来源都推进到终态
    all_rows = await _tickets(env).find({}).to_list()
    assert {r["state"] for r in all_rows} == {"approved", "denied"}
    # 审计：3 条 issued + 3 条 decided/denied
    events = await _events(env).find({}).to_list()
    assert len(events) == 6
    assert {e["tool"].split(".")[1] for e in events} == {"tool", "portal", "sop"}


@pytest.mark.asyncio
async def test_shadow_ticket_cannot_be_consumed_by_decide(env, monkeypatch):
    """影子票据 token_hash 为空，Kernel.decide 找不到它 → 不会形成双重放行。"""
    monkeypatch.setenv("APPROVAL_KERNEL_ENABLED", "true")
    await mirror.mirror_issue(
        source="tool", source_id="a-1", tenant_id="t-1", actor_id="u-1",
        approver_id="approver-1", deadline=FIXED_NOW + timedelta(minutes=5),
    )
    kernel = ak.ApprovalKernel(db=env.db, audit_db=env.db, clock=lambda: FIXED_NOW)
    with pytest.raises(ak.ApprovalNotFoundError):
        await kernel.decide(
            source=ak.ApprovalSource.TOOL, source_id="a-1", tenant_id="t-1",
            token="anything", actor_id="approver-1", approved=True,
        )


@pytest.mark.asyncio
async def test_mirror_failure_is_fail_open(env, monkeypatch, caplog):
    """旁路存储故障必须被吞掉，不能向旧状态机抛异常。"""
    monkeypatch.setenv("APPROVAL_KERNEL_ENABLED", "true")
    env.db.fail_writes = True
    for coll in env.db._c.values():
        coll.fail_writes = True
    with caplog.at_level("WARNING"):
        await mirror.mirror_issue(
            source="sop", source_id="r-1:n-1", tenant_id="t-1", actor_id="u-1",
            approver_id="ap-1", deadline=FIXED_NOW + timedelta(minutes=5),
        )
        await mirror.mirror_decision(
            source="sop", source_id="r-1:n-1", tenant_id="t-1",
            actor_id="ap-1", approved=True,
        )  # 即使找不到影子票也不抛
    assert "mirror_issue_failed" in caplog.text


@pytest.mark.asyncio
async def test_decision_without_shadow_ticket_is_silent(env, monkeypatch):
    """签发时开关未开、决策时才开：静默跳过，不产生脏票据。"""
    monkeypatch.setenv("APPROVAL_KERNEL_ENABLED", "true")
    kernel = ak.ApprovalKernel(db=env.db, audit_db=env.db, clock=lambda: FIXED_NOW)
    assert await kernel.mirror_decision(
        source=ak.ApprovalSource.TOOL, source_id="ghost", tenant_id="t-1",
        actor_id="ap", approved=True,
    ) is False
    assert _tickets(env).docs == {}
    assert _events(env).docs == {}
