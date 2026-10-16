"""030 SC-004 —— ontology_permission repository 的 **mongo 后端**等价冒烟。

与 `test_ontology_permission_smoke.py`（HTTP 层冒烟，跑在 PanWeiDB 上）互补：
本文件直接驱动 `OntologyPermissionRepository`，验证 mongo 后端下同样跑通
grant / detail / audit / sys_config / 清单的读写与清理，即「双后端行为一致」。

**为什么值得单独一份**：030 的第一个高危 bug（省略 `enabled` 时被归一化成
`False`，导致判权热路径 `for_subjects` 查不到任何授权）**只在 mongo 侧暴露** ——
PanWeiDB 侧冒烟全过，因为管理端 `batch_grant` 显式传了 `enabled=True`。
双后端必须各跑一遍，不能用一边的绿灯替代另一边。

**运行条件**（缺任一即 skip）：admin-api 镜像 + `mogo_backend` docker 网络
（要能解析 `mogo-mongo-1`）。mongo 未映射宿主机端口，故必须 `--network` 进内网。

用法::

    docker run --rm --network mogo_backend \\
      --entrypoint python -v <repo>/services/admin-api:/app -w /app \\
      -e PYTHONPATH=/app -e PYTHONDONTWRITEBYTECODE=1 \\
      -e MOGO_DATA_BACKEND=mongo \\
      -e MONGODB_URI=mongodb://mogo-mongo-1:27017 -e MONGODB_DB=mogo_dev \\
      admin-api:<tag> deploy/tests/test_ontology_permission_mongo_parity.py

写路径会真的落库到 mongo，但只碰 `parity-030` 租户下的冒烟数据，**用完即删**。
"""

from __future__ import annotations

import os
import sys

import pytest

SMOKE_TENANT = "parity-030"
SMOKE_USER = "parity-user-030"
GRANT_TABLE = "mesc_ontology_grant"
DETAIL_TABLE = "mesc_ontology_class_detail"

_NETWORK_OK = os.path.exists("/proc/net/route") and bool(
    __import__("socket").gethostbyname_ex("mogo-mongo-1")[2]
) if os.environ.get("MOGO_DATA_BACKEND") == "mongo" else False


def test_mongo_backend_selected() -> None:
    from app.core.db import is_panweidb_backend

    assert not is_panweidb_backend(), "本文件必须在 MOGO_DATA_BACKEND=mongo 下运行"


async def _flow() -> list[tuple[str, bool, str]]:
    from app.core.db import init_backend
    from app.ontology_permission.constants import grant_key
    from app.ontology_permission.repository import OntologyPermissionRepository

    await init_backend()
    repo = OntologyPermissionRepository()
    results: list[tuple[str, bool, str]] = []

    def rec(name: str, ok: bool, extra: str = "") -> None:
        results.append((name, ok, extra))

    try:
        # 预清理（上次异常退出可能留残留）
        for oid in ("material", "customer", "product"):
            await repo.delete_grant(SMOKE_TENANT, "user", SMOKE_USER, oid)
            await repo.delete_detail(SMOKE_TENANT, "user", SMOKE_USER, oid, "Material")

        # 1+2) upsert 的 insert 与 update 两条路径
        await repo.upsert_grant(
            {"tenant_id": SMOKE_TENANT, "subject_type": "user", "subject_id": SMOKE_USER,
             "ontology_uri": "material", "access_mode": "read", "priority": 100}
        )
        await repo.upsert_grant(
            {"tenant_id": SMOKE_TENANT, "subject_type": "user", "subject_id": SMOKE_USER,
             "ontology_uri": "material", "access_mode": "write", "priority": 120}
        )
        rows = await repo.list_grants(SMOKE_TENANT, subject_type="user", subject_id=SMOKE_USER)
        rec("grant upsert insert+update",
            len(rows) == 1 and rows[0]["access_mode"] == "write" and rows[0]["priority"] == 120,
            str([(r["ontology_uri"], r["access_mode"], r["priority"]) for r in rows]))

        # 3) 判权热路径（`enabled` 归一化 bug 的暴露点）
        got = await repo.list_grants_for_subjects(
            SMOKE_TENANT, [("tenant", SMOKE_TENANT), ("user", SMOKE_USER)])
        rec("for_subjects 命中授权行",
            len(got) == 1 and got[0]["ontology_uri"] == "material",
            str([(r["subject_type"], r["ontology_uri"]) for r in got]))

        # 4) detail：数组字段与对象字段的保真读写
        await repo.upsert_detail(
            {"tenant_id": SMOKE_TENANT, "subject_type": "user", "subject_id": SMOKE_USER,
             "ontology_uri": "material", "class_name": "Material", "access_mode": "inherit",
             "column_mode": "selected", "column_list": ["code", "name"],
             "row_condition": {"op": "eq", "field": "org", "value": "A"}, "priority": 100}
        )
        det = await repo.list_details(SMOKE_TENANT, subject_type="user", subject_id=SMOKE_USER)
        rec("detail upsert（array/object 保真）",
            len(det) == 1 and det[0]["column_list"] == ["code", "name"]
            and det[0]["row_condition"] == {"op": "eq", "field": "org", "value": "A"}
            and det[0]["enabled"] is True,
            str(det[:1]))

        # 5) audit 写 + 读
        await repo.write_audit(
            tenant_id=SMOKE_TENANT, actor="parity", action="grant_save",
            target_kind="grant", target_key="user/parity-user-030",
            detail={"ontologyIds": ["material"]})
        audit = await repo.list_audit(SMOKE_TENANT, limit=5)
        rec("audit write+read",
            len(audit) >= 1 and audit[0]["action"] == "grant_save"
            and audit[0]["detail"] == {"ontologyIds": ["material"]}, f"n={len(audit)}")

        # 6) sys_config：读缺省 → 写 → 回读 → 复原
        before = await repo.get_sys_config()
        rec("sys_config read 含缺省键",
            before.get("enforce") is False and "defaultMode" in before, str(before))
        await repo.set_sys_config({"enforce": True, "defaultMode": "deny", "rev": 999001})
        after = await repo.get_sys_config()
        rec("sys_config write+readback", after.get("enforce") is True, str(after))
        await repo.set_sys_config(before)

        # 7) `_id` 确定性拼接（等价 PG 复合主键）
        from app.core.db import get_db

        doc = await get_db()[GRANT_TABLE].find_one(
            {"_id": grant_key(SMOKE_TENANT, "user", SMOKE_USER, "material")})
        rec("_id 确定性拼接", doc is not None and doc.get("ontology_uri") == "material",
            str(doc.get("_id")) if doc else "NOT FOUND")

        # 8) 清理
        d1 = await repo.delete_detail(SMOKE_TENANT, "user", SMOKE_USER, "material", "Material")
        d2 = await repo.delete_grant(SMOKE_TENANT, "user", SMOKE_USER, "material")
        left = await repo.list_grants(SMOKE_TENANT)
        rec("cleanup", d1 == 1 and d2 == 1 and len(left) == 0,
            f"detail={d1} grant={d2} left={len(left)}")
    finally:
        # 无论中途是否失败，都把冒烟数据清干净。
        await repo.delete_detail(SMOKE_TENANT, "user", SMOKE_USER, "material", "Material")
        await repo.delete_grant(SMOKE_TENANT, "user", SMOKE_USER, "material")

    return results


def test_mongo_backend_repository_parity() -> None:
    import asyncio

    results = asyncio.run(_flow())
    failed = [(name, extra) for name, ok, extra in results if not ok]
    assert not failed, f"mongo parity 未通过项: {failed}"


if __name__ == "__main__":  # pragma: no cover - 容器内 stdin 直跑
    import asyncio

    _results = asyncio.run(_flow())
    _failed = [(n, e) for n, ok, e in _results if not ok]
    for _n, _ok, _e in _results:
        print(("  PASS  " if _ok else "  FAIL  ") + _n + ("  " + _e if _e else ""))
    print(f"==== mongo parity: {len(_results) - len(_failed)} passed / {len(_failed)} failed ====")
    sys.exit(1 if _failed else 0)
