# Implementation Plan: Knowledge Graph Layer

**Branch**: `015-knowledge-graph-layer` | **Date**: 2026-07-08 | **Spec**: [spec.md](./spec.md)

**Input**: 缺口新特性（P2 规模化生态，后置）。在文档 RAG（特性 005）之上补充结构化知识图谱，支持跨文档实体/关系推理，提升复杂问题多跳问答与一致性校验。

## Summary

新增 `services/chat-api/app/knowledge_graph/` 子模块：实体/关系抽取（从文档/数据）、图谱存储（首期用 MongoDB 邻接结构模拟图，量大再迁图数据库）、多跳查询 + 一致性约束检测。图谱与 005 RAG 并行，二者结果可融合。

## Technical Context

**Language/Version**: Python 3.13（chat-api 既有栈）

**Primary Dependencies**: 既有 `knowledge/`（抽取数据源）；新增图谱引擎（首期 MongoDB 邻接，避免引入图数据库）

**Storage**: 新增 `kg_nodes`（实体）+ `kg_edges`（关系，含类型/方向/来源）；量大迁图数据库（Neo4j 等）为后续

**Testing**: pytest（抽取单测 + 多跳查询测试 + 一致性约束测试 + 增量合并测试）

**Target Platform**: 自托管 Docker Compose

**Project Type**: 新增模块（知识图谱层，P2 后置）

## 现有挂载点依据

- 数据源：复用 `knowledge/` 抽取（实体/关系从文档/数据来）
- 检索融合：与 005 `knowledge/retrieval` 结果融合（图谱补充结构化推理，文本检索仍走 RAG）
- 业务实体对齐：与 014 business-semantic-index 的 `biz_entities` 对齐（业务实体可纳入图谱节点）
- 权限：图谱访问受 001 治理层约束

## Constitution Check

| 原则 | 结果 |
|---|---|
| I. Specification-First | 通过 |
| II. Production Readiness | 通过：首期 MongoDB 模拟，不强制图数据库 |
| III. Security | 通过：图谱访问受 001 约束 |
| IV. i18n | 通过 |
| V. Observability | 通过：推理路径可追溯 |

## Project Structure

```text
services/chat-api/app/
└── knowledge_graph/
    ├── __init__.py
    ├── extract.py            # 实体/关系抽取
    ├── store.py            # 图谱存储（首期 MongoDB 邻接）
    ├── query.py            # 多跳查询/邻居遍历
    ├── consistency.py      # 一致性约束检测
    └── schema.py           # 实体/关系 schema（按领域配置）
```

## Open Questions（已 clarify 消解）
- OQ-1 图谱存储：**首期 MongoDB 邻接**（`kg_nodes` + `kg_edges`），迁移 Neo4j 阈值 = 节点 > 50 万 或 查询 p95 > 500ms。
- OQ-2 实体/关系 schema：**企业内通用 schema**（人/组织/产品/事件 + 隶属/负责/引用/关联），按业务可扩展（`schema.py` 配置）。
- OQ-3 多跳深度上限：**默认 3 跳**（可配 `kg_max_hops`），防查询爆炸。
- OQ-4 一致性约束种类：**互斥（同一实体两类互斥属性）+ 传递（A→B→C 则 A→C）+ 基数（关系端点数量上限）**。
- OQ-5 与 014 业务实体对齐：**图谱节点可引用 `biz_entities`**（`kg_nodes.source_ref` 指向业务实体 ID），不做数据复制，做指针引用。

## 下一步
OQ 已 clarify 消解。P2 后置，按路线图节奏推进：`/speckit-checklist` → `/speckit-tasks` → `/speckit-analyze` → `/speckit-implement` → `/speckit-converge`。
