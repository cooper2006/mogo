"""025 FR-5 (T014) — 载荷限制配置加载器行为测试。

验证 `app/config/payload_limits.py`：
- 默认值来自 payload_limits.yaml（10 MiB / 深度 16 / 数组 10000 / 字符串 1 MiB）
- `for_path()` 按最长前缀应用 overrides
- 环境变量 `MOGO_PAYLOAD_LIMITS_<KEY>` 逐项覆盖
- yaml 缺失或损坏时回退到内置默认值（不 crash）
"""

from __future__ import annotations

import pytest

from app.config.payload_limits import DEFAULT_CONFIG_PATH, load_payload_limits


class TestDefaults:
    def test_loads_yaml_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MOGO_PAYLOAD_LIMITS_MAX_BYTES", raising=False)
        limits = load_payload_limits(DEFAULT_CONFIG_PATH)
        assert limits.max_bytes == 10 * 1024 * 1024
        assert limits.max_depth == 16
        assert limits.max_array_length == 10_000
        assert limits.max_string_length == 1024 * 1024

    def test_override_registered_for_internal(self) -> None:
        limits = load_payload_limits(DEFAULT_CONFIG_PATH)
        assert limits.overrides.get("/internal", {}).get("max_bytes") == 20 * 1024 * 1024


class TestForPath:
    def test_longest_prefix_wins(self) -> None:
        limits = load_payload_limits(DEFAULT_CONFIG_PATH)
        got = limits.for_path("/internal/personal-knowledge/documents")
        assert got.max_bytes == 20 * 1024 * 1024

    def test_shorter_prefix_still_applies(self) -> None:
        limits = load_payload_limits(DEFAULT_CONFIG_PATH)
        got = limits.for_path("/internal/users")
        assert got.max_bytes == 20 * 1024 * 1024

    def test_unmatched_path_unchanged(self) -> None:
        limits = load_payload_limits(DEFAULT_CONFIG_PATH)
        got = limits.for_path("/v1/documents")
        assert got.max_bytes == 10 * 1024 * 1024
        assert got.max_depth == 16


class TestEnvOverride:
    def test_env_overrides_yaml(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MOGO_PAYLOAD_LIMITS_MAX_BYTES", "4096")
        limits = load_payload_limits(DEFAULT_CONFIG_PATH)
        assert limits.max_bytes == 4096

    def test_blank_env_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MOGO_PAYLOAD_LIMITS_MAX_BYTES", "")
        limits = load_payload_limits(DEFAULT_CONFIG_PATH)
        assert limits.max_bytes == 10 * 1024 * 1024

    def test_invalid_env_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MOGO_PAYLOAD_LIMITS_MAX_DEPTH", "not-a-number")
        limits = load_payload_limits(DEFAULT_CONFIG_PATH)
        assert limits.max_depth == 16


class TestFallback:
    def test_missing_yaml_falls_back(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MOGO_PAYLOAD_LIMITS_MAX_BYTES", raising=False)
        limits = load_payload_limits(tmp_path / "nope.yaml")
        assert limits.max_bytes == 10 * 1024 * 1024
        assert limits.max_depth == 16

    def test_broken_yaml_falls_back(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("limits: [unclosed\n", encoding="utf-8")
        limits = load_payload_limits(bad)
        assert limits.max_bytes == 10 * 1024 * 1024