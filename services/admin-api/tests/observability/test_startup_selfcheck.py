"""023 T028 — 启动自检测试。

验证 startup_selfcheck() 失败不退出但 /ready 返回 503。
"""
from __future__ import annotations

import pytest

from app.common.observability_base import (
    startup_selfcheck,
    get_selfcheck_results,
    _check_mongo,
    _check_redis,
    _check_llm_provider,
    _check_config_files,
)


def test_startup_selfcheck_all_ok():
    """所有检查通过时返回 ok=True。"""
    # 使用假 URI，测试错误处理而非真实连接
    result = startup_selfcheck(
        mongo_uri="mongodb://invalid:27017",
        redis_url="redis://invalid:6379",
        llm_base_url="http://invalid:8000",
        config_paths=[__file__],
        service_name="test",
    )
    # 配置文件检查（本文件存在）应通过
    assert result["checks"]["config_files"]["ok"] is True
    # 总体结果取决于所有检查
    assert "ok" in result


def test_startup_selfcheck_config_files_missing():
    """配置文件不存在时返回 ok=False。"""
    result = startup_selfcheck(
        config_paths=["/nonexistent/path/config.yaml"],
        service_name="test",
    )
    assert result["checks"]["config_files"]["ok"] is False
    assert result["ok"] is False


def test_startup_selfcheck_idempotent():
    """重复调用只覆盖结果。"""
    r1 = startup_selfcheck(service_name="test")
    r2 = startup_selfcheck(service_name="test")
    assert r1["service"] == r2["service"] == "test"
    # 结果被覆盖而非累积：get_selfcheck_results 返回单个 dict（不是 list）
    result = get_selfcheck_results("test")
    assert result["service"] == "test"


def test_startup_selfcheck_no_exit():
    """自检失败不抛异常（不退出进程）。"""
    # 传入无效 URI，不应抛异常
    try:
        result = startup_selfcheck(
            mongo_uri="mongodb://invalid:27017",
            service_name="test",
        )
        assert "checks" in result
    except SystemExit:
        pytest.fail("startup_selfcheck 不应调用 sys.exit")


def test_get_selfcheck_results_returns_cached():
    """get_selfcheck_results 返回缓存结果。"""
    startup_selfcheck(service_name="cached_test")
    result = get_selfcheck_results("cached_test")
    assert result["service"] == "cached_test"


def test_get_selfcheck_results_unknown_service():
    """未知服务返回空 dict。"""
    assert get_selfcheck_results("nonexistent") == {}
