"""051 T021：员工级开放 API Key。

覆盖（``specs/051-digital-employee-profile/tasks.md`` T021 / FR-009）：

* create_key：明文仅返回一次，库中只存 sha256 哈希 + 前缀（明文不可回读）；
* resolve_key：有效 Key → employee principal；错误 / 失效 / 员工停用 → None；
* revoke_key：撤销后不可解析；幂等（已撤销返回现状）；
* scope 判定：read / session / read+session（OQ-3 范围，不含档案修改）；
* 跨租户 / 枚举：失效原因不区分（防侧信道）。

用内存假 DB（同 ``tests/employees/test_employee_b1.py`` 风格）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.employees.api_keys import (
    DEFAULT_KEY_SCOPE,
    KEY_PREFIX_LIVE,
    EmployeeApiKeyRepository,
    generate_key_plaintext,
    hash_key,
    key_prefix_of,
    scope_allows,
)
from app.employees.api_key_auth import (
    EmployeeApiKeyPrincipal,
    _principal_from_resolved,
    require_scope,
    resolve_employee_key,
)

TENANT = "tenant-a"


# ---------------------------------------------------------------------------
# 内存假 Mongo（本测试用到的操作）
# ---------------------------------------------------------------------------
_MISSING = object()


def _matches(doc: dict, filt: dict) -> bool:
    for key, cond in filt.items():
        if key == "$or":
            if not any(_matches(doc, sub) for sub in cond):
                return False
            continue
        if key == "$and":
            if not all(_matches(doc, sub) for sub in cond):
                return False
            continue
        value = doc.get(key, _MISSING)
        if isinstance(cond, dict):
            for op, arg in cond.items():
                if op == "$in":
                    if value is _MISSING or value not in arg:
                        return False
                elif op == "$exists":
                    if bool(arg) != (value is not _MISSING):
                        return False
                elif op == "$ne":
                    if value is not _MISSING and value == arg:
                        return False
                else:  # pragma: no cover
                    raise AssertionError(op)
        elif value is _MISSING or value != cond:
            return False
    return True


class FakeCollection:
    def __init__(self) -> None:
        self.docs: list[dict] = []

    async def insert_one(self, doc: dict) -> SimpleNamespace:
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=doc.get("_id"))

    async def find_one(self, filt: dict, projection: dict | None = None) -> dict | None:
        for doc in self.docs:
            if _matches(doc, filt):
                out = dict(doc)
                if projection:
                    out = {k: v for k, v in out.items() if k in projection}
                return out
        return None

    def find(self, filt: dict) -> "_FakeCursor":
        return _FakeCursor([dict(d) for d in self.docs if _matches(d, filt)])

    async def update_one(self, filt: dict, update: dict, upsert: bool = False) -> SimpleNamespace:
        set_doc = dict(update.get("$set") or {})
        for doc in self.docs:
            if _matches(doc, filt):
                doc.update(set_doc)
                return SimpleNamespace(modified_count=1, matched_count=1)
        if upsert:
            new_doc = dict(set_doc)
            new_doc.update({k: v for k, v in filt.items() if not isinstance(v, dict) and k not in ("$or", "$and")})
            self.docs.append(new_doc)
            return SimpleNamespace(modified_count=0, matched_count=0, upserted_id=new_doc.get("_id"))
        return SimpleNamespace(modified_count=0, matched_count=0)

    async def create_index(self, *args, **kwargs) -> None:  # noqa: ARG002
        return None


class _FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    async def to_list(self, length: int | None = None) -> list[dict]:
        return self._docs[:length] if length else list(self._docs)

    def sort(self, *args, **kwargs) -> "_FakeCursor":  # noqa: ARG002
        return self


class FakeDB:
    def __init__(self) -> None:
        self._collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self._collections.setdefault(name, FakeCollection())

    def __getattr__(self, name: str) -> FakeCollection:
        return self.__getitem__(name)


def _make_repo(db: FakeDB) -> EmployeeApiKeyRepository:
    return EmployeeApiKeyRepository(db=db)


def _seed_employee(db: FakeDB, employee_id: str = "emp-1", status: str = "active") -> None:
    db["employees"].docs.append({
        "_id": employee_id,
        "tenant_id": TENANT,
        "name": "财务员工",
        "status": status,
        "creator_id": "admin",
        "deleted_at": None,
    })


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------

def test_generate_key_plaintext_shape():
    key = generate_key_plaintext()
    assert key.startswith(KEY_PREFIX_LIVE)
    # 32 字节 token_urlsafe → 43 字符；加前缀 ek_live_ 后 51。
    assert len(key) == len(KEY_PREFIX_LIVE) + 43


def test_key_hash_is_sha256():
    key = generate_key_plaintext()
    digest = hash_key(key)
    assert len(digest) == 64  # sha256 hex
    assert digest != key  # 不回读明文


def test_key_prefix_of():
    key = generate_key_plaintext()
    prefix = key_prefix_of(key)
    assert len(prefix) == 8
    assert key[len(KEY_PREFIX_LIVE):][:8] == prefix


def test_scope_allows_matrix():
    assert scope_allows("read", "read") is True
    assert scope_allows("read", "session") is False
    assert scope_allows("session", "session") is True
    assert scope_allows("session", "read") is False
    assert scope_allows("read+session", "read", "session") is True
    assert scope_allows(None, "read", "session") is True  # 默认 read+session
    assert scope_allows("read+session", "read") is True
    assert scope_allows("read", "read", "session") is False


def test_scope_allows_rejects_invalid():
    # 非法 scope 宽容为 False（不抛错，避免热路径崩溃）。
    assert scope_allows("admin", "read") is False


# ---------------------------------------------------------------------------
# repository：create / resolve / revoke
# ---------------------------------------------------------------------------

async def test_create_key_returns_plaintext_once_and_stores_hash():
    db = FakeDB()
    _seed_employee(db)
    repo = _make_repo(db)
    row = await repo.create_key(tenant_id=TENANT, employee_id="emp-1", actor="admin", label="CI")
    assert row["plaintext"].startswith(KEY_PREFIX_LIVE)
    assert row["scope"] == DEFAULT_KEY_SCOPE
    assert row["status"] == "active"
    # 库中仅哈希，无明文。
    stored = db["employee_api_keys"].docs[0]
    assert stored["key_hash"] == hash_key(row["plaintext"])
    assert "plaintext" not in stored
    assert stored["key_prefix"] == key_prefix_of(row["plaintext"])
    assert stored["label"] == "CI"


async def test_resolve_key_ok_returns_employee():
    db = FakeDB()
    _seed_employee(db)
    repo = _make_repo(db)
    row = await repo.create_key(tenant_id=TENANT, employee_id="emp-1", actor="admin")
    resolved = await repo.resolve_key(tenant_id=TENANT, plaintext=row["plaintext"])
    assert resolved is not None
    assert resolved["key"]["_id"] == row["_id"]
    assert resolved["employee"]["_id"] == "emp-1"
    assert resolved["employee"]["name"] == "财务员工"


async def test_resolve_key_empty_tenant_uses_key_tenant():
    """调用方未知租户（tenant_id="") 时按 Key 文档自带租户解析。"""
    db = FakeDB()
    _seed_employee(db)
    repo = _make_repo(db)
    row = await repo.create_key(tenant_id=TENANT, employee_id="emp-1", actor="admin")
    resolved = await repo.resolve_key(tenant_id="", plaintext=row["plaintext"])
    assert resolved is not None
    assert resolved["key"]["tenant_id"] == TENANT
    assert resolved["employee"]["tenant_id"] == TENANT


async def test_resolve_key_wrong_plaintext_none():
    db = FakeDB()
    _seed_employee(db)
    repo = _make_repo(db)
    await repo.create_key(tenant_id=TENANT, employee_id="emp-1", actor="admin")
    resolved = await repo.resolve_key(tenant_id=TENANT, plaintext=generate_key_plaintext())
    assert resolved is None


async def test_resolve_key_after_revoke_none():
    db = FakeDB()
    _seed_employee(db)
    repo = _make_repo(db)
    row = await repo.create_key(tenant_id=TENANT, employee_id="emp-1", actor="admin")
    revoked = await repo.revoke_key(tenant_id=TENANT, key_id=row["_id"], actor="admin")
    assert revoked["status"] == "revoked"
    resolved = await repo.resolve_key(tenant_id=TENANT, plaintext=row["plaintext"])
    assert resolved is None


async def test_revoke_idempotent_returns_current():
    db = FakeDB()
    _seed_employee(db)
    repo = _make_repo(db)
    row = await repo.create_key(tenant_id=TENANT, employee_id="emp-1", actor="admin")
    await repo.revoke_key(tenant_id=TENANT, key_id=row["_id"], actor="admin")
    # 再次撤销（已 revoked）→ 返回现状而非报错。
    again = await repo.revoke_key(tenant_id=TENANT, key_id=row["_id"], actor="admin")
    assert again is not None
    assert again["status"] == "revoked"


async def test_resolve_key_disabled_employee_none():
    db = FakeDB()
    _seed_employee(db, status="disabled")
    repo = _make_repo(db)
    row = await repo.create_key(tenant_id=TENANT, employee_id="emp-1", actor="admin")
    resolved = await repo.resolve_key(tenant_id=TENANT, plaintext=row["plaintext"])
    assert resolved is None


async def test_resolve_key_deleted_employee_none():
    db = FakeDB()
    _seed_employee(db, status="archived")
    db["employees"].docs[0]["deleted_at"] = datetime.now(timezone.utc)
    repo = _make_repo(db)
    row = await repo.create_key(tenant_id=TENANT, employee_id="emp-1", actor="admin")
    resolved = await repo.resolve_key(tenant_id=TENANT, plaintext=row["plaintext"])
    assert resolved is None


async def test_resolve_key_expired_none():
    db = FakeDB()
    _seed_employee(db)
    repo = _make_repo(db)
    row = await repo.create_key(tenant_id=TENANT, employee_id="emp-1", actor="admin", ttl_days=1)
    # 手动把过期时刻拨到过去。
    db["employee_api_keys"].docs[0]["expires_at"] = datetime.now(timezone.utc) - timedelta(days=2)
    resolved = await repo.resolve_key(tenant_id=TENANT, plaintext=row["plaintext"])
    assert resolved is None


async def test_serialize_never_returns_plaintext_or_hash():
    db = FakeDB()
    _seed_employee(db)
    repo = _make_repo(db)
    row = await repo.create_key(tenant_id=TENANT, employee_id="emp-1", actor="admin", label="CI")
    view = EmployeeApiKeyRepository.serialize(row)
    assert view["keyId"] == row["_id"]
    assert view["label"] == "CI"
    assert view["scope"] == DEFAULT_KEY_SCOPE
    assert view["keyPrefix"] == key_prefix_of(row["plaintext"])
    assert "plaintext" not in view
    assert "key_hash" not in view
    assert "keyHash" not in view


# ---------------------------------------------------------------------------
# 认证依赖（api_key_auth）
# ---------------------------------------------------------------------------

def test_principal_from_resolved():
    resolved = {
        "key": {"_id": "k1", "employee_id": "emp-1", "tenant_id": TENANT, "scope": "read", "key_prefix": "abc12345"},
        "employee": {"_id": "emp-1", "name": "财务员工", "creator_id": "admin"},
    }
    principal = _principal_from_resolved(resolved)
    assert principal.employee_id == "emp-1"
    assert principal.tenant_id == TENANT
    assert principal.scope == "read"
    assert principal.employee_name == "财务员工"
    assert principal.allows("read") is True
    assert principal.allows("session") is False


def test_principal_allows_matrix():
    p = EmployeeApiKeyPrincipal(
        employee_id="e", tenant_id="t", scope="read+session", key_id="k", key_prefix="p"
    )
    assert p.allows("read", "session") is True
    assert p.allows("read") is True
    p2 = EmployeeApiKeyPrincipal(
        employee_id="e", tenant_id="t", scope="session", key_id="k", key_prefix="p"
    )
    assert p2.allows("session") is True
    assert p2.allows("read") is False


async def test_resolve_employee_key_missing_header_raises_401():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await resolve_employee_key(x_api_key=None)
    assert exc.value.status_code == 401


async def test_resolve_employee_key_blank_header_raises_401():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await resolve_employee_key(x_api_key="   ")
    assert exc.value.status_code == 401
