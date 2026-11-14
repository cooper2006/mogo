# Implementation Plan: 数字员工档案（051-digital-employee-profile）

**Branch**: `051-digital-employee-profile` | **Date**: 2026-11-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/051-digital-employee-profile/spec.md`

**Note**: **全新特性、产品主线**（StaffDeck 整合方案 §4.2 立项，代码尚未开工）——B1 实体与绑定先行，B2 分发与路由随后；tasks 全部未勾选。

## Summary

新增"数字员工"组装层，横跨双服务与双前端：

- **员工实体（B1）**：chat-api 新增 `app/employees/`（实体 + 档案物化 + 会话注入）；admin-api 新增员工管理路由（CRUD + 审计）；`employees` 集合经 027 门面双后端。
- **会话绑定（B1）**：会话创建接受可选 `employee_id`，创建时物化 `EmployeeProfile` 快照注入执行边界（与 001 门禁取交集）、知识库、记忆 scope、模型配置；未声明员工的会话路径零改动。
- **资产与门户（B1）**：045 `capability_assets` 注册表扩 `employee` 类型；037 门户目录与认领审批链路复用。
- **IM 路由（B2）**：013 ChannelRouter 扩渠道-员工绑定 + 确定性规则路由 + 默认员工兜底。
- **员工级 Key（B2）**：022 凭证体系扩展员工 scope。
- **前端**：admin-web 员工管理页；user-web 门户员工目录 + 会话员工选择（中英双语）。

## Technical Context

**Language/Version**: Python 3.13（chat-api / admin-api）；Vue 3 + TypeScript（双前端）

**Primary Dependencies**: 既有 006 白名单范式（参照不改造）、045 capability_assets、037 portal、001 governance、017 memory、005 knowledge、019 harness_config、040 模型路由、013 im_gateway、022 security、035 token_usage；**不引入新第三方依赖**

**Storage**: 新增 `employees` / `employee_claims` / `channel_employee_bindings`（B2）集合（027 门面双后端）；会话档案快照内嵌会话文档（避免跨集合漂移）

**Testing**: pytest 双服务（chat-api `tests/employees/`、admin-api `tests/test_employees_admin.py`）；既有会话/门禁/IM 测试零修改全绿；前端 SFC + vue-tsc

**Target Platform**: Docker Compose（chat-api + admin-api + 双前端）

**Project Type**: web-service 全栈特性（产品形态层）

**Performance Goals**: 档案注入为会话创建时一次性物化（读放大 ≤ 一次档案查询 + 引用校验）；热路径（会话内每次调用）只读会话内快照，不重复查员工表

**Constraints**: 未声明员工会话零回归（FR-003）；治理取交集不旁路（FR-002）；四概念边界 OQ-1 clarify 前不进入实现；B2 依赖 B1 完成；员工模板上架依赖 053

**Scale/Scope**: chat-api 1 新模块 + 会话创建接线；admin-api 1 新路由模块 + 资产类型扩展；双前端各 1–2 页；B2 IM 路由 + Key 扩展；0 新依赖

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Specification-First**: ✅ 三件套先于代码；七决策已拍板，四 OQ 登记 clarify 门禁（OQ-1 为 ADR 级）。
- **II. Enterprise Production Readiness**: ✅ 失败路径显式：未开通认领拒绝、失效引用按 OQ-2 口径、停用员工新会话拒绝；在途会话快照保护；无不可观测路径（全审计）。
- **III. Security and Data Protection**: ✅ 租户隔离 fail-closed；员工边界与 001 取交集、R4 恒拒；员工级 Key 加密存储（022）；管理操作 system_audit。
- **IV. Cross-Platform and i18n**: ✅ 双前端中英双语（FR-012）；自托管部署无平台假设变化。
- **V. Observability and Simplicity**: ✅ 组装而非另起：边界/知识/记忆/模型/门户/审计全部引用既有体系；员工只是注入层，不新执行引擎；成本经 035 既有链路（不建无写方维度，048 教训）。

## Project Structure

### Documentation (this feature)

```text
specs/051-digital-employee-profile/
├── spec.md              # 特性规约（B1/B2 两阶段）
├── plan.md              # 本文件
├── tasks.md             # 任务清单（全部未勾选）
└── checklists/requirements.md
```

### Source Code (repository root)

```text
services/chat-api/app/employees/
├── __init__.py            # 【新增】
├── model.py               # 【新增】Employee / EmployeeProfile / 状态机
├── repository.py          # 【新增】employees 集合（027 门面）+ 可见性（049 口径）
├── profile.py             # 【新增】档案物化（引用校验 + 快照）
└── injection.py           # 【新增】会话注入（边界交集/知识库/记忆/模型）

services/chat-api/app/api/endpoints/
├── employees.py           # 【新增】用户侧：可用员工列表/会话选择
└── sessions.py            # 【修改】创建接受 employee_id + 档案注入（未声明路径不变）

services/chat-api/app/im_gateway/
└── router.py              # 【修改·B2】渠道-员工绑定 + 规则路由 + 默认兜底

services/admin-api/app/api/routes/
└── employees.py           # 【新增】管理端 CRUD + 启停 + 审计

services/admin-api/app/services/capability_assets/
└── registry.py            # 【修改】asset_type 扩 employee

apps/admin-web/src/views/employees/   # 【新增】员工管理页（i18n）
apps/user-web/src/                    # 【修改】门户员工目录 + 会话员工选择（i18n）

services/chat-api/tests/employees/    # 【新增】实体/注入/交集/零回归
services/admin-api/tests/test_employees_admin.py  # 【新增】
```

**Structure Decision**: 员工实体放 chat-api（会话注入热路径所在），管理端 CRUD 放 admin-api（与 006/045 管理面同侧）——双服务经同一 `employees` 集合读写，口径参照 049 双服务 `quota_policy.py` 同口径先例（共享口径测试守护）。档案物化为会话内快照：热路径零额外查询，档案变更不影响在途会话（FR-010）。

## Complexity Tracking

> 无 constitution 违规。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | — | — |

**已评估并拒绝的复杂度**：① 改造 position_roles 为 agent 实体——人的 RBAC 与 agent 档案语义不同，混改破坏 006 既有口径（046 同名概念教训）；新建实体 + 沿用范式。② 员工独立执行引擎/运行时——员工只是档案注入层，DSH train 不动。③ LLM 意图分类路由首期——非确定性且依赖模型质量，确定性规则先行（决策 #6）。④ 新建员工计量维度——035 `agent_id` 链路已承接，048 教训：无独立写方的维度不建。