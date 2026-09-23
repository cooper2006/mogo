# Implementation Plan: General-Purpose DAG Orchestration Engine

**Branch**: `010-dag-orchestration-engine` | **Date**: 2026-07-08 | **Spec**: [spec.md](./spec.md)

**Input**: 缺口新特性。把 `enterprise_capabilities/content/planning` 场景特化的"内容规划/研究模式"多路径执行，抽象为通用 DAG 编排引擎，复用其既有构建器模式。

## Summary

新增 `services/chat-api/app/orchestration/`（通用 DAG 引擎）：拓扑排序 + 环检测 + 四模式（sequential/supervisor/hybrid/graph）+ 条件跳过（受限表达式）+ 节点级指数退避重试。把现有 `content/planning/builder.py`（semantic/structured/fallback 多路径构建）作为"可迁入 DAG 的既有场景"做向后兼容验证，引擎本身不绑定内容语义。

## Technical Context

**Language/Version**: Python 3.13（chat-api）

**Primary Dependencies**: 既有 `content/planning`（contracts/builder/integration）作为迁移参照；新增 DAG 引擎独立子模块

**Storage**: 编排定义声明式（MongoDB `dag_definitions` 集合，可版本化，与特性 002 工作流版本化对接）

**Testing**: pytest（拓扑/环检测单测 + 四模式执行 + 条件跳过/重试 + 现有内容规划场景迁移等价测试）

**Target Platform**: 自托管 Docker Compose

**Project Type**: 新增模块（通用编排引擎）

## 现有实现事实（迁移参照）

- `content/planning/contracts.py`：`ContentPlanSpec` / `PlanSectionSpec` / `VisualSlotSpec`（DecisionOutput 派生，声明式规格）
- `content/planning/builder.py`：`ContentPlanBuilder` 的 semantic / structured / projected / fallback 多路径构建（"多路径执行"即通用 DAG 的雏形）
- `content/planning/integration.py`：规划与内容管线的集成点

## Constitution Check

| 原则 | 结果 |
|---|---|
| I. Specification-First | 通过 |
| II. Production Readiness | 通过：环检测/失败阻塞 |
| III. Security | 通过：受限表达式（无任意代码） |
| IV. i18n | 通过 |
| V. Observability | 通过：节点事件审计 |

## Project Structure

```text
services/chat-api/app/
├── orchestration/               # 新增通用 DAG 引擎
│   ├── __init__.py
│   ├── graph.py                # DAG 节点/边模型
│   ├── topo.py                 # 拓扑排序 + 环检测
│   ├── engine.py               # 四模式执行器
│   ├── conditions.py           # 受限表达式求值
│   ├── retry.py                # 节点级指数退避
│   └── registry.py             # 编排定义声明式管理
└── enterprise_capabilities/content/planning/   # 既有：作为迁移场景验证
```

## Open Questions
- OQ-1: 条件表达式求值采用何种受限语言（JSON 条件对象 vs 简单表达式 AST；spec 明确"禁用任意代码"）
- OQ-2: 并行度上限（无依赖节点并行时的并发数，需 clarify）
- OQ-3: 节点重试与特性 007（LLM 模型级重试）如何分层（节点重试包模型调用，还是独立）
- OQ-4: 现有内容规划场景迁移是否一次性替换还是双轨并行（建议双轨 + 等价测试）

## 下一步
`/speckit-clarify` 消解 OQ → 补 research/data-model/contracts/quickstart → checklist → tasks → analyze → implement → converge。
