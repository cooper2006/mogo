"""053-plaza-template-distribution：模板克隆服务（FR-003 / FR-004 / FR-006 / 050 联动）.

克隆语义（已定决策 #2）：

* clone = **深拷贝**模板定义到克隆者名下新实体（SOP → ``dag_definitions`` 新定义；
  员工 → 051 ``employees`` 档案），记录 ``template_ref``（模板坐标 + 版本）；
* **副本可改、原件只读**（非上架者不可改原件，API 层鉴权）；
* 原件修改不影响已有副本（深拷贝副本，无引用共享）。

硬步骤：

* **凭证剥离**（FR-004 / 034 口径）：模板定义中的凭证引用键一律不复制，副本需自行配置；
* **审批人重解析**（050 联动）：含 ``human_approval`` 节点的 SOP 模板克隆后审批人按
  克隆者租户重新解析（原审批人引用不跨租户携带）。

克隆时模板已下架 → 拒绝（FR-006 fail-closed）。克隆目标落既有实体集合，不另建通道。
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

from app.core.db import get_db

from .model import (
    SOP_TEMPLATE,
    EMPLOYEE_TEMPLATE,
    AssetTemplate,
    TemplateClone,
    TemplateError,
    make_clone_id,
    utcnow,
)
from .repository import TemplateRepository

#: 克隆目标实体集合（副本即普通实体，plan Structure Decision）。
SOP_TARGET = "dag_definition"
EMPLOYEE_TARGET = "employee"

#: 050 human_approval 节点类型标记。
NODE_TYPE_HUMAN_APPROVAL = "human_approval"

#: 凭证键清单（034 口径）：克隆剥离这些键，副本需自行配置。
CREDENTIAL_KEYS = frozenset({
    "authToken", "token", "apiKey", "secret", "password", "accessToken", "refreshToken",
})


class CloneError(RuntimeError):
    """克隆失败（已下架 / 跨租户 / 凭证剥离后无内容等）。"""


def _strip_credentials(node_payload: dict[str, Any]) -> dict[str, Any]:
    """剥离凭证引用键（034 口径）：递归删除凭证键，副本需自行配置。"""
    if not isinstance(node_payload, dict):
        return node_payload
    result = dict(node_payload)
    for key in list(result.keys()):
        if str(key) in CREDENTIAL_KEYS:
            result.pop(key, None)
    # 工具配置里的 headers 内同名凭证键也剥离。
    config = result.get("config")
    if isinstance(config, dict):
        headers = config.get("headers")
        if isinstance(headers, dict):
            for key in list(headers.keys()):
                if str(key) in CREDENTIAL_KEYS:
                    headers.pop(key, None)
    # 递归处理嵌套 dict/list。
    for key, value in list(result.items()):
        if isinstance(value, dict):
            result[key] = _strip_credentials(value)
        elif isinstance(value, list):
            result[key] = [_strip_credentials(item) if isinstance(item, dict) else item for item in value]
    return result


def strip_credentials(document: dict[str, Any]) -> dict[str, Any]:
    """深拷贝并剥离全部凭证键（FR-004 硬步骤，对外接口）。"""
    return _strip_credentials(copy.deepcopy(document))


def _reparse_approver(node_payload: dict[str, Any], *, tenant_id: str) -> dict[str, Any]:
    """050 联动：human_approval 节点审批人按克隆者租户重解析。

    原审批人引用不跨租户携带；克隆侧改为"待配置"标记，由克隆者租户显式指定
    （fail-closed：不静默沿用跨租户审批人）。
    """
    if str(node_payload.get("type") or "") != NODE_TYPE_HUMAN_APPROVAL:
        return node_payload
    result = dict(node_payload)
    # 审批人改挂到克隆者租户：清空原值并打上待解析标记（副本保存时由克隆者指定）。
    result.pop("approver", None)
    result["approver_tenant_id"] = tenant_id
    result["approver_pending"] = True
    return result


def _reparse_approvers_in_document(document: dict[str, Any], *, tenant_id: str) -> dict[str, Any]:
    """遍历 SOP 定义文档，对含 human_approval 的节点重解析审批人（050 联动）。"""
    result = copy.deepcopy(document)
    nodes = result.get("nodes")
    if isinstance(nodes, list):
        cleaned: list[dict[str, Any]] = []
        for node in nodes:
            if not isinstance(node, dict):
                cleaned.append(node)
                continue
            node_copy = dict(node)
            payload = node_copy.get("payload")
            if isinstance(payload, dict):
                node_copy["payload"] = _reparse_approver(payload, tenant_id=tenant_id)
            elif isinstance(node_copy.get("approver"), str) or "type" in node_copy:
                # 顶层 approver 形态（非 payload 嵌套）。
                node_copy = _reparse_approver(node_copy, tenant_id=tenant_id)
            cleaned.append(node_copy)
        result["nodes"] = cleaned
    return result


def _dedupe_name(base_name: str, existing: set[str]) -> str:
    """同名克隆：自动后缀，不覆盖既有资产（Edge Cases）。"""
    if base_name not in existing:
        return base_name
    counter = 2
    while f"{base_name} (副本 {counter})" in existing:
        counter += 1
    return f"{base_name} (副本 {counter})"


async def _resolve_sop_target(
    *,
    tenant_id: str,
    cloner_id: str,
    content: dict[str, Any],
    name: str,
    existing_ids: set[str],
) -> tuple[str, dict[str, Any]]:
    """SOP 副本落 dag_definitions（克隆者名下，chat-api 010 集合）。

    生成新 orchestration_id（避免与既有冲突），深拷贝文档。
    """
    header = content.get("orchestration") or {}
    base_id = str(header.get("id") or "").strip() or f"sop_{uuid.uuid4().hex[:8]}"
    orchestration_id = base_id
    counter = 1
    while orchestration_id in existing_ids:
        orchestration_id = f"{base_id}_{counter}"
        counter += 1

    new_document = copy.deepcopy(content)
    new_document["orchestration"] = dict(header)
    new_document["orchestration"]["id"] = orchestration_id
    new_document["orchestration"]["version"] = "1"
    new_document["orchestration"]["template_ref"] = {
        "template_id": None,  # 由调用方回填
        "asset_type": SOP_TEMPLATE,
        "version": None,  # 由调用方回填
    }
    return orchestration_id, new_document


async def _resolve_employee_target(
    *,
    tenant_id: str,
    cloner_id: str,
    content: dict[str, Any],
    name: str,
    existing_ids: set[str],
) -> tuple[str, dict[str, Any]]:
    """员工模板副本落 051 employees（B1 未落地时挂起，不另建通道）。

    返回 (employee_id, 档案文档)。
    """
    employee_id = f"emp_{uuid.uuid4().hex[:12]}"
    while employee_id in existing_ids:
        employee_id = f"emp_{uuid.uuid4().hex[:12]}"
    profile = copy.deepcopy(content)
    profile["employee_id"] = employee_id
    profile["name"] = name
    profile["tenant_id"] = tenant_id
    profile["created_by"] = cloner_id
    profile["template_ref"] = {
        "template_id": None,  # 由调用方回填
        "asset_type": EMPLOYEE_TEMPLATE,
        "version": None,  # 由调用方回填
    }
    return employee_id, profile


async def clone_template(
    template: AssetTemplate,
    *,
    cloner_id: str,
    name: str | None = None,
    repo: TemplateRepository | None = None,
) -> tuple[TemplateClone, dict[str, Any]]:
    """克隆模板到克隆者名下新实体。

    Returns:
        (克隆记录, 副本目标信息)。

    Raises:
        CloneError: 模板已下架 / 类型不支持。
    """
    repo = repo or TemplateRepository()
    # FR-006：克隆时模板已下架 → 拒绝（fail-closed）。
    if template.state == "offline":
        raise CloneError(f"模板已下架，无法克隆：{template.template_id}")

    target_name = _dedupe_name(str(name or template.name), set())

    # 深拷贝 + 凭证剥离（FR-004 硬步骤）。
    content = strip_credentials(template.content)

    if template.asset_type == SOP_TEMPLATE:
        # 050 联动：审批人按克隆者租户重解析。
        content = _reparse_approvers_in_document(content, tenant_id=template.tenant_id)
        target_type = SOP_TARGET
        existing_ids = await _existing_sop_ids(template.tenant_id)
        # 合并本模板既有克隆的 target_key（副本未落库前也保证 id 唯一）。
        existing_ids |= {c.target_key for c in await repo.list_clones(tenant_id=template.tenant_id, template_id=template.template_id)}
        target_key, target_doc = await _resolve_sop_target(
            tenant_id=template.tenant_id, cloner_id=cloner_id,
            content=content, name=target_name, existing_ids=existing_ids,
        )
    elif template.asset_type == EMPLOYEE_TEMPLATE:
        target_type = EMPLOYEE_TARGET
        existing_ids = await _existing_employee_ids(template.tenant_id)
        existing_ids |= {c.target_key for c in await repo.list_clones(tenant_id=template.tenant_id, template_id=template.template_id)}
        target_key, target_doc = await _resolve_employee_target(
            tenant_id=template.tenant_id, cloner_id=cloner_id,
            content=content, name=target_name, existing_ids=existing_ids,
        )
    else:
        raise CloneError(f"不支持的模板类型：{template.asset_type!r}")

    # 回填 template_ref（模板坐标 + 版本，已定决策 #2）。
    target_doc = _set_template_ref(target_doc, template, target_key)
    target_doc["template_ref"] = {
        "template_id": template.template_id,
        "asset_type": template.asset_type,
        "version": template.version,
    }

    clone = TemplateClone(
        clone_id=make_clone_id(),
        tenant_id=template.tenant_id,
        template_id=template.template_id,
        template_type=template.asset_type,
        template_version=template.version,
        cloner_id=cloner_id,
        target_type=target_type,
        target_key=target_key,
        template_ref={
            "template_id": template.template_id,
            "asset_type": template.asset_type,
            "version": template.version,
        },
        created_at=utcnow(),
    )
    await repo.save_clone(clone)
    await repo.audit(
        tenant_id=template.tenant_id,
        actor=cloner_id,
        action="clone",
        detail={
            "template_id": template.template_id,
            "target_type": target_type,
            "target_key": target_key,
            "version": template.version,
        },
    )
    return clone, target_doc


def _set_template_ref(document: dict[str, Any], template: AssetTemplate, target_key: str) -> dict[str, Any]:
    """回填 template_ref 到副本文档（SOP header / 员工档案）。"""
    if template.asset_type == SOP_TEMPLATE:
        header = document.get("orchestration")
        if isinstance(header, dict):
            header["template_ref"] = {
                "template_id": template.template_id,
                "asset_type": template.asset_type,
                "version": template.version,
                "target_key": target_key,
            }
    else:
        document["template_ref"] = {
            "template_id": template.template_id,
            "asset_type": template.asset_type,
            "version": template.version,
            "target_key": target_key,
        }
    return document


async def _existing_sop_ids(tenant_id: str) -> set[str]:
    db = get_db()
    if db is None:
        return set()
    rows = await db["dag_definitions"].find({"tenant_id": tenant_id}, {"orchestration_id": 1}).to_list(length=10000)
    return {str(r.get("orchestration_id") or "") for r in rows}


async def _existing_employee_ids(tenant_id: str) -> set[str]:
    db = get_db()
    if db is None:
        return set()
    try:
        rows = await db["employees"].find({"tenant_id": tenant_id}, {"employee_id": 1}).to_list(length=10000)
        return {str(r.get("employee_id") or r.get("_id") or "") for r in rows}
    except Exception:  # noqa: BLE001 - 051 B1 未落地时 employees 集合不存在
        return set()


__all__ = [
    "CREDENTIAL_KEYS",
    "CloneError",
    "EMPLOYEE_TARGET",
    "SOP_TARGET",
    "clone_template",
    "strip_credentials",
]
