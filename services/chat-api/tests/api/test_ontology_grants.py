"""终端用户侧本体授权接口的单元测试（030 user-web 迁移）。

覆盖：
* 合并逻辑：tenant 兜底 + 用户自身；同本体取 priority 大者、同优先级取更严格模式；
  ``enabled is False`` 视为不存在；非命中主体被忽略；空 ``ontology_uri`` 跳过。
* fail-open 展示语义：查询异常时返回空清单 + ``degraded=true``（不阻断用户其它操作）。
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints import ontology_grants as og
from app.api.principal import require_end_user_principal


def _merge(rows, tenant="t1", user="u1"):
    return og._merge_subject_grants(tenant, user, rows)


class TestMergeSubjectGrants:
    def test_tenant_fallback_only(self):
        merged, disabled = _merge(
            [
                {
                    "subject_type": "tenant",
                    "subject_id": "t1",
                    "ontology_uri": "material",
                    "access_mode": "read",
                    "priority": 100,
                    "enabled": True,
                    "remark": "租户兜底",
                }
            ]
        )
        assert [m["ontologyId"] for m in merged] == ["material"]
        assert merged[0]["subjectType"] == "tenant"
        assert merged[0]["visible"] is True
        assert disabled == 0

    def test_user_row_wins_on_higher_priority_even_when_stricter(self):
        merged, _ = _merge(
            [
                {
                    "subject_type": "tenant",
                    "subject_id": "t1",
                    "ontology_uri": "material",
                    "access_mode": "read",
                    "priority": 100,
                    "enabled": True,
                },
                {
                    "subject_type": "user",
                    "subject_id": "u1",
                    "ontology_uri": "material",
                    "access_mode": "none",
                    "priority": 200,
                    "enabled": True,
                },
            ]
        )
        assert len(merged) == 1
        assert merged[0]["accessMode"] == "none"
        assert merged[0]["visible"] is False
        assert merged[0]["subjectType"] == "user"

    def test_same_priority_prefers_stricter_mode(self):
        merged, _ = _merge(
            [
                {
                    "subject_type": "tenant",
                    "subject_id": "t1",
                    "ontology_uri": "material",
                    "access_mode": "write",
                    "priority": 100,
                    "enabled": True,
                },
                {
                    "subject_type": "user",
                    "subject_id": "u1",
                    "ontology_uri": "material",
                    "access_mode": "none",
                    "priority": 100,
                    "enabled": True,
                },
            ]
        )
        assert merged[0]["accessMode"] == "none"

    def test_disabled_row_is_invisible_but_counted(self):
        merged, disabled = _merge(
            [
                {
                    "subject_type": "user",
                    "subject_id": "u1",
                    "ontology_uri": "material",
                    "access_mode": "read",
                    "priority": 100,
                    "enabled": False,
                }
            ]
        )
        assert merged == []
        assert disabled == 1

    def test_foreign_subject_is_ignored(self):
        merged, _ = _merge(
            [
                {
                    "subject_type": "user",
                    "subject_id": "someone-else",
                    "ontology_uri": "secret",
                    "access_mode": "read",
                    "priority": 999,
                    "enabled": True,
                }
            ]
        )
        assert merged == []

    def test_empty_ontology_uri_skipped(self):
        merged, _ = _merge(
            [{"subject_type": "user", "subject_id": "u1", "ontology_uri": "", "access_mode": "read"}]
        )
        assert merged == []

    def test_results_sorted_and_marked_visible(self):
        merged, _ = _merge(
            [
                {"subject_type": "user", "subject_id": "u1", "ontology_uri": "zeta", "access_mode": "read"},
                {"subject_type": "user", "subject_id": "u1", "ontology_uri": "alpha", "access_mode": "write"},
            ]
        )
        assert [m["ontologyId"] for m in merged] == ["alpha", "zeta"]
        assert all(m["visible"] for m in merged)


class TestMineEndpoint:
    def _client(self, principal):
        app = FastAPI()
        app.include_router(og.router)

        async def _dep():
            return principal

        app.dependency_overrides[require_end_user_principal] = _dep
        return TestClient(app)

    def test_mine_returns_merged_grants(self, monkeypatch):
        rows = [
            {
                "subject_type": "tenant",
                "subject_id": "t1",
                "ontology_uri": "material",
                "access_mode": "read",
                "priority": 100,
                "enabled": True,
                "remark": "",
            }
        ]

        async def _rows(tenant_id, user_id):
            return rows

        monkeypatch.setattr(og, "_fetch_subject_grant_rows", _rows)
        principal = SimpleNamespace(tenant_id="t1", user_id="u1", kind="end_user")
        resp = self._client(principal).get("/api/v1/ontology-grants/mine")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["visibleCount"] == 1
        assert body["degraded"] is False
        assert body["ontologies"][0]["ontologyId"] == "material"

    def test_mine_degrades_on_backend_error(self, monkeypatch):
        async def _boom(tenant_id, user_id):
            raise RuntimeError("db down")

        monkeypatch.setattr(og, "_fetch_subject_grant_rows", _boom)
        principal = SimpleNamespace(tenant_id="t1", user_id="u1", kind="end_user")
        resp = self._client(principal).get("/api/v1/ontology-grants/mine")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ontologies"] == []
        assert body["count"] == 0
        assert body["degraded"] is True

    def test_mine_empty_scope_short_circuits(self):
        principal = SimpleNamespace(tenant_id="", user_id="", kind="end_user")
        resp = self._client(principal).get("/api/v1/ontology-grants/mine")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0
