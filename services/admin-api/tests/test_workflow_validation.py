from __future__ import annotations

import pytest

from app.services.workflow_validation import validate_workflow_config


def test_rejects_duplicate_workflow_output_aliases() -> None:
    with pytest.raises(ValueError, match="输出名称不能重复"):
        validate_workflow_config({
            "workflowNodes": [
                {"id": "step-1", "outputAlias": "抽取结果"},
                {"id": "step-2", "outputAlias": "抽取结果"},
            ]
        })


def test_allows_empty_and_unique_workflow_output_aliases() -> None:
    validate_workflow_config({
        "workflowNodes": [
            {"id": "step-1", "outputAlias": ""},
            {"id": "step-2", "outputAlias": "指标结果"},
            {"id": "step-3", "outputAlias": "诊断报告"},
        ]
    })
