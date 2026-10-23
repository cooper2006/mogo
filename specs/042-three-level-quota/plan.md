# Implementation Plan: 三级配额（团队/项目级）（042-three-level-quota）

**Branch**: `042-three-level-quota` | **Date**: 2026-10-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/042-three-level-quota/spec.md`

**Note**: **全新特性**（整合方案 §4.11 立项，代码尚未开工）——本计划先于实现，与 031 的"代码先行回溯补规格"不同；tasks.md 全部任务未勾选。

## Summary

把 020 配额体系从"租户 + 用户"两级扩展为"团队/项目 + 租户 + 用户"三级：`quota_policy` 的 `scope_type` 增加 `team|project`，三层策略同时生效时扣减取各层最小、单层超限即拒（fail-closed），未配置层延续 decision 12 的 unlimited 默认不参与取小。团队层复用部门树 `org_units` + `end_user_org_relations`（零新建实体）；项目层新建轻量分组集合 `quota_projects`（与桌面 Code `projects` 端点语义隔离）。管理端在既有流量分配页（`TrafficAllocationsPage.vue`）旁扩展团队/项目配置入口；超限/接近阈值（默认 20%）告警复用 008 异常枚举口径（`ANOMALY_STATUSES`）与审计落点，不新建推送通道。001 配额门禁层零改动，其消费点自动获得三层语义。

## Technical Context

**Language/Version**: Python 3.11+（chat-api 与 admin-api，FastAPI + pydantic v2 + motor/MongoDB）；TypeScript 5（admin-web，Vue 3 + naive-ui）

**Primary Dependencies**: 既有 `app/core/quota_policy.py` 模块（chat-api / admin-api 同名副本）、`app/services/setup_quota.py`、`api/routes/traffic_allocations.py`、`api/dashboard_metrics.py`；**不引入任何新第三方依赖**

**Storage**: MongoDB——复用 `user_quota_policies`（`scope_type` 扩展 team/project）、`user_token_allocation_logs`、`org_quota_policies`、`end_user_org_relations`、`org_units`；**新增** `quota_projects`（项目分组，成员内嵌数组）

**Testing**: pytest（chat-api / admin-api 既有测试树）；新增三层解析与取小语义单测、多归属取严单测、`get_quota_summary` 改造前后等价回归测试；前端 SFC 编译校验（`@vue/compiler-sfc`）+ 手工联调

**Target Platform**: Docker Compose（chat-api + admin-api + admin-web 同栈部署）

**Project Type**: web-service（双后端服务）+ web-app（admin-web 管理前端）

**Performance Goals**: `get_quota_summary` 位于每次对话入口的同步路径（`api/endpoints/dsh_chat.py:172/279`、`llm/configured_models.py:396-400`、`scheduled_tasks/runner.py:39`）；三层扩展 MUST 保持 **O(1) 次额外查询**：团队/项目策略按 `(tenant_id, scope_type, scope_id)` 点查（复用 `scope_id` 索引形态），成员反查一次聚合，不引入全表扫描或 N+1

**Constraints**: 001 门禁层（`governance/layers/quota.py`）零改动；decision 12 unlimited 默认与 020 FR-035~038 口径不回退；`user_quota_policies` 集合名不改、不做存量数据迁移；admin-web 新文案走 `t()` 中文 key 回退保持中英双语；两份 `quota_policy.py`（chat-api / admin-api）行为保持同步

**Scale/Scope**: 2 个后端模块修改 + 1 个新服务模块 + 1 个路由文件扩展 + 1 个告警口径扩展 + 1 个前端页面扩展；0 新依赖、0 新集合索引类型

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Specification-First**: ✅ 本三件套（spec/plan/tasks）先于任何代码落地；已定决策表覆盖实体来源、扣减语义、默认策略、告警口径、001 接口边界五个拍板点。
- **II. Enterprise Production Readiness**: ✅ 失败路径显式定义：新层查询异常按 unlimited 跳过并记日志（与 `governance/layers/quota.py` L46-49"unreadable row must not block"同源），不因新层引入全量拒绝面；单层超限拒绝信息指明层名，可运维定位；等价回归测试保证存量租户零漂移。
- **III. Security and Data Protection**: ✅ 无新增 PII（项目分组成员 ID 属既有租户内数据）；告警事件脱敏口径沿用 001/008；策略变更全审计（`user_token_allocation_logs`）。
- **IV. Cross-Platform and i18n**: ✅ admin-web 新配置入口文案走 `t()` 中文 key 回退（`locales/messages.ts` 既有模式），保持中英双语。
- **V. Observability and Simplicity**: ✅ 三层解析集中在 `get_quota_summary` 单函数内扩展，不新增编排层/调度器；复用既有集合与页面，唯一新集合 `quota_projects` 为最小实体；YAGNI（不做子树聚合、推送通道、计费）。

## Project Structure

### Documentation (this feature)

```text
specs/042-three-level-quota/
├── spec.md              # 特性规约（定位/决策/FR/SC/关联特性）
├── plan.md              # 本文件
└── tasks.md             # 任务清单（Phase 0-3，全部未勾选）
```

### Source Code (repository root)

```text
services/chat-api/
└── app/core/quota_policy.py            # 【修改】scope_type 扩展 team/project；三层解析；
                                          #  get_quota_summary 三层取小 + 分层明细 + limitingScope；
                                          #  assert_quota_available 错误信息指明超限层

services/admin-api/
├── app/core/quota_policy.py            # 【修改】同名副本同步（admin-api 侧 get_quota_summary
│                                        #  被 governance/quota.py 与 traffic_allocations.py 消费）
├── app/services/quota_projects.py      # 【新增】项目分组 CRUD + 成员维护（轻量服务，
│                                        #  集合 quota_projects；docstring 声明与桌面 Code
│                                        #  projects 端点的语义隔离）
├── app/api/routes/traffic_allocations.py  # 【修改】团队/项目策略配置端点（与既有
│                                          #  update_org_quota_policy / user policy 端点同级），
│                                          #  复用既有鉴权依赖与日志写入模式
└── app/api/dashboard_metrics.py        # 【修改】ANOMALY_STATUSES 增加 quota 类状态口径
                                          #  （超限/接近阈值的驾驶舱异常统计入口）

apps/admin-web/
├── src/api/traffic-allocations.ts      # 【修改】团队/项目配置 API 客户端（既有文件扩展）
└── src/views/organizations/TrafficAllocationsPage.vue  # 【修改】团队额度（部门树选择）
                                          #  + 项目分组 CRUD 配置区，与既有 org/user 同级

# 【复用不改】services/admin-api/app/governance/layers/quota.py（001 配额门禁层，零改动）
# 【复用不改】services/admin-api/app/api/routes/directory.py（部门树 GET /departments/tree）
# 【复用不改】services/admin-api/app/services/setup_quota.py（既有 configure_setup_quotas 签名与行为不变）
# 【复用不改】集合 org_units / end_user_org_relations / user_quota_overrides
```

**Structure Decision**: 复用既有 monorepo 布局与"流量分配页作为配额配置单一入口"的现状（`/organizations/traffic?open=quota` 已被 ModelsPage.vue 引用为配额配置导航目标），不新增页面与路由；团队层借道部门树（020 已建）、项目层以最小新集合补齐"跨部门横向分组"这一部门树表达不了的形状；三层语义收口在 `get_quota_summary` 单函数，001/008 两个消费方零改动接入。

## Complexity Tracking

> 无 constitution 违规，无需复杂度论证。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | — | — |

**已评估并拒绝的复杂度**（记录备查）：① 部门子树自动聚合限额——需定义中层归属与双重计量口径，超出 MVP，留后续；② 独立告警推送通道——008 Non-Goal 明示属独立能力，本特性只接异常枚举；③ 新集合 `team_quota_policies`/`project_quota_policies` 平行于既有集合——`user_quota_policies` 的 `(tenant_id, scope_type, scope_id)` 结构已天然支持，新集合纯属冗余。
