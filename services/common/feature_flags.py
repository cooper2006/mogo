"""024 T054 (FR-027)：应用侧统一的 feature flag 读取入口。

设计约束（与 deploy/flags/flags.yml 契约对齐）：

1. 默认值来自 `deploy/flags/flags.yml` 里每个 flag 的 `defaultValue` 字段。
2. 运行时可用环境变量覆盖（优先级最高）：`MOGO_FLAG_<NAME_UPPER>`，
   值接受 `1/0/true/false/yes/no`（不区分大小写），其他值原样返回。
3. 未登记、清单缺失、YAML 解析失败时**绝不抛异常**，回退到调用方显式传入的
   `default`；特性开关是发布控制手段，不能因为清单缺失而让应用崩溃。
4. 清单读取带 60s TTL 缓存，避免每个请求都重读磁盘。

三个业务服务（admin-api / chat-api / document-parser）的 `app/core/config.py`
统一通过本模块的 `get_feature_flag` 暴露读取方法（见各 config.py 的
`Settings.feature_flag`），禁止在业务代码里各自读环境变量判断开关。
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FLAGS_ENV_PREFIX = "MOGO_FLAG_"
_CACHE_TTL_SECONDS = 60.0
_CACHE: dict[str, Any] = {"ts": 0.0, "data": {}}

_TRUE_VALUES = {"1", "true", "yes", "on", "y"}
_FALSE_VALUES = {"0", "false", "no", "off", "n", ""}


def _env_key(name: str) -> str:
    return FLAGS_ENV_PREFIX + name.upper().replace("-", "_").replace(".", "_")


def _coerce(raw: str, default: Any) -> Any:
    lowered = raw.strip().lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    # 非布尔语义（如字符串/数字 flag）：尽量还原数字，其余按字符串。
    if default is not None and isinstance(default, bool):
        return raw  # 类型不匹配时保留原始字符串，由调用方决定
    return raw


def flags_manifest_path() -> Path:
    """定位 flags.yml：环境变量优先，其次按仓库相对路径探测。"""
    env = os.environ.get("MOGO_FLAGS_FILE")
    if env:
        return Path(env)
    try:
        # <repo>/services/common/feature_flags.py -> <repo>/deploy/flags/flags.yml
        repo_root = Path(__file__).resolve().parents[2]
    except Exception:
        repo_root = Path(".")
    return repo_root / "deploy" / "flags" / "flags.yml"


def _load_defaults() -> dict[str, Any]:
    path = flags_manifest_path()
    try:
        import yaml  # 延迟导入：仅在校验清单时需要

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # 文件缺失 / YAML 损坏 / 未装 pyyaml
        logger.debug("feature flags manifest unavailable (%s): %s", path, exc)
        return {}
    defaults: dict[str, Any] = {}
    for entry in data.get("flags") or []:
        if isinstance(entry, dict) and entry.get("name"):
            defaults[str(entry["name"])] = entry.get("defaultValue")
    return defaults


def get_feature_flag(name: str, default: Any = False) -> Any:
    """读取一个特性开关的当前值。

    - 环境变量 `MOGO_FLAG_<NAME_UPPER>` 覆盖清单默认值。
    - 未在清单登记时回退到 `default`（默认 False，保守关闭）。
    """
    if not name:
        return default
    raw = os.environ.get(_env_key(name))
    if raw is not None:
        return _coerce(raw, default)

    now = time.monotonic()
    if now - float(_CACHE["ts"]) > _CACHE_TTL_SECONDS:
        _CACHE["data"] = _load_defaults()
        _CACHE["ts"] = now
    return _CACHE["data"].get(name, default)


def feature_flag_names() -> list[str]:
    """返回清单中登记的全部开关名（诊断/列表用）。"""
    defaults = _load_defaults()
    return sorted(defaults)


def is_enabled(name: str, default: bool = False) -> bool:
    """布尔快捷入口：把返回值规范成 bool。"""
    return bool(get_feature_flag(name, default))


def resolve_flag(name: str, default: Any = False) -> Any:
    """给各服务 `app/core/config.py` 用的兜底入口。

    正常情况下由 `_load_config_entrypoint()` 把本模块的 `resolve_flag` 交给
    `Settings.feature_flag`；此处直接调用等价于同一条读取路径。共享模块加载
    失败时仍保持「仅环境变量 + 显式 default」语义，绝不抛异常。
    """
    try:
        return get_feature_flag(name, default)
    except Exception:
        pass
    raw = os.environ.get(_env_key(name))
    if raw is None:
        return default
    return _coerce(raw, default)


def _load_config_entrypoint():
    """供 config.py 引导：定位并加载本共享模块，返回其 resolve_flag。

    顺序：先试常规 import（调用方 PYTHONPATH 已含 services/），失败则从
    config.py 所在目录逐级向上搜索 `common/feature_flags.py`（覆盖容器内
    /app/<svc> 布局与本地 <repo>/services/<svc> 布局）。全程不抛异常。
    """
    try:
        import common.feature_flags  # type: ignore  # noqa: F401

        return resolve_flag
    except Exception:
        pass
    try:
        import importlib.util
        import sys

        probe = Path(__file__).resolve()
        for ancestor in [probe, *probe.parents]:
            candidate = ancestor / "common" / "feature_flags.py"
            if candidate.is_file():
                spec = importlib.util.spec_from_file_location(
                    "mogo_common_feature_flags", str(candidate)
                )
                module = importlib.util.module_from_spec(spec)
                sys.modules["mogo_common_feature_flags"] = module
                spec.loader.exec_module(module)  # type: ignore[union-attr]
                return module.resolve_flag
    except Exception as exc:  # 加载失败回退 env-only
        logger.debug("feature flag entrypoint unavailable: %s", exc)
    return resolve_flag