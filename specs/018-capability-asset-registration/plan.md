# Implementation Plan: Capability Assetization (Discovery → Registration)

**Branch**: `018-capability-asset-registration` | **Date**: 2026-07-08 | **Spec**: [spec.md](./spec.md)

**Input**: 缺口新特性（P2 规模化生态，后置）。把存量业务能力（审批/查询/下单等）变成可审计、可版本化的能力资产，注册为可被 Agent 发现和调用的标准化单元。

## Summary

新增 `services/admin-api/app/services/capability_assets/` 子模块：能力发现（扫描/接入存量能力接口契约）+ 资产注册（契约 + 版本 + owner + 审计）+ 治理视图（全量资产 + 状态）。与 004（Skill 生命周期）的关系：能力资产是 Skill/工具的"资产化"升级；与 012（A2A）的关系：注册资产可经 A2A 对外暴露。

## Technical Context

**Language/Version**: Python 3.13（admin-api 既有栈）

**Primary Dependencies**: 既有 `enterprise_capabilities/tools`（工具/MCP 契约）+ `admin-api/position_roles`（owner/授权）+ 既有审计通道；新增能力资产注册中心

**Storage**: 新增 `capability_assets`（契约 + 版本 + owner + 状态 + 审计引用）

**Testing**: pytest（能力扫描单测 + 契约注册测试 + 版本递增测试 + 治理视图测试）

**Target Platform**: 自托管 Docker Compose

**Project Type**: 新增模块（能力资产化，P2 后置）

## 现有挂载点依据

- 工具/MCP 契约：`enterprise_capabilities/tools/contracts.py`（ToolExecuteRequest / ActionReceipt 作为"能力契约"参照）
- 审批/查询/下单等存量能力：经 MCP/工具接入（004 既有），资产化是把它们标准化登记
- 审计/owner：复用 `admin-api/system_audit` + `position_roles`（资产责任人 + 全量审计）
- 对外暴露：与 012 A2A 网关对接（注册资产可生成 AgentCard/JSON-RPC 端点）

## Constitution Check

| 原则 | 结果 |
|---|---|
| I. Specification-First | 通过 |
| II. Production Readiness | 通过：资产可审计、可版本化 |
| III. Security | 通过：资产调用过 001 门禁/审计 |
| IV. i18n | 通过 |
| V. Observability | 通过：治理侧全量资产视图 |

## Project Structure

```text
services/admin-api/app/
└── services/
    └── capability_assets/        # 新增能力资产化
        ├── __init__.py
        ├── discover.py           # 扫描/接入存量能力，识别契约
        ├── registry.py           # 资产注册（契约 + 版本 + owner + 审计）
        ├── versioning.py         # 契约变更版本递增
        └── governance.py         # 全量资产治理视图
services/admin-api/app/api/routes/
└── (新增 capability_assets.py：资产 CRUD + 治理端点)
```

## Open Questions（已 clarify 消解）
- OQ-1 能力契约 schema：**采用 GraphSpec 思路**（输入/输出/错误/SLA 四段），JSON 声明式，与 009/010 的声明式规则同风格。
- OQ-2 发现分工：**自动扫描识别标准 REST/MCP 接口契约；非标准能力必须人工补全**（spec 声明"自动扫描 + 人工补全"）。
- OQ-3 资产与 004 映射：**多对多**（一个 Skill 可含多个能力资产；一个资产可被多个 Skill 引用），用 `capability_assets.skill_refs` 关联。
- OQ-4 资产下线审批：**006 的"全能力管理员"角色可审批下线**；留 001 审计。
- OQ-5 与 012 A2A 暴露策略：**显式标记**（`capability_assets.a2a_exposed = true` 才生成 AgentCard），非默认全暴露。

## 下一步
OQ 已 clarify 消解。P2 后置，按路线图节奏推进：`/speckit-checklist` → `/speckit-tasks` → `/speckit-analyze` → `/speckit-implement` → `/speckit-converge`。
