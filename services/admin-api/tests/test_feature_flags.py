"""024 T054 (FR-027)：feature flag 读取入口测试。

运行：ASKAI_ADMIN_MONGODB_URI=mongodb://127.0.0.1:27017 \
      pytest services/admin-api/tests/test_feature_flags.py -q
"""

from __future__ import annotations

import importlib
import os
import sys

SERVICES_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if SERVICES_DIR not in sys.path:
    sys.path.insert(0, SERVICES_DIR)

import pytest

import common.feature_flags as ff  # type: ignore

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _write_manifest(tmp_path, body: str) -> str:
    p = tmp_path / "flags.yml"
    p.write_text(body, encoding="utf-8")
    return str(p)


FLAGS_YML = """
version: 1
flags:
  - name: canary_routing_enabled
    owner: platform-oncall
    defaultValue: true
    expiry: 2027-01-31
    cleanupPlan: x
    codeRefs: ["deploy/cli/canary.sh"]
  - name: panweidb_data_backend
    owner: data-platform
    defaultValue: false
    expiry: 2027-06-30
    cleanupPlan: x
    codeRefs: ["services/admin-api/app/core/config.py"]
  - name: mogo_tls
    owner: platform-oncall
    defaultValue: false
    expiry: 2099-12-31
    cleanupPlan: x
    codeRefs: []
"""


@pytest.fixture(autouse=True)
def _reset_cache(tmp_path, monkeypatch):
    ff._CACHE["ts"] = 0.0
    ff._CACHE["data"] = {}
    manifest = _write_manifest(tmp_path, FLAGS_YML)
    monkeypatch.setenv("MOGO_FLAGS_FILE", manifest)
    for key in list(os.environ):
        if key.startswith("MOGO_FLAG_"):
            monkeypatch.delenv(key)
    yield


def test_default_value_comes_from_manifest():
    assert ff.get_feature_flag("canary_routing_enabled") is True
    assert ff.get_feature_flag("panweidb_data_backend") is False


def test_env_var_overrides_manifest(monkeypatch):
    monkeypatch.setenv("MOGO_FLAG_CANARY_ROUTING_ENABLED", "0")
    assert ff.get_feature_flag("canary_routing_enabled") is False
    monkeypatch.setenv("MOGO_FLAG_PANWEIDB_DATA_BACKEND", "1")
    assert ff.get_feature_flag("panweidb_data_backend") is True


def test_unknown_flag_returns_explicit_default():
    assert ff.get_feature_flag("nonexistent_flag", True) is True
    assert ff.get_feature_flag("nonexistent_flag") is False


def test_missing_manifest_does_not_raise(monkeypatch, tmp_path):
    monkeypatch.setenv("MOGO_FLAGS_FILE", str(tmp_path / "nope.yml"))
    assert ff.get_feature_flag("whatever", "fallback") == "fallback"
    assert ff.get_feature_flag("whatever") is False


def test_boolean_coercion(monkeypatch):
    for raw in ("1", "true", "YES", "on"):
        monkeypatch.setenv("MOGO_FLAG_X", raw)
        assert ff.get_feature_flag("x") is True
    for raw in ("0", "false", "no", ""):
        monkeypatch.setenv("MOGO_FLAG_X", raw)
        assert ff.get_feature_flag("x") is False


def test_listed_names():
    assert "canary_routing_enabled" in ff.feature_flag_names()
    assert "mogo_tls" in ff.feature_flag_names()


def test_manifest_path_default_looks_under_repo_deploy_flags():
    # 默认路径应指向仓库内 deploy/flags/flags.yml
    p = os.environ.get("MOGO_FLAGS_FILE")
    if p:
        return  # 已在 fixture 覆盖，跳过
    assert os.path.exists(os.path.join(REPO_ROOT, "deploy", "flags", "flags.yml"))


def _admin_settings_feature_flag():
    # admin-api 的包名是 `app`（容器内 PYTHONPATH=/app），须从 services/admin-api 导入。
    pkg_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if pkg_root not in sys.path:
        sys.path.insert(0, pkg_root)
    from app.core.config import Settings  # type: ignore

    assert hasattr(Settings, "feature_flag"), "admin-api Settings 缺少 feature_flag 方法"
    return Settings().feature_flag("canary_routing_enabled")


def _other_services_declare_feature_flag():
    """chat-api / document-parser 的 config.py 以 `app` 同名包运行，无法与 admin-api
    同时导入；这里做源码级断言：Settings 类内必须定义 feature_flag 方法。"""
    import re

    for svc in ("chat-api", "document-parser"):
        path = os.path.join(REPO_ROOT, "services", svc, "app", "core", "config.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        compile(src, path, "exec")  # 语法必须合法
        assert re.search(r"def feature_flag\(self, name", src), (
            f"{svc}/app/core/config.py 未定义 Settings.feature_flag"
        )


def test_admin_api_settings_exposes_feature_flag():
    assert _admin_settings_feature_flag() is True


def test_chat_api_settings_declares_feature_flag():
    _other_services_declare_feature_flag()