"""Keep stable workflow references when AI rewrites node wording."""

from __future__ import annotations

from typing import Any


_READ_SOURCE_KEYS = ("sourceType", "knowledgeScope", "knowledgeSourceId")
_REVIEW_SOURCE_KEYS = ("reviewSubjectNodeId", "reviewCriteriaNodeId", "reviewCriteriaMode", "reviewCriteria", "outputMode")


def restore_workflow_bindings(
    existing: list[dict[str, Any]], generated: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {str(node.get("id") or ""): node for node in existing}
    for node in generated:
        node_type = str(node.get("type") or "")
        old = by_id.get(str(node.get("id") or ""))
        if not old or str(old.get("type") or "") != node_type:
            continue
        keys = _READ_SOURCE_KEYS if node_type == "read_material" else _REVIEW_SOURCE_KEYS if node_type == "review_check" else ()
        if not keys:
            continue
        old_config = old.get("businessConfig") if isinstance(old.get("businessConfig"), dict) else {}
        config = node.get("businessConfig") if isinstance(node.get("businessConfig"), dict) else {}
        node["businessConfig"] = {
            **{key: value for key, value in config.items() if key != "sourceRole"},
            **{key: old_config[key] for key in keys if key in old_config},
        }
    return generated
