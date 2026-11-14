"""025 FR-5 (T014)：载荷限制配置加载器（QF-211）。

读取 `app/config/payload_limits.yaml`，供 T013 的载荷限制中间件使用：
- `max_bytes`        请求体字节数上限（超限 413）
- `max_depth`        JSON 嵌套最大深度（超限 422）
- `max_array_length` 单个数组最大元素数（超限 422）
- `max_string_length` 单个字符串最大长度（超限 422）
- `overrides`        按路径前缀的路由级覆盖，命中最长前缀者生效

环境变量 `MOGO_PAYLOAD_LIMITS_<KEY>`（如 `MOGO_PAYLOAD_LIMITS_MAX_BYTES`）可逐项
覆盖；未设置时用 yaml 中的值；yaml 缺失或损坏时回退到内置默认值，
保证中间件在配置不完整时仍能启动（宁可宽松也不拒绝服务）。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping

import yaml

logger = logging.getLogger(__name__)

# 内置默认值：与 payload_limits.yaml 保持一致（yaml 缺失时兜底）
_DEFAULTS = {
    "max_bytes": 10 * 1024 * 1024,  # 10 MiB
    "max_depth": 16,
    "max_array_length": 10_000,
    "max_string_length": 1024 * 1024,  # 1 MiB
}

DEFAULT_CONFIG_PATH = Path(__file__).with_name("payload_limits.yaml")

# 允许通过环境变量覆盖的键 -> yaml 键名（同名字段）
_OVERRIDABLE = ("max_bytes", "max_depth", "max_array_length", "max_string_length")


@dataclass(frozen=True)
class PayloadLimits:
    """解析后的载荷限制。`for_path()` 会返回叠加路径级覆盖后的副本。"""

    max_bytes: int = 10 * 1024 * 1024
    max_depth: int = 16
    max_array_length: int = 10_000
    max_string_length: int = 1024 * 1024
    overrides: Mapping[str, Mapping[str, int]] = field(default_factory=dict)

    def for_path(self, path: str) -> "PayloadLimits":
        """按请求路径返回生效的限制（匹配最长前缀的 override）。"""
        best_prefix: str | None = None
        best: Mapping[str, int] = {}
        for prefix, values in self.overrides.items():
            if path.startswith(prefix) and (best_prefix is None or len(prefix) > len(best_prefix)):
                best_prefix = prefix
                best = values
        if not best:
            return self
        kwargs = {key: value for key, value in best.items() if key in _OVERRIDABLE}
        return replace(self, **kwargs) if kwargs else self


def _coerce_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _apply_env(limits: PayloadLimits) -> PayloadLimits:
    kwargs: dict[str, int] = {}
    for key in _OVERRIDABLE:
        raw = os.environ.get(f"MOGO_PAYLOAD_LIMITS_{key.upper()}")
        if raw is None or raw.strip() == "":
            continue
        parsed = _coerce_int(raw)
        if parsed is not None and parsed > 0:
            kwargs[key] = parsed
    return replace(limits, **kwargs) if kwargs else limits


def load_payload_limits(config_path: Path | None = None) -> PayloadLimits:
    """加载载荷限制配置。

    - yaml 存在且可解析：以 yaml 为基线；
    - yaml 缺失/损坏：使用内置默认值（并保留 yaml 损坏的提示）；
    - 环境变量覆盖：`MOGO_PAYLOAD_LIMITS_<KEY>` 逐项覆盖。
    """
    raw: dict = {}
    path = config_path or DEFAULT_CONFIG_PATH
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            raw = data.get("limits", {}) if isinstance(data, dict) else {}
        except yaml.YAMLError:
            logger.warning("payload_limits.yaml 解析失败，回退到内置默认值: %s", path)
            raw = {}
    else:
        logger.warning("未找到载荷限制配置文件，使用内置默认值: %s", path)

    kwargs: dict[str, int] = {}
    for key in _OVERRIDABLE:
        value = _coerce_int(raw.get(key))
        if value is None:
            value = _DEFAULTS[key]
        kwargs[key] = value

    overrides_raw = raw.get("overrides") or {}
    overrides: dict[str, dict[str, int]] = {}
    if isinstance(overrides_raw, dict):
        for prefix, values in overrides_raw.items():
            if not isinstance(prefix, str) or not isinstance(values, dict):
                continue
            cleaned = {k: v for k, v in values.items() if k in _OVERRIDABLE and _coerce_int(v) is not None}
            if cleaned:
                overrides[prefix] = {k: int(v) for k, v in cleaned.items()}  # type: ignore[assignment]

    limits = PayloadLimits(**kwargs, overrides=overrides)
    return _apply_env(limits)