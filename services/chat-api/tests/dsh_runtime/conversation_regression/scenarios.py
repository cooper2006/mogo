from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConversationScenario:
    id: str
    prompt: str
    model_tool_name: str
    gateway_tool_name: str
    arguments: dict[str, Any]


SCENARIOS = (
    ConversationScenario(
        id="dynamic_http_tool",
        prompt="调用本轮动态注册的 HTTP 查询工具。",
        model_tool_name="askai_http_regression_lookup",
        gateway_tool_name="askai_http_regression_lookup",
        arguments={"value": "http-marker"},
    ),
    ConversationScenario(
        id="dynamic_mcp_tool",
        prompt="调用本轮动态注册的 MCP 查询工具。",
        model_tool_name="askai_mcp_regression_lookup",
        gateway_tool_name="askai_mcp_regression_lookup",
        arguments={"value": "mcp-marker"},
    ),
    ConversationScenario(
        id="default_web_search",
        prompt="搜索一个当前公开事实。",
        model_tool_name="web_search",
        gateway_tool_name="external_search",
        arguments={"queries": ["DSH regression current fact"], "max_results_per_query": 8},
    ),
    ConversationScenario(
        id="progressive_research",
        prompt="对一个公开主题进行多来源研究。",
        model_tool_name="progressive_research",
        gateway_tool_name="progressive_research",
        arguments={"query": "DSH regression research"},
    ),
    ConversationScenario(
        id="knowledge_search",
        prompt="查询企业内部回归知识。",
        model_tool_name="knowledge_search",
        gateway_tool_name="knowledge_search",
        arguments={"query": "DSH regression policy", "top_n": 3, "rerank": True},
    ),
    ConversationScenario(
        id="content_generation",
        prompt="生成一篇受治理的短测试文章。",
        model_tool_name="content_production",
        gateway_tool_name="content_production",
        arguments={
            "request": "Write a deterministic DSH regression article.",
            "content_form": "article",
            "writing_mode": "creative",
            "min_words": 100,
            "max_words": 800,
        },
    ),
    ConversationScenario(
        id="word_export",
        prompt="把给定 Markdown 导出成 Word。",
        model_tool_name="artifact_export",
        gateway_tool_name="artifact_export",
        arguments={
            "format": "docx",
            "markdown": "# DSH Regression\n\nWORD_EXPORT_OK",
            "filename": "dsh-regression.docx",
        },
    ),
    ConversationScenario(
        id="document_translation",
        prompt="把给定中文 Word 保真翻译为英文。",
        model_tool_name="document_transform",
        gateway_tool_name="document_transform",
        arguments={
            "artifact": {
                "object_path": "regression/source.docx",
                "filename": "source.docx",
                "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            },
            "source_language": "zh-CN",
            "target_language": "en-US",
            "filename": "translated.docx",
        },
    ),
)


SKILL_SCENARIO = ConversationScenario(
    id="dynamic_skill",
    prompt="执行刚注册的测试 Skill。",
    model_tool_name="askai_mcp_regression_lookup",
    gateway_tool_name="askai_mcp_regression_lookup",
    arguments={"value": "skill-marker"},
)
