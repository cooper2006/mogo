"""IM 意图路由（051 B2 / T008 协议 / FR-007，OQ-4 已定）。

确定性路由（YAGNI：不做 LLM 意图分类首期承诺）：

* 一个 IM 渠道绑定**多个**员工，每条绑定带**关键词列表** + **默认标记**；
* 消息进入时按绑定序求值，**首个命中关键词**的员工胜出；
* 未命中任何关键词 → 落**默认员工**；无默认员工 → 返回 ``None``，由调用方
  回落既有无员工会话行为（不拒绝消息，FR-007）；
* 路由结果落会话 ``employee_id`` 与审计（调用方接线）。

模块 DB-free（纯函数 + dataclass），规则求值 100% 确定性（SC-004）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: 渠道-员工绑定集合名（027 门面双后端；跨服务共享）。
CHANNEL_EMPLOYEE_BINDINGS_COLLECTION = "channel_employee_bindings"

#: 路由结果：命中员工 / 落默认 / 回落（无默认员工）。
ROUTE_MATCHED = "matched"
ROUTE_DEFAULT = "default"
ROUTE_FALLBACK = "fallback"


class RoutingRuleError(ValueError):
    """路由规则非法（空员工 / 空关键词 / 多默认标记）。"""


@dataclass
class ChannelEmployeeBinding:
    """渠道-员工绑定与路由规则（T008 协议）。

    一条绑定 = 渠道 + 员工 + 关键词列表 + 默认标记。同一渠道内至多一条
    默认绑定（``_validate`` fail-closed）。
    """

    channel: str
    employee_id: str
    keywords: list[str] = field(default_factory=list)
    is_default: bool = False
    tenant_id: str = "default"
    binding_id: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not str(self.channel or "").strip():
            raise RoutingRuleError("binding.channel must not be empty")
        if not str(self.employee_id or "").strip():
            raise RoutingRuleError("binding.employee_id must not be empty")
        self.keywords = [str(k).strip().lower() for k in (self.keywords or []) if str(k).strip()]

    def as_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "employee_id": self.employee_id,
            "keywords": list(self.keywords),
            "is_default": bool(self.is_default),
            "tenant_id": self.tenant_id,
            "binding_id": self.binding_id,
            "updated_at": self.updated_at,
        }


def validate_bindings(bindings: list[ChannelEmployeeBinding]) -> None:
    """规则集合校验：同渠道至多一条默认绑定（fail-closed）。"""
    per_channel_default: dict[str, str] = {}
    for binding in bindings:
        if not binding.is_default:
            continue
        existing = per_channel_default.get(binding.channel)
        if existing is not None and existing != binding.employee_id:
            raise RoutingRuleError(
                f"channel {binding.channel!r} has more than one default employee "
                f"({existing!r} vs {binding.employee_id!r})"
            )
        per_channel_default[binding.channel] = binding.employee_id


def resolve_employee(
    bindings: list[ChannelEmployeeBinding],
    text: str,
) -> tuple[str | None, str]:
    """确定性路由：命中关键词 → 员工；未命中 → 默认；无默认 → (None, fallback)。

    Returns:
        ``(employee_id, route_kind)``。``route_kind`` 为 ROUTE_MATCHED /
        ROUTE_DEFAULT / ROUTE_FALLBACK。无绑定或未命中且无默认 → (None, fallback)。
    """
    validate_bindings(bindings)
    haystack = str(text or "").strip().lower()
    default_id: str | None = None
    for binding in bindings:
        if binding.is_default:
            default_id = binding.employee_id
            continue
        for keyword in binding.keywords:
            if keyword and keyword in haystack:
                return binding.employee_id, ROUTE_MATCHED
    if default_id is not None:
        return default_id, ROUTE_DEFAULT
    return None, ROUTE_FALLBACK


__all__ = [
    "CHANNEL_EMPLOYEE_BINDINGS_COLLECTION",
    "ROUTE_MATCHED",
    "ROUTE_DEFAULT",
    "ROUTE_FALLBACK",
    "ChannelEmployeeBinding",
    "RoutingRuleError",
    "resolve_employee",
    "validate_bindings",
]
