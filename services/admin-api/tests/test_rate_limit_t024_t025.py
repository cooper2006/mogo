"""025 FR-13 (T024/T025)：限流配置加载 + 限流中间件行为测试（QF-237~240）。

T025 配置加载器用真实 yaml + tmp_path 缺失/损坏场景；T024 中间件用纯 ASGI
手动驱动（不依赖 TestClient，便于指定 client/state），内存 store 验证：
超配额 429 + Retry-After + detail 五字段、滑动窗口恢复、维度隔离、
override 生效、store 结构、backend=memory、config 空维度放行。
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from app.config.rate_limit import (
    DEFAULT_CONFIG_PATH,
    RateLimitConfig,
    RateLimitRule,
    load_rate_limit_config,
)
from app.middleware.rate_limit import RateLimitMiddleware, RateLimitStore

OK_BODY = b'{"ok":true}'


async def _ok_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json; charset=utf-8")],
        }
    )
    await send({"type": "http.response.body", "body": OK_BODY})


def _make_scope(path: str = "/orders", method: str = "GET", client_ip: str = "1.1.1.1",
                state: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "type": "http",
        "method": method,
        "path": path,
        "client": (client_ip, 12345),
        "state": dict(state or {}),
        "headers": [],
    }


async def _run(middleware: Any, scope: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await middleware(scope, receive, send)
    return messages


def _headers(messages: list[dict[str, Any]]) -> dict[bytes, bytes]:
    start = messages[0]
    return {k.lower(): v for k, v in start.get("headers", [])}


def _status(messages: list[dict[str, Any]]) -> int:
    return int(messages[0]["status"])


def _body(messages: list[dict[str, Any]]) -> dict[str, Any]:
    return json.loads(messages[1]["body"])


def _middleware(**kwargs: Any) -> RateLimitMiddleware:
    kwargs.setdefault("store", RateLimitStore())
    return RateLimitMiddleware(_ok_app, **kwargs)


# ── T025 配置加载 ────────────────────────────────────────────────────────────


class TestConfigLoader:
    def test_default_dimensions_from_yaml(self) -> None:
        config = load_rate_limit_config()
        assert config.rule_for("ip", "/x").limit == 100
        assert config.rule_for("ip", "/x").window == 60
        assert config.rule_for("tenant", "/x").limit == 1000
        assert config.rule_for("user", "/x").limit == 100
        assert config.rule_for("endpoint", "/x").limit == 500

    def test_override_longest_prefix_wins(self) -> None:
        config = load_rate_limit_config()
        # /internal/personal-knowledge 更长前缀 → 2000；/internal → 2000；其它 → 500
        assert config.rule_for("endpoint", "/internal/personal-knowledge/x").limit == 2000
        assert config.rule_for("endpoint", "/internal/x").limit == 2000
        assert config.rule_for("endpoint", "/public/x").limit == 500

    def test_unknown_dimension_returns_none(self) -> None:
        config = load_rate_limit_config()
        assert config.rule_for("nope", "/x") is None

    def test_missing_yaml_falls_back_to_defaults(self, tmp_path: Path, monkeypatch: Any) -> None:
        monkeypatch.setattr("app.config.rate_limit.DEFAULT_CONFIG_PATH", tmp_path / "missing.yaml")
        config = load_rate_limit_config(tmp_path / "missing.yaml")
        assert config.rule_for("ip", "/x").limit == 100
        assert config.rule_for("endpoint", "/x").limit == 500

    def test_corrupt_yaml_falls_back_to_defaults(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("dimensions: [unclosed", encoding="utf-8")
        config = load_rate_limit_config(bad)
        assert config.rule_for("ip", "/x").limit == 100

    def test_env_override(self, tmp_path: Path, monkeypatch: Any) -> None:
        good = tmp_path / "ok.yaml"
        good.write_text(
            "dimensions:\n  ip: {limit: 100, window: 60}\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("MOGO_RATE_LIMIT_IP_LIMIT", "7")
        monkeypatch.setenv("MOGO_RATE_LIMIT_IP_WINDOW", "5")
        config = load_rate_limit_config(good)
        rule = config.rule_for("ip", "/x")
        assert rule.limit == 7
        assert rule.window == 5

    def test_config_path_exists(self) -> None:
        assert DEFAULT_CONFIG_PATH.exists()

    def test_dimensions_sorted(self) -> None:
        config = load_rate_limit_config()
        assert config.dimensions_sorted() == ["endpoint", "ip", "tenant", "user"]


# ── T024 中间件 ──────────────────────────────────────────────────────────────


class TestStore:
    def test_backend_is_memory_without_redis(self) -> None:
        assert RateLimitStore().backend == "memory"

    def test_hit_shape_and_limit(self) -> None:
        store = RateLimitStore()
        rule = RateLimitRule(limit=2, window=60)
        first = store.hit("ip:1.1.1.1", rule)
        assert first["allowed"] is True
        assert first["remaining"] == 1
        assert first["limit"] == 2
        assert first["window"] == 60
        assert first["reset_at"] > first["remaining"]  # 时间戳数值
        second = store.hit("ip:1.1.1.1", rule)
        assert second["allowed"] is True
        third = store.hit("ip:1.1.1.1", rule)
        assert third["allowed"] is False
        assert third["remaining"] == 0

    def test_sliding_window_recovers_after_expiry(self) -> None:
        store = RateLimitStore()
        rule = RateLimitRule(limit=3, window=1)
        for _ in range(3):
            assert store.hit("ip:1.1.1.1", rule)["allowed"] is True
        assert store.hit("ip:1.1.1.1", rule)["allowed"] is False
        time.sleep(1.1)
        assert store.hit("ip:1.1.1.1", rule)["allowed"] is True  # 旧记录已滑出


class TestMiddleware:
    def test_under_limit_passes_through(self) -> None:
        config = RateLimitConfig(dimensions={"ip": RateLimitRule(limit=100, window=60)})
        mw = _middleware(config=config)
        messages = asyncio.run(_run(mw, _make_scope()))
        assert _status(messages) == 200

    def test_over_limit_returns_429_with_retry_after(self) -> None:
        config = RateLimitConfig(dimensions={"ip": RateLimitRule(limit=1, window=60)})
        mw = _middleware(config=config)
        assert asyncio.run(_run(mw, _make_scope()))[0]["status"] == 200
        messages = asyncio.run(_run(mw, _make_scope()))
        assert _status(messages) == 429
        headers = _headers(messages)
        # 刚超配额：窗口内最早记录即将滑出，Retry-After 为 1 秒级
        assert int(headers[b"retry-after"]) >= 1
        assert int(headers[b"x-ratelimit-limit"]) == 1
        assert int(headers[b"x-ratelimit-remaining"]) == 0

    def test_429_detail_has_required_fields(self) -> None:
        config = RateLimitConfig(dimensions={"ip": RateLimitRule(limit=1, window=60)})
        mw = _middleware(config=config)
        asyncio.run(_run(mw, _make_scope()))
        detail = _body(asyncio.run(_run(mw, _make_scope())))["detail"]
        assert detail["code"] == "RATE_LIMITED"
        assert set(detail) == {"code", "message", "limit", "remaining", "window", "reset_at", "dimension"}
        assert detail["limit"] == 1
        assert detail["remaining"] == 0
        assert detail["window"] == 60
        assert "T" in detail["reset_at"]  # ISO 时间
        assert detail["dimension"] == "ip"

    def test_per_ip_isolation(self) -> None:
        config = RateLimitConfig(dimensions={"ip": RateLimitRule(limit=1, window=60)})
        mw = _middleware(config=config)
        asyncio.run(_run(mw, _make_scope(client_ip="1.1.1.1")))
        # 同 IP 第二发 → 429；不同 IP → 200
        assert _status(asyncio.run(_run(mw, _make_scope(client_ip="1.1.1.1")))) == 429
        assert _status(asyncio.run(_run(mw, _make_scope(client_ip="2.2.2.2")))) == 200

    def test_tenant_dimension_uses_state(self) -> None:
        config = RateLimitConfig(dimensions={"tenant": RateLimitRule(limit=1, window=60)})
        mw = _middleware(config=config)
        asyncio.run(_run(mw, _make_scope(state={"tenant_id": "t1"})))
        assert _status(asyncio.run(_run(mw, _make_scope(state={"tenant_id": "t1"})))) == 429
        assert _status(asyncio.run(_run(mw, _make_scope(state={"tenant_id": "t2"})))) == 200

    def test_endpoint_dimension_uses_path(self) -> None:
        config = RateLimitConfig(dimensions={"endpoint": RateLimitRule(limit=1, window=60)})
        mw = _middleware(config=config)
        asyncio.run(_run(mw, _make_scope(path="/orders")))
        assert _status(asyncio.run(_run(mw, _make_scope(path="/orders")))) == 429
        assert _status(asyncio.run(_run(mw, _make_scope(path="/items")))) == 200

    def test_override_applied_for_path(self) -> None:
        """路径命中 override 使用放宽后的规则（limit 大 → 不超配额）。"""
        config = RateLimitConfig(
            dimensions={"endpoint": RateLimitRule(limit=1, window=60)},
            overrides={"/internal": {"endpoint": RateLimitRule(limit=100, window=60)}},
        )
        mw = _middleware(config=config)
        # 普通路径：第 2 发超配额；/internal：多连发都放行
        asyncio.run(_run(mw, _make_scope(path="/orders")))
        assert _status(asyncio.run(_run(mw, _make_scope(path="/orders")))) == 429
        for _ in range(3):
            assert _status(asyncio.run(_run(mw, _make_scope(path="/internal/x")))) == 200

    def test_empty_config_passes_all(self) -> None:
        mw = _middleware(config=RateLimitConfig(dimensions={}))
        for _ in range(3):
            assert _status(asyncio.run(_run(mw, _make_scope()))) == 200

    def test_dimensions_subset_applied(self) -> None:
        """只启用 ip 维度时，tenant 超配额不影响。"""
        config = RateLimitConfig(
            dimensions={
                "ip": RateLimitRule(limit=100, window=60),
                "tenant": RateLimitRule(limit=1, window=60),
            }
        )
        mw = _middleware(config=config, dimensions=("ip",))
        # tenant 已超，但 ip 维度未启用 → 仍放行
        asyncio.run(_run(mw, _make_scope(state={"tenant_id": "t1"})))
        assert _status(asyncio.run(_run(mw, _make_scope(state={"tenant_id": "t1"})))) == 200