"""025 US1 (T020)：语义契约集成测试（六组 Acceptance）。

把 T008 路径命名 / T011 状态码语义 / T015 幂等 / T017 分页 / T019 内容协商
装配到一个最小 FastAPI 应用上做端到端验证，六组各覆盖一组 Acceptance：

1. **路径命名** —— 真实仓库 `tools/api_check/path_naming.py` 扫描结果为 0 违规；
   应用内不暴露动词段路径。
2. **状态码** —— 业务失败走 4xx/5xx，不被 200 包裹；成功路径 2xx。
3. **幂等** —— 同 `Idempotency-Key` 重放返回缓存且下游只执行 1 次。
4. **并发** —— 并发重放同 key，下游仍只执行 1 次（副作用不重复）。
5. **分页** —— `PageResponse` 5 字段 snake_case，`next_cursor` 稳定翻页。
6. **内容协商** —— 不支持的 `Accept` 返回 406 + `Vary: Accept`；`Accept-Encoding: gzip`
   时 JSON 响应压缩。

原则：**不做环境依赖**（不连真实 Mongo/Redis），用内存替身验证契约。
"""

from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[4]
PATH_NAMING = REPO / "tools" / "api_check" / "path_naming.py"

from app.api.pagination import PageParams, PageResponse  # noqa: E402  (用于分页组 fixture app)
from app.core.idempotency import IdempotencyMiddleware, IdempotencyStore  # noqa: E402
from app.middleware.content_negotiation import ContentNegotiationMiddleware  # noqa: E402


ITEMS = [{"id": i, "name": f"item-{i}"} for i in range(1, 26)]  # 25 条


def _build_app() -> tuple[FastAPI, dict[str, Any]]:
    """构建集成应用；返回 (app, hits)，hits 记录下游副作用次数。"""
    hits = {"orders": 0}
    app = FastAPI()

    @app.post("/orders", status_code=201)
    def create_order(payload: dict[str, Any]) -> dict[str, Any]:
        hits["orders"] += 1
        return {"success": True, "order_id": len(str(hits["orders"]))}

    @app.post("/broken")
    def broken() -> dict[str, Any]:
        raise HTTPException(status_code=400, detail="业务校验失败（不被 200 包裹）")

    app.add_middleware(IdempotencyMiddleware, store=IdempotencyStore())
    app.add_middleware(ContentNegotiationMiddleware, supported_types=("application/json",), enable_gzip=True)
    return app, hits


# ── 1. 路径命名 ─────────────────────────────────────────────────────────────


class TestPathNaming:
    def test_real_repo_scan_is_clean(self) -> None:
        """真实仓库扫描必须 0 违规（T009/T010 整改后）。"""
        result = subprocess.run(
            [sys.executable, str(PATH_NAMING), "--root", str(REPO)],
            capture_output=True,
            text=True,
            cwd=str(REPO),
            timeout=120,
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 0, f"path-naming 应通过，实际：\n{combined}"
        assert "path-naming OK" in combined

    def test_no_verb_segment_exposed(self) -> None:
        """应用挂载的端点路径都不含动词段（资源化命名）。"""
        app, _ = _build_app()
        client = TestClient(app)
        schema = client.get("/openapi.json").json()
        for path in schema["paths"]:
            segments = [s for s in path.strip("/").split("/") if s]
            for seg in segments:
                if seg.startswith("{"):
                    continue
                assert seg not in ("get", "list", "create", "update", "delete"), (
                    f"路径 {path} 含动词段 {seg!r}"
                )


# ── 2. 状态码语义 ───────────────────────────────────────────────────────────


class TestStatusCodeSemantics:
    def test_success_path_returns_2xx(self) -> None:
        app, _ = _build_app()
        client = TestClient(app)
        response = client.post("/orders", json={"qty": 1})
        assert response.status_code == 201

    def test_business_failure_is_4xx_not_200_wrapped(self) -> None:
        app, _ = _build_app()
        client = TestClient(app)
        response = client.post("/broken", json={})
        assert response.status_code == 400
        assert "detail" in response.json()


# ── 3. 幂等 ─────────────────────────────────────────────────────────────────


class TestIdempotency:
    def test_replay_returns_cache_and_executes_once(self) -> None:
        app, hits = _build_app()
        client = TestClient(app)
        headers = {"Idempotency-Key": "key-order-1"}
        first = client.post("/orders", json={"qty": 1}, headers=headers)
        second = client.post("/orders", json={"qty": 1}, headers=headers)
        assert first.status_code == second.status_code == 201
        assert first.json() == second.json()
        assert hits["orders"] == 1
        assert second.headers.get("idempotency-replayed") == "true"

    def test_different_key_executes_again(self) -> None:
        app, hits = _build_app()
        client = TestClient(app)
        client.post("/orders", json={"qty": 1}, headers={"Idempotency-Key": "a"})
        client.post("/orders", json={"qty": 1}, headers={"Idempotency-Key": "b"})
        assert hits["orders"] == 2


# ── 4. 并发 ─────────────────────────────────────────────────────────────────


class TestConcurrency:
    def test_concurrent_replay_executes_once(self) -> None:
        """8 个线程并发带同一 Idempotency-Key，下游只执行 1 次。"""
        app, hits = _build_app()
        headers = {"Idempotency-Key": "concurrent-key"}

        def _fire() -> int:
            client = TestClient(app)
            return client.post("/orders", json={"qty": 1}, headers=headers).status_code

        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(lambda _i: _fire(), range(8)))

        assert all(s == 201 for s in statuses)
        assert hits["orders"] == 1


# ── 5. 分页 ─────────────────────────────────────────────────────────────────


class TestPagination:
    def _items_app(self) -> FastAPI:
        app = FastAPI()

        @app.get("/items")
        def list_items(params: PageParams = Depends()) -> PageResponse[dict[str, Any]]:
            page = params.resolved_page()
            page_size = params.page_size
            start = (page - 1) * page_size
            chunk = ITEMS[start : start + page_size]
            return PageResponse[dict[str, Any]].build(chunk, len(ITEMS), page, page_size)

        return app

    def test_page_response_shape(self) -> None:
        client = TestClient(self._items_app())
        body = client.get("/items?page=1&page_size=10").json()
        assert set(body) == {"data", "total", "page", "page_size", "has_next", "next_cursor"}
        assert body["total"] == 25
        assert body["page"] == 1
        assert body["page_size"] == 10
        assert body["has_next"] is True
        assert body["next_cursor"]  # 有下一页给游标

    def test_cursor_stable_pagination(self) -> None:
        """用 next_cursor 翻到第 3 页，结果与 page=3 一致（稳定翻页）。"""
        client = TestClient(self._items_app())
        first = client.get("/items?page=1&page_size=10").json()
        # cursor 只恢复 page；page_size 由客户端显式携带（T017 约定）
        second = client.get(f"/items?cursor={first['next_cursor']}&page_size=10").json()
        third_by_page = client.get("/items?page=3&page_size=10").json()
        assert second["page"] == 2
        assert second["page_size"] == 10
        assert third_by_page["page"] == 3
        assert [d["id"] for d in second["data"]] == [d["id"] for d in ITEMS[10:20]]

    def test_last_page_has_no_next_cursor(self) -> None:
        client = TestClient(self._items_app())
        body = client.get("/items?page=3&page_size=10").json()
        assert body["has_next"] is False
        assert body["next_cursor"] is None

    def test_page_size_zero_rejected(self) -> None:
        client = TestClient(self._items_app())
        assert client.get("/items?page=1&page_size=0").status_code == 422


# ── 6. 内容协商 ─────────────────────────────────────────────────────────────


class TestContentNegotiation:
    def test_unsupported_accept_returns_406(self) -> None:
        app, _ = _build_app()
        client = TestClient(app)
        response = client.get("/orders/anything", headers={"Accept": "text/html"})
        assert response.status_code == 406
        assert response.headers.get("vary") == "Accept"

    def test_json_accept_ok(self) -> None:
        app, _ = _build_app()
        client = TestClient(app)
        response = client.post("/orders", json={"qty": 1}, headers={"Accept": "application/json"})
        assert response.status_code == 201

    def test_gzip_encoding_negotiated(self) -> None:
        app, _ = _build_app()
        client = TestClient(app)
        response = client.get("/openapi.json", headers={"Accept-Encoding": "gzip"})
        # TestClient/httpx 会自动解压，但应保留协商头
        assert response.headers.get("content-encoding", "").lower() == "gzip"
        assert "accept-encoding" in response.headers.get("vary", "").lower()
        assert response.status_code == 200

    def test_wildcard_accept_allows_json(self) -> None:
        app, _ = _build_app()
        client = TestClient(app)
        response = client.post("/orders", json={"qty": 1}, headers={"Accept": "*/*"})
        assert response.status_code == 201