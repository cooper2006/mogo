"""030 本体数据权限 —— admin-api 端到端冒烟（真实 PanWeiDB / Mongo，无 mock）。

覆盖 tasks.md T023 的冒烟路径：:

    GET  /api/ontologies
    POST /api/ontologies/sync
    GET  /api/ontologies/config
    POST /api/ontologies/users/{uid}/permissions   （批量 + 去重）
    GET  /api/ontologies/users/{uid}/permissions   （回读）
    POST /api/ontologies/subjects/role/{rid}/permissions （四态通用）
    DEL  /api/ontologies/users/{uid}/permissions/{oid}
    GET  /api/ontologies/audit
    PUT  /api/ontologies/config                     （enforce 开/关复原）
    未认证 401 / 内部接口无凭证 401

**运行条件**（缺任一即 skip，不视为失败）：

1. 在 ``mogo-admin-api-1`` 容器内执行 —— 需要 ``/run/askai-secrets/runtime.env``
   提供 ``ASKAI_ADMIN_JWT_SECRET``，才能与运行中的服务同密钥签票；
2. 业务库可达且存在至少一个 ``status = active`` 的管理员账号。脚本**借用**该
   账号身份签一次性会话（不触碰口令），结束即 ``revoke_session``；
3. 写路径会真的落库，故对自建的冒烟数据**用完即删**。

**为什么全部塞进一个协程**：``asyncio.run`` 每调一次就新建事件循环，而
``app.core.db`` 的异步连接池会绑定首次使用的 loop。分多个 ``asyncio.run``
会让后续调用在已关闭的 loop 上用池并报错，因此一次性跑完最稳妥。

用法（容器内，把本文件经 stdin 喂给 python）::

    docker exec -i mogo-admin-api-1 sh -c \\
      '. /run/askai-secrets/runtime.env; export ASKAI_ADMIN_JWT_SECRET; python -' \\
      < deploy/tests/test_ontology_permission_smoke.py
"""

from __future__ import annotations

import os
import sys

import pytest

BASE = "http://127.0.0.1:8100/api"
SMOKE_USER = "smoke-030-user"
SMOKE_ROLE = "smoke-030-role"
ONTOLOGIES = ("material", "customer")
_RUNTIME_ENV = "/run/askai-secrets/runtime.env"

_NEEDS_RUNTIME_ENV = (
    f"需在 mogo-admin-api-1 容器内且已注入 ASKAI_ADMIN_JWT_SECRET（{_RUNTIME_ENV}）"
)
_HAS_SECRET = os.path.exists(_RUNTIME_ENV) and bool(os.environ.get("ASKAI_ADMIN_JWT_SECRET"))


@pytest.mark.skipif(not _HAS_SECRET, reason=_NEEDS_RUNTIME_ENV)
def test_ontology_permission_end_to_end() -> None:
    """跑通 docstring 列出的整条链路，并清理自建数据。"""
    import asyncio

    results = asyncio.run(_flow())
    failed = [(name, extra) for name, ok, extra in results if not ok]
    assert not failed, f"冒烟未通过项: {failed}"


async def _flow() -> list[tuple[str, bool, str]]:
    import httpx

    from app.core.db import init_backend, get_db
    from app.core.security import create_access_token
    from app.repositories import admin_session_repository as asr
    from app.repositories import org_user_repository as our

    await init_backend()
    account = await get_db()[our.ACCOUNT_COLLECTION].find_one({"status": "active"})
    if account is None:
        pytest.skip("业务库中没有 status=active 的管理员账号")
    username, tenant_id = account.get("username"), account.get("tenant_id")
    if not username or not tenant_id:
        pytest.skip("借用到的管理员账号缺少 username / tenant_id")

    token, expires_at, session_id = create_access_token(
        {"username": username, "tenant_id": tenant_id}, expires_in_seconds=600
    )
    await asr.create_session(
        session_id, username, expires_at, tenant_id=tenant_id,
        user_agent="030-smoke", ip="127.0.0.1",
    )

    results: list[tuple[str, bool, str]] = []

    def rec(name: str, ok: bool, extra: str = "") -> None:
        results.append((name, ok, extra))

    try:
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(base_url=BASE, headers=headers, timeout=30) as c:
            # 预清理：上次异常退出可能留下残留。
            r = await c.get(f"/ontologies/users/{SMOKE_USER}/permissions")
            for g in r.json().get("grants", []) if r.status_code == 200 else []:
                await c.delete(f"/ontologies/users/{SMOKE_USER}/permissions/{g['ontologyId']}")

            r = await c.get("/ontologies")
            rec("GET /ontologies", r.status_code == 200 and isinstance(r.json(), list),
                f"status={r.status_code}")

            r = await c.post("/ontologies/sync")
            rec("POST /ontologies/sync", r.status_code == 200, f"status={r.status_code}")

            r = await c.get("/ontologies/config")
            cfg = r.json() if r.status_code == 200 else {}
            rec("GET /ontologies/config", r.status_code == 200 and "enforce" in cfg,
                f"status={r.status_code}")

            # 批量授予 + 去重（第一个本体故意传两次）
            r = await c.post(f"/ontologies/users/{SMOKE_USER}/permissions", json={
                "ontologyIds": [ONTOLOGIES[0], ONTOLOGIES[1], ONTOLOGIES[0]],
                "accessMode": "read", "priority": 100, "remark": "030-smoke",
            })
            body = r.json() if r.status_code == 200 else {}
            ids = body.get("ontologyIds") or []
            rec("POST .../permissions 批量+去重",
                r.status_code == 200 and len(ids) == 2 and set(ids) == set(ONTOLOGIES),
                f"status={r.status_code} body={body}")

            r = await c.get(f"/ontologies/users/{SMOKE_USER}/permissions")
            grants = r.json().get("grants", []) if r.status_code == 200 else []
            rec("GET .../permissions 回读",
                r.status_code == 200
                and {g["ontologyId"] for g in grants} == set(ONTOLOGIES),
                f"status={r.status_code} n={len(grants)}")

            # 四态通用形态（role）
            r = await c.post(
                f"/ontologies/subjects/role/{SMOKE_ROLE}/permissions",
                json={"ontologyIds": [ONTOLOGIES[0]], "accessMode": "read", "priority": 100},
            )
            rec("POST /subjects/role/.../permissions", r.status_code == 200, f"status={r.status_code}")

            r = await c.delete(f"/ontologies/users/{SMOKE_USER}/permissions/{ONTOLOGIES[0]}")
            rec("DELETE .../permissions/{oid}", r.status_code in (200, 204), f"status={r.status_code}")

            r = await c.get("/ontologies/audit?limit=10")
            audit = r.json() if r.status_code == 200 and isinstance(r.json(), list) else []
            acts = [a.get("action") for a in audit]
            rec("GET /ontologies/audit", r.status_code == 200 and "grant_save" in acts,
                f"status={r.status_code} actions={acts[:6]}")

            # enforce 开 → 关（必须复原，避免影响后续环境）
            r = await c.put("/ontologies/config",
                            json={"enforce": True, "defaultMode": "deny", "rev": 990001})
            rec("PUT /ontologies/config enforce=true",
                r.status_code == 200 and r.json().get("enforce") is True, f"status={r.status_code}")
            r = await c.put("/ontologies/config",
                            json={"enforce": False, "defaultMode": "allow", "rev": 990002})
            rec("PUT 复原 enforce=false",
                r.status_code == 200 and r.json().get("enforce") is False, f"status={r.status_code}")

            # 清理自建数据
            r = await c.get(f"/ontologies/users/{SMOKE_USER}/permissions")
            for g in r.json().get("grants", []) if r.status_code == 200 else []:
                await c.delete(f"/ontologies/users/{SMOKE_USER}/permissions/{g['ontologyId']}")
            await c.delete(f"/ontologies/subjects/role/{SMOKE_ROLE}/permissions/{ONTOLOGIES[0]}")

        async with httpx.AsyncClient(base_url=BASE, timeout=30) as anon:
            r = await anon.get("/ontologies")
            rec("未认证 401", r.status_code == 401, f"status={r.status_code}")
            r = await anon.get("/internal/ontology-permissions",
                               params={"tenantId": "x", "userId": "y"})
            rec("内部接口无凭证 401", r.status_code == 401, f"status={r.status_code}")
    finally:
        await asr.revoke_session(session_id)

    return results


if __name__ == "__main__":  # pragma: no cover - 容器内 stdin 直跑
    # stdin 喂给 python 时没有文件路径，pytest 收集不到用例，故直接驱动协程。
    import asyncio

    _results = asyncio.run(_flow())
    _failed = [(n, e) for n, ok, e in _results if not ok]
    for _n, _ok, _e in _results:
        print(("  PASS  " if _ok else "  FAIL  ") + _n + ("  " + _e if _e else ""))
    print(f"==== smoke: {len(_results) - len(_failed)} passed / {len(_failed)} failed ====")
    sys.exit(1 if _failed else 0)
