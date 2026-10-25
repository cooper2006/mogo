"""025 FR-13 (T025)：限流维度与阈值配置加载器（QF-237~QF-240）。

读取 `app/config/rate_limit.yaml`，供 T024 的限流中间件使用：
- `dimensions`：各维度（ip / tenant / user / endpoint）的滑动窗口规则
  `limit`（窗口内最大请求数）+ `window`（窗口秒数）。
- `overrides`：按路径前缀放宽（命中最长前缀者生效），替换该维度的规则。

环境变量 `MOGO_RATE_LIMIT_<DIM>_LIMIT` / `MOGO_RATE_LIMIT_<DIM>_WINDOW`
（如 `MOGO_RATE_LIMIT_IP_LIMIT`）可逐项覆盖；yaml 缺失或损坏时回退到
内置默认值（IP:100/min、tenant:1000/min、user:100/min、endpoint:500/min），
保证中间件在配置不完整时仍能启动（限流宁宽勿误杀）。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping

import yaml

logger = logging.getLogger(__name__)

# 内置默认值：与 rate_limit.yaml 保持一致（yaml 缺失时兜底）
_DEFAULT_DIMENSIONS: dict[str, dict[str, int]] = {
    "ip": {"limit": 100, "window": 60},
    "tenant": {"limit": 1000, "window": 60},
    "user": {"limit": 100, "window": 60},
    "endpoint": {"limit": 500, "window": 60},
}

DEFAULT_CONFIG_PATH = Path(__file__).with_name("rate_limit.yaml")


@dataclass(frozen=True)
class RateLimitRule:
    """单个维度的滑动窗口规则。"""

    limit: int
    window: int  # 秒

    def validate(self) -> "RateLimitRule":
        """限制必须为正数，否则回退到 1 次 / 60s 的最小安全值。"""
        return replace(
            self,
            limit=self.limit if self.limit > 0 else 1,
            window=self.window if self.window > 0 else 60,
        )


@dataclass(frozen=True)
class RateLimitConfig:
    """解析后的限流配置。`rule_for()` 返回叠加路径级覆盖后的规则。"""

    dimensions: Mapping[str, RateLimitRule] = field(default_factory=dict)
    overrides: Mapping[str, Mapping[str, RateLimitRule]] = field(default_factory=dict)

    def rule_for(self, dimension: str, path: str) -> RateLimitRule | None:
        """按维度 + 请求路径返回生效规则（匹配最长前缀的 override）。"""
        base = self.dimensions.get(dimension)
        if base is None:
            return None
        best_prefix: str | None = None
        best: Mapping[str, RateLimitRule] | None = None
        for prefix, rules in self.overrides.items():
            if path.startswith(prefix) and (best_prefix is None or len(prefix) > len(best_prefix)):
                best_prefix = prefix
                best = rules
        if best and dimension in best:
            return best[dimension]
        return base

    def dimensions_sorted(self) -> list[str]:
        """维度名排序（稳定顺序：endpoint, ip, tenant, user）。"""
        return sorted(self.dimensions)


def _coerce_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _rule_from(raw: object) -> RateLimitRule | None:
    if not isinstance(raw, dict):
        return None
    limit = _coerce_int(raw.get("limit"))
    window = _coerce_int(raw.get("window"))
    if limit is None and window is None:
        return None
    return RateLimitRule(
        limit=limit if limit is not None else _DEFAULT_DIMENSIONS.get("ip", {}).get("limit", 100),
        window=window if window is not None else 60,
    ).validate()


def _apply_env(dimensions: dict[str, RateLimitRule]) -> dict[str, RateLimitRule]:
    out: dict[str, RateLimitRule] = {}
    for name, rule in dimensions.items():
        limit = _coerce_int(os.environ.get(f"MOGO_RATE_LIMIT_{name.upper()}_LIMIT"))
        window = _coerce_int(os.environ.get(f"MOGO_RATE_LIMIT_{name.upper()}_WINDOW"))
        out[name] = replace(
            rule,
            limit=limit if limit is not None and limit > 0 else rule.limit,
            window=window if window is not None and window > 0 else rule.window,
        )
    return out


def load_rate_limit_config(config_path: Path | None = None) -> RateLimitConfig:
    """加载限流配置。

    - yaml 存在且可解析：以 yaml 为基线（缺维度用内置默认值补齐）；
    - yaml 缺失/损坏：使用内置默认值（并保留提示）；
    - 环境变量覆盖：`MOGO_RATE_LIMIT_<DIM>_LIMIT` / `_WINDOW`。
    """
    raw: dict = {}
    path = config_path or DEFAULT_CONFIG_PATH
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            raw = data if isinstance(data, dict) else {}
        except yaml.YAMLError:
            logger.warning("rate_limit.yaml 解析失败，回退到内置默认值: %s", path)
            raw = {}
    else:
        logger.warning("未找到限流配置文件，使用内置默认值: %s", path)

    dimensions_raw = raw.get("dimensions") or {}
    dimensions: dict[str, RateLimitRule] = {}
    for name, rule in _DEFAULT_DIMENSIONS.items():
        parsed = _rule_from(dimensions_raw.get(name)) if isinstance(dimensions_raw, dict) else None
        dimensions[name] = parsed if parsed is not None else RateLimitRule(**rule)

    overrides_raw = raw.get("overrides") or {}
    overrides: dict[str, dict[str, RateLimitRule]] = {}
    if isinstance(overrides_raw, dict):
        for prefix, rules in overrides_raw.items():
            if not isinstance(prefix, str) or not isinstance(rules, dict):
                continue
            cleaned = {k: v for k, v in rules.items() if _rule_from(v) is not None}
            if cleaned:
                overrides[prefix] = {k: _rule_from(v) for k, v in cleaned.items()}  # type: ignore[misc]

    return RateLimitConfig(dimensions=_apply_env(dimensions), overrides=overrides)