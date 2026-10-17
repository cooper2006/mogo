"""030 本体数据权限 —— 演示数据补种（真实库直写，幂等可复跑）。

背景：030 落地后库内仅有 2 条针对 ``6ab9dd0382f60252a4a40aa5`` 的冒烟残留授权
（该 subject 在 ``end_users`` 中不存在，已于 2026-10-17 清理）；本次给**真实用户** 朱军峰
（``zhujunfeng@bonc.com.cn`` / ``6ab9dd0382f60252a4a40aa6``）补齐演示数据，
并补全 tenant / org / role 三态主体，让四态主体模型在库里都有样本。

补种内容（均为 upsert，重复执行幂等；审计行按次新增）：

    A. 用户级授权 ×3（HTTP 写侧 ``POST /ontologies/users/{uid}/permissions``）
       ontology://customer read  / ontology://product write / ontology://order read
    B. 其他三态主体 ×3（HTTP 写侧 ``POST /ontologies/subjects/{type}/{sid}/permissions``）
       org 企业总部 ontology://order read p50；
       role 全能力管理员 ontology://customer read p50；
       tenant 兜底 ontology://product read p10（演示被用户级 priority 覆盖）
    C. 类明细 ×2（repository 直写 + detail_save 审计；HTTP 暂无明细写路由）
       customer/Customer：selected 列 + active 行；
       order/Order：列不过滤 + active 行
    D. 关系行状态修补 ×2（``end_user_org_relations`` / ``end_user_position_roles``
       的 ``status`` 原为 NULL，``SubjectExpander`` 按 ``active`` 过滤会匹配不到，
       导致 org / role 授权在运行期不生效）→ 置 ``active``
    E. 校验：回读用户授权、``resolve_for_user`` 四态并集、清单 grantCount、审计

用法（容器内，经 stdin 喂给 python，借用管理员身份只签一次性会话）::

    docker exec -i mogo-admin-api-1 sh -c \
      '. /run/askai-secrets/runtime.env; export ASKAI_ADMIN_JWT_SECRET; python -' \
      < deploy/tests/seed_ontology_permission_demo.py
"""

from __future__ import annotations

import os
import sys

import pytest

BASE = "http://127.0.0.1:8100/api"
_RUNTIME_ENV = "/run/askai-secrets/runtime.env"

TENANT_ID = "bonc-2331b8a0ecdbd2ebcbf253c4"
USER_ID = "6ab9dd0382f60252a4a40aa6"  # 朱军峰 zhujunfeng@bonc.com.cn
ORG_ID = "6ab9dd032ab4a1bd38c4d0f4"  # 企业总部
ROLE_ID = "system:bonc-2331b8a0ecdbd2ebcbf253c4:full_access_admin"

USER_GRANTS = [
    ("ontology://customer", "read", 100, "朱军峰：客户本体只读"),
    ("ontology://product", "write", 100, "朱军峰：产品本体可读写"),
    ("ontology://order", "read", 100, "朱军峰：订单本体只读"),
]
OTHER_GRANTS = [
    ("org", ORG_ID, "ontology://order", "read", 50, "企业总部组织兜底：订单只读（可被用户级覆盖）"),
    ("role", ROLE_ID, "ontology://customer", "read", 50, "全能力管理员角色兜底：客户只读（可被用户级覆盖）"),
    ("tenant", TENANT_ID, "ontology://product", "read", 10, "租户兜底：产品只读（最低优先级，演示覆盖）"),
]
CLASS_DETAILS = [
    {
        "ontology_uri": "ontology://customer",
        "class_name": "Customer",
        "access_mode": "read",
        "column_mode": "selected",
        "column_list": ["name", "code", "tenant_id"],
        "row_condition": {"status": "active"},
        "priority": 50,
        "remark": "朱军峰：Customer 类仅 name/code/tenant_id 列、active 行",
    },
    {
        "ontology_uri": "ontology://order",
        "class_name": "Order",
        "access_mode": "read",
        "column_mode": "all",
        "column_list": [],
        "row_condition": {"status": "active"},
        "priority": 50,
        "remark": "朱军峰：Order 类列不过滤、仅看 active 行",
    },
]

_NEEDS_RUNTIME_ENV = (
    f"需在 mogo-admin-api-1 容器内且已注入 ASKAI_ADMIN_JWT_SECRET（{_RUNTIME_ENV}）"
)
_HAS_SECRET = os.path.exists(_RUNTIME_ENV) and bool(os.environ.get("ASKAI_ADMIN_JWT_SECRET"))


@pytest.mark.skipif(not _HAS_SECRET, reason=_NEEDS_RUNTIME_ENV)
def test_seed_ontology_permission_demo() -> None:
    """补种演示数据并校验（真实 PanWeiDB，无 mock）。"""
    import asyncio

    results = asyncio.run(_flow())
    failed = [(name, extra) for name, ok, extra in results if not ok]
    assert not failed, f"补种/校验未通过项: {failed}"


async def _flow() -> list[tuple[str, bool, str]]:
    import httpx

    from app.core.db import init_backend, get_db
    from app.core.security import create_access_token
    from app.repositories import admin_session_repository as asr
    from app.repositories import org_user_repository as our
    from app.ontology_permission.repository import OntologyPermissionRepository, utcnow
    from app.ontology_permission.service import OntologyPermissionService

    await init_backend()
    account = await get_db()[our.ACCOUNT_COLLECTION].find_one(
        {"tenant_id": TENANT_ID, "status": "active"}
    )
    if account is None:
        pytest.skip(f"租户 {TENANT_ID} 没有 status=active 的管理员账号")
    username = account.get("username")
    if not username:
        pytest.skip("借用到的管理员账号缺少 username")

    token, expires_at, session_id = create_access_token(
        {"username": username, "tenant_id": TENANT_ID}, expires_in_seconds=600
    )
    await asr.create_session(
        session_id, username, expires_at, tenant_id=TENANT_ID,
        user_agent="030-seed", ip="127.0.0.1",
    )

    results: list[tuple[str, bool, str]] = []

    def rec(name: str, ok: bool, extra: str = "") -> None:
        results.append((name, ok, extra))

    try:
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(base_url=BASE, headers=headers, timeout=30) as c:
            # ── A. 用户级授权（朱军峰）────────────────────────────────────
            for uri, mode, priority, remark in USER_GRANTS:
                r = await c.post(
                    f"/ontologies/users/{USER_ID}/permissions",
                    json={
                        "ontologyIds": [uri],
                        "accessMode": mode,
                        "priority": priority,
                        "remark": remark,
                    },
                )
                rec(f"A grant user {uri}={mode}",
                    r.status_code == 200 and r.json().get("granted") == 1,
                    f"status={r.status_code}")

            # ── B. 其他三态主体 ───────────────────────────────────────────
            for subject_type, subject_id, uri, mode, priority, remark in OTHER_GRANTS:
                r = await c.post(
                    f"/ontologies/subjects/{subject_type}/{subject_id}/permissions",
                    json={
                        "ontologyIds": [uri],
                        "accessMode": mode,
                        "priority": priority,
                        "remark": remark,
                    },
                )
                rec(f"B grant {subject_type}/{subject_id[:24]} {uri}={mode}",
                    r.status_code == 200 and r.json().get("granted") == 1,
                    f"status={r.status_code}")

            # ── D. 关系行状态修补（org/role 展开器按 active 过滤）──────────
            db = get_db()
            now = utcnow()
            for coll, key in (
                ("end_user_org_relations", "org_id"),
                ("end_user_position_roles", "role_id"),
            ):
                r = await db[coll].update_one(
                    {"tenant_id": TENANT_ID, "user_id": USER_ID},
                    {"$set": {"status": "active", "updated_at": now}},
                )
                rec(f"D fix {coll}.status=active", r.modified_count >= 0,
                    f"matched={r.matched_count}")

            # ── C. 类明细（repository 直写 + 审计）────────────────────────
            repo = OntologyPermissionRepository()
            for detail in CLASS_DETAILS:
                row = {
                    "tenant_id": TENANT_ID,
                    "subject_type": "user",
                    "subject_id": USER_ID,
                    **detail,
                    "enabled": True,
                }
                await repo.upsert_detail(row)
                await repo.write_audit(
                    tenant_id=TENANT_ID,
                    actor=username,
                    action="detail_save",
                    target_kind="detail",
                    target_key=(
                        f"user/{USER_ID}/{detail['ontology_uri']}/{detail['class_name']}"
                    ),
                    detail={
                        "accessMode": detail["access_mode"],
                        "columnMode": detail["column_mode"],
                        "rowCondition": detail["row_condition"],
                        "remark": detail["remark"],
                    },
                )
                rec(f"C detail {detail['ontology_uri']}/{detail['class_name']}", True)

            # ── E. 校验 ──────────────────────────────────────────────────
            r = await c.get(f"/ontologies/users/{USER_ID}/permissions")
            bundle = r.json() if r.status_code == 200 else {}
            grants = bundle.get("grants") or []
            details = bundle.get("details") or []
            rec("E read user bundle", len(grants) == 3 and len(details) == 2,
                f"grants={len(grants)} details={len(details)}")

            service = OntologyPermissionService()
            resolved = await service.resolve_for_user(TENANT_ID, USER_ID)
            rec("E resolve_for_user union",
                resolved["ontologies"] == ["ontology://customer", "ontology://order",
                                           "ontology://product"]
                and len(resolved["orgIds"]) >= 1 and len(resolved["roleIds"]) >= 1,
                f"ontologies={resolved['ontologies']} orgIds={resolved['orgIds']} "
                f"roleIds={resolved['roleIds']}")

            r = await c.get("/ontologies")
            catalog = {item["ontologyId"]: item["grantCount"] for item in r.json()} \
                if r.status_code == 200 else {}
            rec("E catalog grantCount",
                catalog.get("ontology://customer") == 3
                and catalog.get("ontology://product") == 3
                and catalog.get("ontology://order") == 2,
                f"catalog={catalog}")

            r = await c.get("/ontologies/audit?limit=10")
            audit = r.json() if r.status_code == 200 else []
            rec("E audit tail",
                any(a["action"] == "grant_save" for a in audit)
                and any(a["action"] == "detail_save" for a in audit),
                f"head={[(a['action'], a['targetKey']) for a in audit[:4]]}")
    finally:
        await asr.revoke_session(session_id)

    return results


if __name__ == "__main__":  # pragma: no cover - 容器内直跑入口
    if not _HAS_SECRET:
        print(_NEEDS_RUNTIME_ENV)
        sys.exit(2)
    import asyncio

    rows = asyncio.run(_flow())
    for name, ok, extra in rows:
        print(f"[{'PASS' if ok else 'FAIL'}] {name} {extra}")
    sys.exit(0 if all(ok for _n, ok, _e in rows) else 1)
