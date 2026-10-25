"""025 T027 / T028 — 批量语义上限校验 + 降级空值判断。

T027（FR-14 / QF-245 / QF-247 / QF-248）：
- ``knowledge_documents.validate_batch_size`` 是批量接口的统一大小校验，
  ``BATCH_LIMIT == 100``；超限返回 422，``detail`` 为结构化 dict
  （含 ``code`` / ``message`` / ``field`` / ``path`` / ``limit`` / ``count``），
  不是裸字符串；空列表不在此处拦截。
- 已挂载到真实批量端点（position-roles 批量分配、ontologies 批量授予），
  用内存替身走真实路由验证 422 与放行两态。

T028（FR-15 / QF-252）：
- 降级场景应返回 ``null`` + ``degraded: true`` 元信息，**不**返回误导性的
  空数组 / 空对象。此处给出对合成坏样例的判断函数，供扫描报告复用。

不连 Mongo / Redis；全部走 FastAPI TestClient + monkeypatch。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


# --------------------------------------------------------------------------- T027


class TestBatchLimitFunction:
    """直接调用 ``validate_batch_size``（T027 核心单元）。"""

    def test_batch_limit_constant(self) -> None:
        from app.api.routes.knowledge_documents import BATCH_LIMIT

        assert BATCH_LIMIT == 100

    def test_at_limit_passes(self) -> None:
        from app.api.routes.knowledge_documents import validate_batch_size

        items = [f"id-{i}" for i in range(100)]
        assert validate_batch_size(items) == 100

    def test_over_limit_raises_422_with_structured_detail(self) -> None:
        from app.api.routes.knowledge_documents import validate_batch_size

        items = [f"id-{i}" for i in range(101)]
        with pytest.raises(HTTPException) as exc_info:
            validate_batch_size(items, field="ontologyIds", path="/ontologies/x")
        exc = exc_info.value
        assert exc.status_code == 422
        detail = exc.detail
        assert isinstance(detail, dict), "detail 必须是结构化 dict，不是裸字符串"
        assert detail["code"] == "api.validation_error"
        assert detail["limit"] == 100
        assert detail["count"] == 101
        assert detail["field"] == "ontologyIds"
        assert detail["path"] == "/ontologies/x"
        assert isinstance(detail["message"], str) and detail["message"]

    def test_empty_list_not_blocked_by_size_check(self) -> None:
        from app.api.routes.knowledge_documents import validate_batch_size

        # 空列表不在此处拦截（交由端点既有业务校验决定），此处断言不抛错。
        assert validate_batch_size([]) == 0

    def test_custom_limit_respected(self) -> None:
        from app.api.routes.knowledge_documents import validate_batch_size

        with pytest.raises(HTTPException) as exc_info:
            validate_batch_size(list(range(6)), limit=5)
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["limit"] == 5
        assert exc_info.value.detail["count"] == 6


# 内存替身：让批量端点的 service 调用零 DB 依赖。
class _FakeService:
    async def batch_grant(self, **kwargs: Any) -> dict[str, Any]:
        return {"granted": len(kwargs["ontology_ids"]), "ontologyIds": sorted(kwargs["ontology_ids"])}

    async def bump_revision(self, tenant_id: str, actor: str) -> None:  # noqa: ARG002
        return None


def _make_ontology_app(monkeypatch: Any) -> FastAPI:
    """构造只挂 ontologies 路由的最小 app，monkeypatch 掉 service 与鉴权依赖。"""
    from app.api.deps import get_current_admin_user
    from app.api.routes import ontologies
    from app.ontology_permission.service import OntologyPermissionService

    monkeypatch.setattr(OntologyPermissionService, "batch_grant", _FakeService.batch_grant)
    monkeypatch.setattr(OntologyPermissionService, "bump_revision", _FakeService.bump_revision)

    app = FastAPI()
    app.dependency_overrides[get_current_admin_user] = lambda: {
        "tenant_id": "t1",
        "user_id": "u1",
        "username": "admin",
    }
    app.include_router(ontologies.router, prefix="/ontologies")
    return app


class TestOntologyGrantBatchLimit:
    """真实批量端点（ontologies 批量授予）走 422 / 放行两态。"""

    def _grant(self, client: TestClient, ontology_ids: list[str]) -> Any:
        return client.post(
            "/ontologies/users/u1/permissions",
            json={"ontologyIds": ontology_ids, "accessMode": "read"},
        )

    def test_100_allowed(self, monkeypatch: Any) -> None:
        client = TestClient(_make_ontology_app(monkeypatch))
        response = self._grant(client, [f"ontology://k{i}" for i in range(100)])
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["granted"] == 100

    def test_101_rejected_422_structured_detail(self, monkeypatch: Any) -> None:
        client = TestClient(_make_ontology_app(monkeypatch))
        response = self._grant(client, [f"ontology://k{i}" for i in range(101)])
        assert response.status_code == 422, response.text
        detail = response.json()["detail"]
        assert isinstance(detail, dict)
        assert detail["code"] == "api.validation_error"
        assert detail["limit"] == 100
        assert detail["count"] == 101
        assert detail["field"] == "ontologyIds"
        assert detail["path"] == "/ontologies/users/{user_id}/permissions"


# --------------------------------------------------------------------------- T028


def is_misleading_empty_fallback(body: Any) -> bool:
    """T028 扫描用的降级空值判断：命中返回 True，表示需要整改。

    判据（来自 FR-15 / QF-252）：
    - 响应**主体**（或 ``data`` / ``items`` 承载字段）为 ``[]`` 或 ``{}``；
    - 且**没有** ``degraded: true`` 元信息，也没有 ``null`` 承载值；
    → 客户端无法区分「数据真空」与「服务降级」，属误导性空值。
    """
    if not isinstance(body, dict):
        return body is None  # 非 dict 且非 None 视为非降级形态
    degraded = body.get("degraded")
    if degraded is True:
        return False
    for key in ("data", "items", "results", "value"):
        if key in body and body[key] in ([], {}):
            return True
    # 主体本身就是空容器（无承载字段）
    return body == {}


class TestDegradedFallbackJudgement:
    """对合成坏样例的判断函数测试（T028 扫描判据）。"""

    def test_empty_items_without_degraded_flagged(self) -> None:
        assert is_misleading_empty_fallback({"items": [], "total": 0}) is True

    def test_empty_data_without_degraded_flagged(self) -> None:
        assert is_misleading_empty_fallback({"data": {}}) is True

    def test_null_with_degraded_true_not_flagged(self) -> None:
        assert is_misleading_empty_fallback({"value": None, "degraded": True}) is False

    def test_null_value_without_degraded_not_flagged_as_empty(self) -> None:
        # null 承载值本身即 T028 期望形态，即使缺 degraded 标记也不视为「空容器」。
        assert is_misleading_empty_fallback({"value": None}) is False

    def test_real_data_not_flagged(self) -> None:
        assert is_misleading_empty_fallback({"items": [1, 2], "total": 2}) is False