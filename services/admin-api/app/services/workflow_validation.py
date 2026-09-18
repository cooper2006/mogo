"""Validation shared by organization Workflow Skill write paths."""

from __future__ import annotations

from typing import Any


def validate_workflow_config(config: dict[str, Any]) -> None:
    raw_nodes = config.get("workflowNodes") or config.get("workflow_nodes") or []
    if not isinstance(raw_nodes, list):
        raise ValueError("工作流节点格式无效")

    aliases = [
        str(node.get("outputAlias") or node.get("output_alias") or "").strip()
        for node in raw_nodes
        if isinstance(node, dict)
    ]
    populated = [alias for alias in aliases if alias]
    if len(populated) != len(set(populated)):
        raise ValueError("工作流各步骤的输出名称不能重复")
