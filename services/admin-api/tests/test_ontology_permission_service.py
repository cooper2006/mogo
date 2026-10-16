"""本体数据权限（admin-api）单元测试。

覆盖：
* ``resolve_visible_ontologies`` 判权合并（priority / 同优先级取更严格 / enabled / 主体过滤）。
* ``OntologyPermissionService`` 的配置、清单、授权写入侧（含审计）与 fail-closed 边界。

用内存 Fake 仓储，不依赖 mongo / PanWeiDB（原生 repository 的双后端行为由集成验证覆盖）。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pytest
from fastapi import HTTPException

from app.ontology_permission.repository import OntologyPermissionRepository
from app.ontology_permission.service import (
    OntologyPermissionService,
    resolve_visible_ontologies,
)
from app.ontology_permission.subjects import SubjectSet


# ---------------------------------------------------------------------------
# 纯解析
# ---------------------------------------------------------------------------


def test_resolve_higher_priority_wins() -> None:
    rows = [
        {"subject_type": "tenant", "subject_id": "t1", "ontology_uri": "m", "access_mode": "read", "priority": 10},
        {"subject_type": "user", "subject_id": "u1", "ontology_uri": "m", "access_mode": "none", "priority": 50},
    ]
    visible = resolve_visible_ontologies([("tenant", "t1"), ("user", "u1")], rows)
    assert visible == frozenset()


def test_resolve_tie_prefers_more_restrictive() -> None:
    rows = [
        {"subject_type": "tenant", "subject_id": "t1", "ontology_uri": "m", "access_mode": "write", "priority": 100},
        {"subject_type": "tenant", "subject_id": "t1", "ontology_uri": "m", "access_mode": "none", "priority": 100},
    ]
    visible = resolve_visible_ontologies([("tenant", "t1")], rows)
    assert visible == frozenset()


def test_resolve_ignores_disabled_rows() -> None:
    rows = [
        {"subject_type": "user", "subject_id": "u1", "ontology_uri": "m", "access_mode": "read", "enabled": False},
    ]
    assert resolve_visible_ontologies([("user", "u1")], rows) == frozenset()


def test_resolve_ignores_non_member_subject() -> None:
    rows = [
        {"subject_type": "role", "subject_id": "r9", "ontology_uri": "m", "access_mode": "read"},
    ]
    assert resolve_visible_ontologies([("user", "u1")], rows) == frozenset()


def test_resolve_keeps_read_and_write_only() -> None:
    rows = [
        {"subject_type": "user", "subject_id": "u1", "ontology_uri": "a", "access_mode": "read"},
        {"subject_type": "user", "subject_id": "u1", "ontology_uri": "b", "access_mode": "write"},
        {"subject_type": "user", "subject_id": "u1", "ontology_uri": "c", "access_mode": "none"},
    ]
    assert resolve_visible_ontologies([("user", "u1")], rows) == frozenset({"a", "b"})


def test_resolve_skips_rows_without_ontology_uri() -> None:
    rows = [{"subject_type": "user", "subject_id": "u1", "access_mode": "read"}]
    assert resolve_visible_ontologies([("user", "u1")], rows) == frozenset()


# ---------------------------------------------------------------------------
# Fake 仓储
# ---------------------------------------------------------------------------


class FakeRepository:
    def __init__(self) -> None:
        self.grants: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        self.details: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
        self.audits: list[dict[str, Any]] = []
        self.config: dict[str, Any] = {"enforce": False, "defaultMode": "allow", "rev": 0}
        self.catalog: list[dict[str, Any]] = []

    async def list_grants(self, tenant_id, *, subject_type=None, subject_id=None, ontology_uri=None, enabled_only=False):
        out = []
        for key, row in self.grants.items():
            if key[0] != str(tenant_id):
                continue
            if subject_type and key[1] != str(subject_type):
                continue
            if subject_id and key[2] != str(subject_id):
                continue
            if ontology_uri and key[3] != str(ontology_uri):
                continue
            if enabled_only and row.get("enabled") is False:
                continue
            out.append(dict(row))
        return out

    async def list_grants_for_subjects(self, tenant_id, subjects: Sequence[tuple[str, str]]):
        keys = {(str(a), str(b)) for a, b in subjects}
        return [
            dict(row)
            for key, row in self.grants.items()
            if key[0] == str(tenant_id) and (key[1], key[2]) in keys and row.get("enabled") is not False
        ]

    async def upsert_grant(self, row: Mapping[str, Any]):
        payload = dict(row)
        key = (
            str(row.get("tenant_id")),
            str(row.get("subject_type")),
            str(row.get("subject_id")),
            str(row.get("ontology_uri")),
        )
        self.grants[key] = payload
        return payload

    async def delete_grant(self, tenant_id, subject_type, subject_id, ontology_uri) -> int:
        key = (str(tenant_id), str(subject_type), str(subject_id), str(ontology_uri))
        return 1 if self.grants.pop(key, None) is not None else 0

    async def list_details(self, tenant_id, *, subject_type=None, subject_id=None, ontology_uri=None):
        out = []
        for key, row in self.details.items():
            if key[0] != str(tenant_id):
                continue
            if subject_type and key[1] != str(subject_type):
                continue
            if subject_id and key[2] != str(subject_id):
                continue
            if ontology_uri and key[3] != str(ontology_uri):
                continue
            out.append(dict(row))
        return out

    async def delete_detail(self, tenant_id, subject_type, subject_id, ontology_uri, class_name) -> int:
        key = (str(tenant_id), str(subject_type), str(subject_id), str(ontology_uri), str(class_name))
        return 1 if self.details.pop(key, None) is not None else 0

    async def write_audit(self, *, tenant_id, actor, action, target_kind, target_key, detail=None) -> None:
        self.audits.append(
            {
                "tenant_id": tenant_id,
                "actor": actor,
                "action": action,
                "target_kind": target_kind,
                "target_key": target_key,
                "detail": detail,
            }
        )

    async def list_audit(self, tenant_id, *, limit: int = 50):
        return [row for row in self.audits if row.get("tenant_id") == tenant_id][:limit]

    async def get_sys_config(self, key: str = ""):
        return dict(self.config)

    async def set_sys_config(self, value, key: str = ""):
        self.config = dict(value)
        return dict(value)

    async def list_catalog(self, tenant_id: str):
        return [dict(item) for item in self.catalog]


def _service() -> tuple[OntologyPermissionService, FakeRepository]:
    repo = FakeRepository()
    return OntologyPermissionService(repository=repo), repo  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_config_defaults_to_not_enforcing() -> None:
    service, _ = _service()
    config = await service.get_config()
    assert config["enforce"] is False
    assert config["defaultMode"] == "allow"
    assert config["effectiveDefault"] == "allow"


@pytest.mark.asyncio
async def test_set_enforce_makes_effective_default_deny() -> None:
    service, repo = _service()
    config = await service.set_enforce(tenant_id="t1", actor="admin", enforce=True)
    assert config["enforce"] is True
    # 决策③：enforce=true 时缺省判定固定为 deny，defaultMode 仅作预演口径。
    assert config["effectiveDefault"] == "deny"
    assert repo.audits[-1]["action"] == "enforce_toggle"


@pytest.mark.asyncio
async def test_set_enforce_rejects_bad_default_mode() -> None:
    service, _ = _service()
    with pytest.raises(HTTPException) as exc:
        await service.set_enforce(tenant_id="t1", actor="admin", enforce=True, default_mode="maybe")
    assert exc.value.status_code == 422


# ---------------------------------------------------------------------------
# 可见集
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_visible_ontologies_empty_user_is_fail_closed() -> None:
    service, _ = _service()
    result = await service.visible_ontologies("t1", "")
    assert result["ontologies"] == []
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_visible_ontologies_uses_tenant_fallback_and_user_grant() -> None:
    service, repo = _service()
    await repo.upsert_grant(
        {"tenant_id": "t1", "subject_type": "tenant", "subject_id": "t1", "ontology_uri": "shared", "access_mode": "read"}
    )
    await repo.upsert_grant(
        {"tenant_id": "t1", "subject_type": "user", "subject_id": "u1", "ontology_uri": "private", "access_mode": "read"}
    )
    result = await service.visible_ontologies("t1", "u1")
    assert result["ontologies"] == ["private", "shared"]


@pytest.mark.asyncio
async def test_visible_ontologies_does_not_leak_other_tenant() -> None:
    service, repo = _service()
    await repo.upsert_grant(
        {"tenant_id": "t2", "subject_type": "tenant", "subject_id": "t2", "ontology_uri": "leak", "access_mode": "read"}
    )
    result = await service.visible_ontologies("t1", "u1")
    assert result["ontologies"] == []


@pytest.mark.asyncio
async def test_resolve_for_user_expands_org_and_role() -> None:
    service, repo = _service()

    class StubExpander:
        async def expand(self, tenant_id: str, user_id: str) -> SubjectSet:
            return SubjectSet(
                tenant_id=tenant_id,
                user_id=user_id,
                org_ids=frozenset({"o1"}),
                role_ids=frozenset({"r1"}),
            )

    await repo.upsert_grant(
        {"tenant_id": "t1", "subject_type": "org", "subject_id": "o1", "ontology_uri": "org-onto", "access_mode": "read"}
    )
    await repo.upsert_grant(
        {"tenant_id": "t1", "subject_type": "role", "subject_id": "r1", "ontology_uri": "role-onto", "access_mode": "write"}
    )
    result = await service.resolve_for_user("t1", "u1", expander=StubExpander())
    assert result["ontologies"] == ["org-onto", "role-onto"]
    assert result["orgIds"] == ["o1"]
    assert result["roleIds"] == ["r1"]


# ---------------------------------------------------------------------------
# 授权写入侧
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_grant_writes_rows_dedup_and_audits() -> None:
    service, repo = _service()
    result = await service.batch_grant(
        tenant_id="t1",
        actor="admin",
        subject_type="user",
        subject_id="u1",
        ontology_ids=["b", "a", "a", " "],
        access_mode="read",
    )
    assert result["granted"] == 2
    assert result["ontologyIds"] == ["a", "b"]
    assert len(repo.grants) == 2
    assert repo.audits[-1]["action"] == "grant_save"
    assert repo.audits[-1]["target_key"] == "user/u1"


@pytest.mark.asyncio
async def test_batch_grant_rejects_empty_ids() -> None:
    service, _ = _service()
    with pytest.raises(HTTPException) as exc:
        await service.batch_grant(
            tenant_id="t1", actor="admin", subject_type="user", subject_id="u1", ontology_ids=["", " "]
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_batch_grant_rejects_invalid_access_mode() -> None:
    service, _ = _service()
    with pytest.raises(HTTPException) as exc:
        await service.batch_grant(
            tenant_id="t1",
            actor="admin",
            subject_type="user",
            subject_id="u1",
            ontology_ids=["a"],
            access_mode="admin",
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_revoke_removes_grant_and_orphan_details() -> None:
    service, repo = _service()
    await repo.upsert_grant(
        {"tenant_id": "t1", "subject_type": "user", "subject_id": "u1", "ontology_uri": "a", "access_mode": "read"}
    )
    repo.details[("t1", "user", "u1", "a", "Customer")] = {
        "tenant_id": "t1",
        "subject_type": "user",
        "subject_id": "u1",
        "ontology_uri": "a",
        "class_name": "Customer",
    }
    result = await service.revoke(
        tenant_id="t1", actor="admin", subject_type="user", subject_id="u1", ontology_uri="a"
    )
    assert result["deleted"] == 1
    assert result["detailsDeleted"] == 1
    assert repo.grants == {}
    assert repo.details == {}
    assert repo.audits[-1]["action"] == "grant_delete"


@pytest.mark.asyncio
async def test_list_subject_grants_serializes_for_frontend() -> None:
    service, repo = _service()
    await repo.upsert_grant(
        {
            "tenant_id": "t1",
            "subject_type": "user",
            "subject_id": "u1",
            "ontology_uri": "material",
            "access_mode": "read",
            "priority": 100,
            "enabled": True,
            "remark": "生产计划岗",
        }
    )
    payload = await service.list_subject_grants("t1", "user", "u1")
    assert payload["subjectType"] == "user"
    assert payload["grants"][0]["ontologyId"] == "material"
    assert payload["grants"][0]["accessMode"] == "read"


@pytest.mark.asyncio
async def test_list_catalog_includes_granted_but_unindexed_ontologies() -> None:
    service, repo = _service()
    repo.catalog = [{"ontology_id": "material", "entity_count": 3, "entity_types": ["product"]}]
    await repo.upsert_grant(
        {"tenant_id": "t1", "subject_type": "user", "subject_id": "u1", "ontology_uri": "material", "access_mode": "read"}
    )
    await repo.upsert_grant(
        {"tenant_id": "t1", "subject_type": "user", "subject_id": "u1", "ontology_uri": "manual-only", "access_mode": "read"}
    )
    catalog = await service.list_catalog("t1")
    ids = [item["ontologyId"] for item in catalog]
    assert ids == ["manual-only", "material"]
    assert catalog[1]["grantCount"] == 1


@pytest.mark.asyncio
async def test_bump_revision_increments_and_preserves_enforce() -> None:
    service, repo = _service()
    await service.set_enforce(tenant_id="t1", actor="admin", enforce=True)
    rev = await service.bump_revision("t1", "admin")
    assert rev == repo.config["rev"]
    assert repo.config["enforce"] is True


# ---------------------------------------------------------------------------
# 回归：省略 ``enabled`` 时的归一化（mongo 后端等价冒烟抓到的高危 bug）
#
# ``bool(row.get("enabled", True))`` 在上游 dict **含** "enabled" 键且值为 None 时
# 返回 bool(None)=False，授权被静默写成「已禁用」，随后被
# ``enabled = true``（PG）/ ``enabled: {$ne: False}``（mongo）全部滤掉，
# 表现为「授予成功但判权热路径 for_subjects 查不到」。
# 管理端 batch_grant 显式传了 enabled=True 所以当时没暴露；本测试与
# deploy/tests/test_ontology_permission_smoke.py 共同守护该语义。
# ---------------------------------------------------------------------------


class _CaptureCollection:
    """只记录 replace_one 收到的文档（upsert_grant/upsert_detail 的落库形态）。"""

    def __init__(self) -> None:
        self.captured: dict[str, Any] | None = None

    async def replace_one(self, flt: Mapping[str, Any], doc: Mapping[str, Any], upsert: bool = False):
        self.captured = dict(doc)

        class _Result:
            upserted_id = flt.get("_id")

        return _Result()


class _FakeDB(dict):
    """最小 motor 数据库替身：按集合名返回共享的捕获集合。"""

    def __init__(self) -> None:
        super().__init__()
        self.grant_coll = _CaptureCollection()
        self.detail_coll = _CaptureCollection()

    def __missing__(self, key: str) -> _CaptureCollection:
        if key == "mesc_ontology_grant":
            return self.grant_coll
        if key == "mesc_ontology_class_detail":
            return self.detail_coll
        return _CaptureCollection()


@pytest.mark.asyncio
async def test_upsert_grant_defaults_enabled_true_when_field_omitted() -> None:
    """不传 enabled → 必须落库为 True（不能因 None 变成 False）。"""
    from app.ontology_permission.constants import GRANT_TABLE

    db = _FakeDB()
    repo = OntologyPermissionRepository(db=db)
    doc = await repo.upsert_grant(
        {
            "tenant_id": "t1",
            "subject_type": "user",
            "subject_id": "u1",
            "ontology_uri": "material",
            "access_mode": "read",
        }
    )
    assert GRANT_TABLE == "mesc_ontology_grant"
    assert doc["enabled"] is True, "省略 enabled 时必须归一化为 True"
    assert db.grant_coll.captured is not None
    assert db.grant_coll.captured["enabled"] is True


@pytest.mark.asyncio
async def test_upsert_grant_honors_explicit_enabled_false() -> None:
    """显式传 False → 保持 False（不能被「兜底 True」吞掉）。"""
    db = _FakeDB()
    repo = OntologyPermissionRepository(db=db)
    doc = await repo.upsert_grant(
        {
            "tenant_id": "t1",
            "subject_type": "user",
            "subject_id": "u1",
            "ontology_uri": "material",
            "access_mode": "read",
            "enabled": False,
        }
    )
    assert doc["enabled"] is False
    assert db.grant_coll.captured["enabled"] is False


@pytest.mark.asyncio
async def test_upsert_detail_defaults_enabled_true_when_field_omitted() -> None:
    """类明细同样必须归一化（走同一个陷阱）。"""
    db = _FakeDB()
    repo = OntologyPermissionRepository(db=db)
    doc = await repo.upsert_detail(
        {
            "tenant_id": "t1",
            "subject_type": "user",
            "subject_id": "u1",
            "ontology_uri": "material",
            "class_name": "Material",
            "access_mode": "inherit",
            "column_mode": "selected",
            "column_list": ["code", "name"],
        }
    )
    assert doc["enabled"] is True
    assert db.detail_coll.captured is not None
    assert db.detail_coll.captured["enabled"] is True
