"""Translate document-processing errors at the HTTP boundary only."""

from __future__ import annotations

import re


_ENGLISH_DETAILS = {
    "任务队列不可用": "The task queue is unavailable",
    "DASHSCOPE_API_KEY 未配置": "DASHSCOPE_API_KEY is not configured",
    "DashScope rerank endpoint 未配置": "The DashScope rerank endpoint is not configured",
    "Azure embedding 配置不完整，请设置 endpoint、deployment 和 API Key": "Azure embedding configuration is incomplete. Set the endpoint, deployment, and API key.",
    "Azure embedding 返回格式不正确": "Azure embedding returned an invalid response format",
    "Azure embedding 缺少 embedding 字段": "Azure embedding response is missing the embedding field",
    "模型中心 embedding 的 Base URL 或模型 ID 为空": "The model center embedding Base URL or model ID is empty",
    "模型中心 embedding 返回格式不正确": "The model center embedding response format is invalid",
    "模型中心 embedding 缺少 embedding 字段": "The model center embedding response is missing the embedding field",
    "chunk 数量和向量数量不一致": "The chunk and vector counts do not match",
    "Docling chunker 不可用，无法使用 Docling 分段": "The Docling chunker is unavailable; Docling segmentation cannot run",
    "Docling 未安装，且 python-docx 不可用，无法解析 DOCX": "Docling is not installed and python-docx is unavailable; DOCX parsing cannot run",
    "Docling 未安装，且 pypdf 不可用，无法解析 PDF": "Docling is not installed and pypdf is unavailable; PDF parsing cannot run",
    "Docling 未安装，当前文件类型没有可用的轻量解析器": "Docling is not installed and no lightweight parser is available for this file type",
    "没有可索引的 RAG 分段": "There are no RAG chunks to index",
    "模型配置缺少租户标识": "The model configuration is missing a tenant ID",
    "模型组 ID 无效": "Invalid model group ID",
    "模型组不可用": "The model group is unavailable",
}


def _dynamic_english(detail: str) -> str | None:
    patterns = (
        (r"Embedding 请求失败: HTTP (\d{3})(?: .*)?", "Embedding request failed: HTTP {}"),
        (r"Rerank 请求失败: HTTP (\d{3})(?: .*)?", "Rerank request failed: HTTP {}"),
        (r"Embedding 调用失败: .*", "Embedding call failed"),
        (r"DashScope rerank 调用失败: .*", "DashScope rerank call failed"),
        (r"Rerank 调用失败: .*", "Rerank call failed"),
        (r"不支持的 rerank provider: (.*)", "Unsupported rerank provider: {}"),
        (r"不支持的 embedding provider: (.*)", "Unsupported embedding provider: {}"),
        (r"知识库尚未选择 (.*) 模型", "No {} model has been selected for the knowledge base"),
        (r"(.*) 模型实例 ID 无效", "Invalid {} model instance ID"),
        (r"未找到可用的 (.*) 模型配置", "No available {} model configuration was found"),
        (r"所选模型不具备 (.*) 能力", "The selected model does not support {}"),
        (r"(.*) 模型 API Key 无法解密或为空", "The {} model API key cannot be decrypted or is empty"),
        (r"向量库 (.*) 已预留，当前默认实现为 Weaviate", "Vector store {} is reserved; the current default implementation is Weaviate"),
    )
    for pattern, template in patterns:
        match = re.fullmatch(pattern, detail)
        if match and (not match.groups() or not any("\u3400" <= char <= "\u9fff" for char in match.group(1))):
            return template.format(*match.groups())
    return None


def localize_detail(detail: object, status_code: int, accept_language: str | None) -> object:
    language = (accept_language or "zh").split(",", 1)[0].split(";", 1)[0].strip().lower()
    if not language.startswith("en") or not isinstance(detail, str):
        return detail
    if not any("\u3400" <= char <= "\u9fff" for char in detail):
        return detail
    return _ENGLISH_DETAILS.get(detail) or _dynamic_english(detail) or {
        400: "Invalid request",
        403: "Access denied",
        404: "Resource not found",
        422: "Invalid request data",
        503: "Service unavailable",
    }.get(status_code, "Document processing failed")
