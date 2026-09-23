# Implementation Plan: Enterprise Knowledge RAG & Multi-Source Research

**Branch**: `005-knowledge-rag-research` | **Date**: 2026-07-08 | **Spec**: [spec.md](./spec.md)

**Input**: 回溯规约，固化既有行为。把"现有知识问答/检索/引用"实现事实技术化为契约。

## Summary

不新增模块，把 `knowledge/`（retrieval + citations + agents + prompting）与 `document-parser` 的 RAG 索引产物写成契约。交付物：data-model.md（chunk/citation/retrieval result 字段）、contracts/rag-contract.md、quickstart.md。

## Technical Context

**Language/Version**: Python 3.13（chat-api/document-parser 既有栈）

**Primary Dependencies**: 既有检索客户端 + LLM（knowledge_qa_agent）+ document-parser 向量库

**Storage**: 向量库（RAG 索引）+ MongoDB（个人知识目录/资源）

**Testing**: pytest（knowledge/agents + document-parser tests 既有）

**Target Platform**: 自托管 Docker Compose

**Project Type**: 既有服务契约化（brownfield）

## 现有实现事实（contract 依据）

- 检索：`knowledge/retrieval/retrieval_client.py`（`KnowledgeRetrievalClient.search`）+ `schemas.py`（RetrievalSearchPayload/ChunkItem/SearchResult）
- 引用：`citations/citation_resolver.py`：
  - `resolve_citations(chunks, used_chunk_ids)` → KnowledgeCitation 列表
  - `_source_anchor(chunk)` → 源锚点
  - `build_evidence_bundle(query, citations)` → 证据包
  - 提示词约定：`usedChunkIds` 必须用 `documentId:chunkId` 复合键（knowledge_qa_prompt.py），跨文档不串引
- 问答：`agents/knowledge_qa_agent.py`：`retrieve_chunks` → `answer_from_chunks`（resolve_citations + evidence_bundle）
- 研究：`knowledge/research_focus_builder.py`（ResearchFocusBuilder）
- 个人知识：`api/endpoints/personal_knowledge.py`（directories + resources CRUD，require_end_user_principal）
- 访问策略：`document-parser/services/retrieval_access_policy.py`（租户/组织隔离）

## Constitution Check

| 原则 | 结果 |
|---|---|
| I. Specification-First | 通过 |
| II. Production Readiness | 通过：引用可定位、无依据标注 |
| III. Security | 通过：访问策略隔离 |
| IV. i18n | 通过 |
| V. Observability | 通过：检索事件可审计 |

## Project Structure

```text
specs/005-knowledge-rag-research/
├── plan.md
├── data-model.md      # chunk / citation / evidence bundle 字段
├── contracts/
│   └── rag-contract.md   # 检索/引用/证据/个人知识 API 契约
└── quickstart.md
```

源码不改动（brownfield 契约化）；如需修回归，以 tasks.md 登记。

## Open Questions
- OQ-1: 个人知识"可分享"当前实现范围（仅目录分享 vs 资源分享）需确认
- OQ-2: 检索是否已有重排（reranker），影响证据排序契约

## 下一步
`/speckit-clarify` 消解 OQ → 补 data-model/contracts/quickstart → checklist → tasks → analyze。
