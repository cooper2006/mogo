# Implementation Plan: 连接器市场（041-connector-market）

**Branch**: `041-connector-market` | **Date**: 2026-10-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/041-connector-market/spec.md`

**Note**: 本计划为**全新特性、代码尚未开工**的 spec → plan → tasks 先行流程（市场框架先行；存量工具连接已存在，本特性是升级而非新建）。冲突时以 spec.md 的 FR 为准。

## Summary

把租户级 HTTP/MCP 工具连接升级为"连接器市场"：admin-api 新增**仓库内种子模板目录**（首批 10–20 个常见系统模板，YAML + 版本号）+ "从模板创建" API（schema 校验 → 映射 → 复用 `tools.py` 既有创建路径落库）+ 安装计数与「已安装」视图；admin-web 新增市场页与创建向导页。创建的连接器与手工创建**同构**（同一存储、同一 test 链路、同一 `external_tools` 注入路径），自动注册为 018 能力资产（`type=connector`）。凭证存储加密依赖 034（credential-encryption，并行撰写）：034 落地前保持现状，落地后验收无明文。

## Technical Context

**Language/Version**: Python 3.11+（admin-api，FastAPI + pydantic v2）；TypeScript 5（admin-web，Vue 3 + naive-ui）

**Primary Dependencies**: FastAPI、pydantic、PyYAML（种子模板加载）；Vue 3 SFC、naive-ui；**chat-api 侧零改动**（注入/审计路径纯复用）

**Storage**: 模板 = 仓库内种子 YAML（`services/admin-api/app/connector_templates/*.yaml`，启动加载 + mtime 热加载，与 chat-api `ModelRouter._load_config` 同模式）；安装记录 = admin-api 新集合 `connector_installs`（模板 × 租户 × 工具）；连接器本体 = **既有 external_tools 存储**（同一路径，硬约束）

**Testing**: pytest（admin-api，`tests/test_connector_market.py`：种子加载/schema 校验/同构断言/安装计数/租户隔离）；chat-api 既有工具调用测试回归；前端 `@vue/compiler-sfc` 单文件编译校验（替代全量 build，与 031 同约束）

**Target Platform**: Docker Compose（admin-api + admin-web + chat-api）；自托管 Linux/Docker

**Project Type**: web-service（admin-api）+ web-app（admin-web），pnpm 工作区

**Performance Goals**: 模板加载一次进内存 + mtime 热加载；市场列表/详情为内存过滤，无外部依赖；创建链路与既有 `tools.py` 创建同延迟量级

**Constraints**: MUST NOT 新建第二套工具存储/注入/test 路径（同构是硬约束）；种子文件 MUST 只含占位符（无真实凭证）；模板 `authType` MUST 对齐 `external_tools` 既有注入能力（`none`/`bearer`/`api_key`）；安装计数与已安装视图 MUST 按租户隔离；前端文案保持中英双语文案键

**Scale/Scope**: 首批 18 个模板种子（5 类别，见下）；2 组新 API（模板目录 + 安装计数/已安装）+ 1 个向导创建 API；1 个新前端页（市场列表/详情/向导）；018 资产注册 1 处接线；chat-api 0 改动

### 首批模板建议清单（10–20 个，运营可调，数量不承诺）

| 类别 | 模板（建议 18 个） | authType |
| --- | --- | --- |
| OA/协同（4） | 钉钉机器人 Webhook、飞书机器人 Webhook、企业微信应用消息、泛微 e-cology REST | api_key / none |
| ERP（3） | 用友 NC Cloud REST、金蝶云星空 REST、SAP OData（预留，首期可降级为通用 REST） | api_key |
| 数据平台（4） | MySQL 查询 API、ClickHouse HTTP、Elasticsearch HTTP、GaussDB(DWS) | api_key / none |
| DevOps（4） | GitLab API、Jenkins REST、Prometheus HTTP、Grafana HTTP | api_key / none |
| 通知/IM（3） | Slack Webhook、飞书消息推送、钉钉工作通知 | none / api_key |

每个模板 MUST 含：参数 schema（必填/类型/说明）、示例参数（占位符）、测试建议（探测端点/预期状态码）、认证类型。SAP OData 若首期协议复杂，按通用 REST 模板降级落地（YAGNI）。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Specification-First**: ✅ 本 spec/plan/tasks 三件套先行，代码未开工；模板形态/首批范围/可见性/存量关系/"30 分钟"口径/资产关联/034 依赖七项决策先拍板。
- **II. Enterprise Production Readiness**: ✅ 复用既有 CRUD/test/门禁链路（生产已验证）；模板损坏跳过 + 告警；034 未落地时明确降级行为（不阻塞、不假装安全）。
- **III. Security and Data Protection**: ✅ 种子只含占位凭证；凭证写入依赖 034 加密（落地后验收无明文）；Agent 侧注入语义不变（明文不出服务端）；门禁与审计不变。
- **IV. Cross-Platform and i18n**: ✅ 市场页/向导文案走 `t()` 中文 key 回退（与 031 同约束）；模板描述中英双语字段。
- **V. Observability and Simplicity**: ✅ 不建平行工具体系（同构硬约束）；安装计数为单一计数器；模板加载复用既有 mtime 热加载模式；审计复用 `enterprise_capabilities/tools/service.py`。

## Project Structure

### Documentation (this feature)

```text
specs/041-connector-market/
├── spec.md              # 特性规约（FR/SC/决策表）
├── plan.md              # 本文件
└── tasks.md             # 任务清单（全新特性，全部未勾选）
```

### Source Code (repository root)

```text
services/admin-api/
├── app/connector_templates/*.yaml        # 【新增】首批 18 个模板种子（含 version，占位凭证）
├── app/services/connector_templates.py   # 【新增】种子加载（mtime 热加载 + 损坏跳过告警）+ schema 校验 + 安装记录
├── app/api/routes/connector_market.py    # 【新增】模板目录（列表/详情/筛选/搜索）+ 安装计数/已安装 + 从模板创建
├── app/api/routes/tools.py               # 【复用】创建/test/discover 链路——向导最终落库与测试走这里（不改其语义）
├── app/api/routes/capability_assets.py   # 【复用】连接器资产注册（type=connector，018 既有路由面）
└── tests/test_connector_market.py        # 【新增】加载/校验/同构/计数/租户隔离单测

services/chat-api/
├── app/services/external_tools.py                # 【复用】凭证服务端注入（947-977），零改动
└── app/enterprise_capabilities/tools/service.py  # 【复用】全程 audit，零改动

apps/admin-web/
├── src/api/connectorMarket.ts              # 【新增】市场 API 客户端（目录/详情/创建/计数/已安装）
├── src/views/connectors/ConnectorMarketPage.vue  # 【新增】市场列表 + 模板详情 + 从模板创建向导（含测试连接）
└── src/views/tools/ToolsPage.vue           # 【复用】既有工具管理页——「已安装」视图数据契约参照（不改其行为）
```

**Structure Decision**: 完全复用 admin-api 既有路由/服务分层与 admin-web 视图/API 客户端模式（参照 `tools.py` + `api/tools.ts` + `views/tools/`）；模板种子为仓库内新目录（决策 1）；连接器本体落既有存储（决策 4）；chat-api 零改动（注入/审计纯复用）。

## Complexity Tracking

> 无 constitution 违规，无需复杂度论证。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | — | — |
