import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.api.endpoints.skills import _normalize_workflow_node_type
from app.dsh_runtime.profile.skills.workflow import compile_workflow_body
from app.dsh_runtime.profile.tools import ToolProfileDefinition
from app.enterprise_capabilities.runtime.catalog import InternalCapabilityCatalog
from app.services.workflow_node_bindings import restore_workflow_bindings


def test_review_check_is_accepted_and_compiled_as_agent_guidance():
    assert _normalize_workflow_node_type("校验复核") == "review_check"
    row = {"name": "合同预审", "config": {"workflowNodes": [{
        "id": "review", "type": "review_check", "title": "逐条审查",
        "description": "核对每条适用规则", "outputAlias": "审核结果",
        "businessConfig": {
            "reviewSubject": "合同事实", "reviewCriteria": "审核规则",
            "evidenceRequirement": "source_and_basis",
            "failurePolicy": "needs_human_review",
        },
    }]}}
    body, refs = compile_workflow_body(row, tools=(), style_refs={})
    assert refs == ("dsh.review_check@v1",)
    assert "Review subject: 合同事实" in body
    assert "Review criteria: 审核规则" in body
    assert "Review each item and provide a conclusion" in body
    assert "evidenceRequirement" not in body
    assert "failurePolicy" not in body
    assert "本步骤输出：审核结果" in body


def test_ai_wording_rewrite_keeps_selected_knowledge_document():
    existing = [{
        "id": "rules", "type": "read_material",
        "businessConfig": {
            "sourceType": "knowledge_document", "knowledgeScope": "organization",
            "knowledgeSourceId": "rule-doc", "sourceRole": "review_policy",
        },
    }]
    generated = [{
        "id": "rules", "type": "read_material",
        "businessConfig": {"source": "更新后的节点文字", "knowledgeSourceId": "invented-id"},
    }]
    result = restore_workflow_bindings(existing, generated)
    assert result[0]["businessConfig"]["knowledgeSourceId"] == "rule-doc"
    assert "sourceRole" not in result[0]["businessConfig"]


def _bound_review_nodes():
    return [
        {"id": "subject", "type": "extract_info", "title": "提取对象", "outputAlias": "新对象"},
        {"id": "basis", "type": "extract_info", "title": "提取依据", "outputAlias": "新依据"},
        {"id": "review", "type": "review_check", "title": "复核", "outputAlias": "复核结果",
         "businessConfig": {
             "reviewSubjectNodeId": "subject", "reviewCriteriaNodeId": "basis",
             "reviewSubject": "旧对象", "reviewCriteria": "旧依据",
         }},
    ]


def test_review_sources_resolve_current_upstream_aliases():
    body, _ = compile_workflow_body(
        {"name": "通用复核", "config": {"workflowNodes": _bound_review_nodes()}},
        tools=(), style_refs={},
    )
    assert "Review subject: 新对象" in body
    assert "Review criteria: 新依据" in body
    assert "Review subject: 旧对象" not in body


def test_review_rejects_downstream_or_missing_source():
    nodes = _bound_review_nodes()
    nodes[2]["businessConfig"]["reviewCriteriaNodeId"] = "later"
    nodes.append({"id": "later", "type": "extract_info", "title": "后续", "outputAlias": "后续结果"})
    with pytest.raises(ValueError, match="reviewCriteriaNodeId"):
        compile_workflow_body(
            {"name": "通用复核", "config": {"workflowNodes": nodes}},
            tools=(), style_refs={},
        )


def test_review_accepts_inline_criteria_with_upstream_subject():
    nodes = _bound_review_nodes()
    nodes[2]["businessConfig"].update({
        "reviewCriteriaMode": "inline", "reviewCriteriaNodeId": "",
        "reviewCriteria": "金额必须大于零",
    })
    body, _ = compile_workflow_body(
        {"name": "通用复核", "config": {"workflowNodes": nodes}},
        tools=(), style_refs={},
    )
    assert "Review subject: 新对象" in body
    assert "Review criteria: 金额必须大于零" in body


def test_review_rejects_empty_inline_criteria():
    nodes = _bound_review_nodes()
    nodes[2]["businessConfig"].update({
        "reviewCriteriaMode": "inline", "reviewCriteriaNodeId": "", "reviewCriteria": "",
    })
    with pytest.raises(ValueError, match="inline criteria"):
        compile_workflow_body(
            {"name": "通用复核", "config": {"workflowNodes": nodes}},
            tools=(), style_refs={},
        )


def test_ai_wording_rewrite_keeps_review_source_ids():
    existing = [_bound_review_nodes()[2]]
    generated = [{"id": "review", "type": "review_check", "businessConfig": {
        "reviewSubjectNodeId": "made-up", "reviewCriteriaNodeId": "made-up",
    }}]
    result = restore_workflow_bindings(existing, generated)
    assert result[0]["businessConfig"]["reviewSubjectNodeId"] == "subject"
    assert result[0]["businessConfig"]["reviewCriteriaNodeId"] == "basis"


def test_annotated_review_compiles_generic_verified_docx_tools():
    catalog = InternalCapabilityCatalog()
    tools = tuple(
        ToolProfileDefinition(
            name=definition.tool_name,
            version=definition.version,
            source_type="internal",
            capability_ref=definition.capability_ref,
            external_tool_id=definition.capability_ref,
            display_name=definition.display_name,
            description=definition.description,
            input_schema=definition.input_schema,
            output_schema=definition.output_schema,
            risk_level=definition.risk_level,
        )
        for definition in catalog._definitions
        if definition.capability_ref in {"document.review_source@v1", "document.annotate@v1"}
    )
    nodes = _bound_review_nodes()
    nodes[2]["businessConfig"]["outputMode"] = "annotated_docx"
    body, refs = compile_workflow_body(
        {"name": "通用材料审核", "config": {"workflowNodes": nodes}},
        tools=tools, style_refs={},
    )
    assert "document.review_source@v1" in refs
    assert "document.annotate@v1" in refs
    assert "uniquely located in the original file" in body
    assert "For other formats, create a separate review report" in body

    generated = [{"id": "review", "type": "review_check", "businessConfig": {}}]
    restored = restore_workflow_bindings([nodes[2]], generated)
    assert restored[0]["businessConfig"]["outputMode"] == "annotated_docx"
