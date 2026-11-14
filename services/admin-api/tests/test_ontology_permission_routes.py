"""030 本体权限路由回归：``ontology://`` 形态 URI 的撤销路径。

背景：``ontology_uri`` 形如 ``ontology://customer``（含 ``://``），而 APIRouter 默认
``str`` 路径参数换算器**不匹配 ``/``**；前端 ``encodeURIComponent`` 编码后
（%3A%2F%2F），ASGI 服务器解出的 ``scope["path"]`` 仍还原为 ``/``（uvicorn 与
Starlette TestClient 均对 path 做 unquote）→ DELETE 一律 404，真实授权在 UI 上
无法撤销。修复：两个 DELETE 路由的 ``{ontology_id}`` 改用 ``:path`` 换算器。

本测试不连库：覆盖 ``get_current_admin_user`` 依赖 + 打桩 ``OntologyPermissionService``，
只锁定「路由能匹配含 ``/`` 的本体 URI 且把完整 URI 交给 service」这一行为。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_current_admin_user
from app.api.routes import ontologies as routes_module
from app.api.routes.ontologies import router

TENANT_ID = "t-1"
USER_ID = "u-1"
ORG_ID = "org-1"
ROLE_ID = "role-1"

_USER_PATHS = [
    # 原样（调试/直连接口形态）
    f"/api/ontologies/users/{USER_ID}/permissions/ontology://customer",
    # 回归保护：不含 / 的裸 id 也必须仍然可用（上轮冒烟用的形态）
    f"/api/ontologies/users/{USER_ID}/permissions/customer",
]
_SUBJECT_PATHS = [
    f"/api/ontologies/subjects/org/{ORG_ID}/permissions/ontology://order",
    f"/api/ontologies/subjects/role/{ROLE_ID}/permissions/ontology://product",
]

# ⚠ 前端发送的 ``encodeURIComponent`` 形态（%3A%2F%2F）不在本单测覆盖：
# httpx 的 TestClient 会先做 URL 规范化（%3A → :），再经 starlette ``unquote``
# 解 %2F，冒号被解两遍变成 ``ontology:://``——这是 TestClient 链路与真实
# 「浏览器 → uvicorn（单次 unquote）」的差异，不是路由缺陷。该形态由部署后
# 对真实服务的 smoke 探针验证（存量授权 DELETE 200 且 deleted=1）。


class _FakeService:
    """记录 revoke 调用；revoke 的其余语义（删明细/审计）由 service 单测覆盖。"""

    def __init__(self) -> None:
        self.revoked: list[dict] = []

    async def revoke(self, **kwargs):
        self.revoked.append(kwargs)
        return {"deleted": 1, "detailsDeleted": 0}

    async def bump_revision(self, tenant_id: str, actor: str) -> int:
        return 1


@pytest.fixture(name="harness")
def _harness(monkeypatch):
    fake = _FakeService()
    monkeypatch.setattr(
        routes_module, "OntologyPermissionService", lambda repository=None: fake
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/ontologies")
    app.dependency_overrides[get_current_admin_user] = lambda: {
        "tenant_id": TENANT_ID,
        "username": "admin",
        "_id": "admin-1",
    }
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, service=fake)


@pytest.mark.parametrize("path", _USER_PATHS, ids=("raw-ontology", "plain-id"))
def test_user_revoke_matches_slash_containing_ontology_uri(harness, path):
    r = harness.client.delete(path)
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": 1, "detailsDeleted": 0}
    call = harness.service.revoked[-1]
    assert call["subject_type"] == "user"
    assert call["subject_id"] == USER_ID
    # raw / encoded 两种形态都必须还原出完整 URI；裸 id 原样透传
    expected = "customer" if path.endswith("/permissions/customer") else "ontology://customer"
    assert call["ontology_uri"] == expected


@pytest.mark.parametrize("path", _SUBJECT_PATHS, ids=("org", "role"))
def test_subject_revoke_matches_slash_containing_ontology_uri(harness, path):
    r = harness.client.delete(path)
    assert r.status_code == 200, r.text
    call = harness.service.revoked[-1]
    assert call["tenant_id"] == TENANT_ID
    if "/org/" in path:
        assert call["subject_type"] == "org" and call["subject_id"] == ORG_ID
        assert call["ontology_uri"] == "ontology://order"
    else:
        assert call["subject_type"] == "role" and call["subject_id"] == ROLE_ID
        assert call["ontology_uri"] == "ontology://product"
