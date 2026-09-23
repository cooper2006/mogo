# Implementation Plan: Business System Semantic Index

**Branch**: `014-business-semantic-index` | **Date**: 2026-07-08 | **Spec**: [spec.md](./spec.md)

**Input**: 缺口新特性（P2 规模化生态，后置）。在 RAG（特性 005）之上对接 CRM/采购/财务等业务系统做语义检索，让 Agent 按业务语义召回业务实体与状态。

## Summary

新增 `services/chat-api/app/business_index/` 子模块：业务系统连接器（首期 1 个）+ 业务实体语义抽取 + 增量索引 + 跨系统实体对齐。检索复用特性 005 的 `knowledge/retrieval` 客户端与引用锚点机制，业务索引是"检索侧"叠加层，不替代业务系统、不写业务库。

## Technical Context

**Language/Version**: Python 3.13（chat-api 既有栈）

**Primary Dependencies**: 既有 `knowledge/retrieval`（检索客户端 + schemas）+ 向量库；新增业务系统连接器（DB 驱动/API 客户端）

**Storage**: 复用既有向量库（业务实体嵌入）+ 新增 `biz_entities`（业务实体索引，含系统来源/实体类型/对齐键）

**Testing**: pytest（实体抽取单测 + 增量索引测试 + 跨系统对齐测试 + 检索命中带来源测试）

**Target Platform**: 自托管 Docker Compose

**Project Type**: 新增模块（业务语义索引，P2 后置）

## 现有挂载点依据

- 检索：复用 `knowledge/retrieval/retrieval_client.py` + `schemas.py`（RetrievalChunkItem 可扩展业务实体项）
- 引用锚点：复用 `knowledge/citations/citation_resolver.py`（`_source_anchor` 扩展为"业务实体来源"）
- 权限：复用 `document-parser/services/retrieval_access_policy.py`（租户/组织隔离）
- 业务系统连接凭据（DB 账号/API key）：按 001 安全原则不入仓库，经密钥管理注入

## Constitution Check

| 原则 | 结果 |
|---|---|
| I. Specification-First | 通过 |
| II. Production Readiness | 通过：增量索引 + 只读 |
| III. Security | 通过：只读不写业务库；凭据不入仓库；访问受 001 约束 |
| IV. i18n | 通过 |
| V. Observability | 通过：索引/检索事件审计 |

## Project Structure

```text
services/chat-api/app/
└── business_index/
    ├── __init__.py
    ├── connectors/            # 业务系统连接器
    │   ├── base.py
    │   ├── crm.py            # 首期（按 clarify 定）
    │   ├── procurement.py
    │   └── finance.py
    ├── entity_extract.py      # 业务实体语义抽取
    ├── incremental.py         # 增量索引
    └── align.py             # 跨系统实体对齐
services/chat-api/app/knowledge/retrieval/  # 既有：检索客户端扩展业务实体项
```

## Open Questions
- OQ-1: 首期对接哪个业务系统（CRM/采购/财务）+ 连接方式（DB 直连 vs API）
- OQ-2: 业务实体 schema 定义（客户/订单/供应商/账目的字段与对齐键，领域相关需按业务定）
- OQ-3: 增量同步机制（CDC vs 定时拉取，spec 写"增量更新"需定机制）
- OQ-4: 业务数据脱敏（与 001 PII 脱敏联动，业务实体含 PII 字段时如何）

## 下一步
P2 后置。`/speckit-clarify` 消解 OQ → 补 research/data-model/contracts/quickstart → checklist → tasks → analyze → implement → converge。
