"""056 R-7 — 审批内核迁移期旁路适配器（影子双写）。

三套历史状态机（admin ``gate_approvals`` / 037 ``portal_requests`` / 050
``orchestration_runs``）在迁移期仍是**唯一仲裁源**；本模块把它们的签发/决策
镜像到 :class:`app.common.approval_kernel.ApprovalKernel`，用于：

* 统一审批待办视图（``list_todos`` 聚合三来源）；
* 跨能力审计链（所有审批生命周期事件汇入 ``gate_events``，补上 P1-3
  orchestration 目录零写入的缺口）。

安全约束（对应 spec「风险与回滚」）：
* **开关默认关闭**：``APPROVAL_KERNEL_ENABLED``（兼容统一 flag 范式
  ``MOGO_FLAG_APPROVAL_KERNEL_ENABLED``）为真才写；关闭时短路，零开销。
* **完全 fail-open**：任何异常都只记 warning，绝不改变旧状态机的返回值、
  状态或 HTTP 契约。调用点应把它当作「尽力而为的旁路」。
* 影子票据带 ``shadow=True``，``token_hash=""``，不可被 ``Kernel.decide``
  消费，避免与旧票据形成双重放行。

跨服务：本文件是 ``services/common`` 规范源，同步到各服务 ``app/common/``，
因为各服务 Dockerfile 的构建上下文只 COPY 自己的 ``app/``（见 058 结论）。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

FLAG_ENV_NAMES = ("APPROVAL_KERNEL_ENABLED", "MOGO_FLAG_APPROVAL_KERNEL_ENABLED")
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def approval_kernel_enabled() -> bool:
    """迁移开关；默认 False（灰度期旧路径为主，可随时关闭回退）。"""
    for name in FLAG_ENV_NAMES:
        raw = os.environ.get(name)
        if raw is not None:
            return str(raw).strip().lower() in _TRUTHY
    return False


def _kernel(db: Any):
    from app.common.approval_kernel import ApprovalKernel

    return ApprovalKernel(db=db, audit_db=db)


def _db():
    from app.core.db import get_db

    return get_db()


def _source(value: str):
    from app.common.approval_kernel import ApprovalSource

    return ApprovalSource(str(value))


def _default_deadline() -> datetime:
    from app.common.shared_constants import utc_now

    return utc_now() + timedelta(minutes=5)


async def mirror_issue(
    *,
    source: str,
    source_id: str,
    tenant_id: str,
    actor_id: str,
    approver_id: str,
    deadline: Optional[datetime] = None,
    run_id: str = "",
    node_id: str = "",
) -> None:
    """镜像一条 pending 影子票据；任何失败都吞掉（不阻断业务）。"""
    if not approval_kernel_enabled():
        return
    try:
        await _kernel(_db()).mirror_issue(
            source=_source(source), source_id=source_id, tenant_id=tenant_id,
            actor_id=actor_id, approver_id=approver_id,
            deadline=deadline or _default_deadline(),
            run_id=run_id, node_id=node_id,
        )
    except Exception as exc:  # pragma: no cover - 旁路失败必须不影响主流程
        logger.warning("approval.mirror_issue_failed source=%s source_id=%s: %s",
                       source, source_id, exc)


async def mirror_decision(
    *,
    source: str,
    source_id: str,
    tenant_id: str,
    actor_id: str,
    approved: bool,
    reason: str = "",
) -> None:
    """镜像一次决策（终态 + 审计）；任何失败都吞掉（不阻断业务）。"""
    if not approval_kernel_enabled():
        return
    try:
        await _kernel(_db()).mirror_decision(
            source=_source(source), source_id=source_id, tenant_id=tenant_id,
            actor_id=actor_id, approved=approved, reason=reason,
        )
    except Exception as exc:  # pragma: no cover - 旁路失败必须不影响主流程
        logger.warning("approval.mirror_decision_failed source=%s source_id=%s: %s",
                       source, source_id, exc)


__all__ = ["approval_kernel_enabled", "mirror_issue", "mirror_decision"]
