# Implementation Plan: 平台化多租户（Platform Multi-Tenancy）

**Branch**: `020-platform-multi-tenancy` | **Date**: 2026-09-30 | **Spec**: [spec.md](./spec.md)

**Input**: 补齐租户供给能力，使一套部署承载多个企业；新增平台管理员角色管理租户生命周期。数据层与认证层已具备多租户能力，本特性不重建这两层。

## Summary

当前 `setup.py::setup_initialize()` 把"建租户全过程"内联在路由函数里（第 343–463 行），且 `system_bootstrap` 为单例、租户标识仅此一处生成，导致一套部署只能产出一个企业。

本方案：

1. 将建租户流程抽为独立服务 `provision_tenant()`，成为**唯一**供给入口；
2. 新增 `tenants` 集合作为平台层租户主表，与租户内 `organizations` 分层；
3. 引入平台管理员（专用保留租户标识 `__platform__`），把首次启动引导改造为"部署检测 → 创建平台超管 → 完成"，租户创建独立为平台控制台功能；
4. 部署检测从供给链路剥离，仅服务于引导流程且只卡数据库；
5. 补齐生命周期：归档 / 恢复 / 彻底清理；配额默认不限额。

## Technical Context

**Language/Version**: Python 3.13（admin-api / chat-api 既有栈）；前端 Vue 3 + TypeScript（pnpm 工作区）

**Primary Dependencies**: FastAPI、Motor/PyMongo、Pydantic Settings、Weaviate（向量）、Redis

**Storage**: MongoDB（主存储，全部集合按 `main_id` 分区）、Weaviate（向量）、本地文件系统（知识库文档、头像）

**Testing**: pytest（admin-api 既有测试）

**Target Platform**: 自托管 Docker Compose（Linux / Windows 安装器）

**Project Type**: 既有服务扩展（brownfield）

**Performance Goals**: 创建租户为低频操作，无特殊性能要求；彻底清理需异步执行并回报进度

**Constraints**: 不得破坏现有单租户部署的既有行为；存量升级必须零数据丢失

**Scale/Scope**: 单部署承载数个到数十个企业；11 个实施阶段

## 现有实现事实（contract 依据）

**供给链路**

- `services/admin-api/app/api/routes/setup.py`：`setup_initialize()` 第 343–463 行内联了完整建租户流程（生成标识 → 建账号组 → 建管理员 → 建根部门 → 建员工 → upsert 组织 → 写关系 → 岗位角色 → 配额 → 模型 → 知识库配置 → 搜索配置）
- `_next_main_id()`：全仓库**唯一**的租户标识生成点
- `_deployment_services()`：6 项服务全绿才放行（MongoDB / Redis / 存储 / Chat API / 文档处理 / Weaviate），否则 503
- `app/repositories/setup_repository.py`：`system_bootstrap` 以 `_id: "singleton"` 存储，`mark_setup_completed()` 全局置 `completed=True`；`_ensure_setup_open()` 之后所有 setup 端点 409
- `app/services/setup_cleanup.py`：`cleanup_failed_setup()` 按 `main_id` 删除 **17** 个集合

**认证与隔离**

- `app/api/routes/auth.py`：`POST /login` 接受 `mainId`；不带时 `list_accounts_by_username` 跨租户查，命中多个走 challenge → `POST /login/select-tenant`
- `auth.py:228`：登录兜底会用 `setup_state.main_id` 作为默认租户 ← **多租户下为错误行为**
- `app/api/deps.py:24`：`main_id = str(subject.get("main_id") or settings.bootstrap_main_id)`
- `or "default"` 兜底共 **114 处**（admin-api 81 + chat-api 33），集中在 `knowledge_documents.py`(27)、`skills.py`(17)、`tools.py`(11)、`analytics.py`(5)、`hooks.py`(4)

**管理员预置**

- `app/core/config.py:16-21`：`bootstrap_admin_*` 六项配置；`app/services/admin_bootstrap.py` 取其创建**租户内**管理员（标识来自 `setup_state`）
- `bootstrap_admin_role_name` 默认值误写为"平台超级管理员"
- `app/main.py:49`：启动钩子调用 `bootstrap_admin_user()`

**配额**

- `app/core/quota_policy.py`：`get_quota_summary()` 分两条路径——企业空间读 `org_quota_policies`；个人/社区空间读 `organizations.total_points / used_points`
- `assert_quota_available()`：`status != active` 或 `remainingPoints <= 0` 即抛 `QuotaExceededError`
- `ensure_org_quota_policy()` / `ensure_default_user_policy()` 惰性默认 `total_tokens = 0`、`quota_tokens = 0` ← **留空即拦截**

**向量与租户枚举**

- `services/chat-api/app/knowledge/retrieval/retrieval_client.py:45`：按 `mainId` 过滤检索
- `app/services/directory_bootstrap.py:15` 与 `app/services/employee_tenant_identity.py:37,40`：`distinct("main_id")`，过滤 `$nin: [None, "", "default"]` ← **需追加排除 `__platform__`**

## Constitution Check

*GATE: 必须通过后方可进入设计。*

| 原则 | 结果 | 说明 |
|---|---|---|
| I. Specification-First | ✅ | 本文件为 `/speckit-plan` 产出；spec.md 已先行完成 |
| II. Enterprise Production Readiness | ✅ | 全部生命周期操作写入 `system_audit`；彻底清理有确认与进度；不引入未验证镜像 |
| III. Security and Data Protection | ✅ | 隔离加固是核心目标之一；`deps` 入口强校验租户标识；凭据仍走 `.env.example` 约定，不入仓库 |
| IV. Cross-Platform and i18n | ✅ | 新增界面文案需中英双语；无平台特定依赖 |
| V. Observability and Simplicity | ✅ | 遵循 YAGNI：不新建账号体系，复用既有 `admin_accounts` + 保留标识；不引入审批流 |
| Agent Operating Rules | ✅ | 不删除文件；每轮更新 `docs/WORK_LOG.md`；只改必要文件 |

**结论**：无违规项，无需填写 Complexity Tracking。

## Project Structure

### Documentation (this feature)

```text
specs/020-platform-multi-tenancy/
├── plan.md                    # 本文件（/speckit-plan 产出）
├── spec.md                    # /speckit-specify 产出
├── quickstart.md              # Phase 1 产出
├── contracts/
│   └── tenants.md             # Phase 1 产出：平台租户 API 契约
├── checklists/
│   └── requirements.md        # 规格质量门禁
└── tasks.md                   # Phase 2 产出（/speckit-tasks）
```

### Source Code (repository root)

```text
services/admin-api/app/
├── api/routes/
│   ├── setup.py               # [改] 引导流程：部署检测 + 创建平台超管；移除建租户内联逻辑
│   ├── platform/
│   │   └── tenants.py         # [新] /api/platform/tenants* 与 /api/platform/system/health
│   └── auth.py                # [改] 移除 setup_state 兜底；归档租户禁止登录
├── api/deps.py                # [改] 新增 get_current_platform_admin；入口强校验 main_id
├── services/
│   ├── tenant_provisioning.py # [新] provision_tenant() —— 唯一供给入口
│   ├── tenant_registry.py     # [新] tenants 集合读写 + 存量回填 + 墓碑清理
│   ├── tenant_purge.py        # [新] 彻底清理（Mongo + 向量 + 文件）异步任务
│   ├── admin_bootstrap.py     # [改] 配置项改名
│   └── platform_bootstrap.py  # [新] 平台超管 ensure
├── core/
│   ├── config.py              # [改] bootstrap_admin_* → tenant_bootstrap_admin_*；新增 platform_admin_*
│   └── quota_policy.py        # [改] unlimited 短路（企业 + 个人两条路径）
├── repositories/
│   └── setup_repository.py    # [改] singleton 语义：平台超管是否已创建
└── main.py                    # [改] 启动钩子追加 bootstrap_platform_admin()

services/admin-api/app/services/
├── directory_bootstrap.py     # [改] 排除 __platform__；按 tenants.status=active 枚举
└── employee_tenant_identity.py# [改] 同上

apps/admin-web/src/
├── views/auth/SetupPage.vue          # [改] 6 步 → 3 步（部署检测 → 创建平台超管 → 完成）
├── views/platform/
│   ├── TenantsPage.vue               # [新] 租户列表 / 归档 / 恢复 / 清理 / 重置密码
│   └── SystemHealthPage.vue          # [新] 服务健康只读
├── components/platform/
│   └── TenantCreateForm.vue          # [新] 唯一租户创建表单（3 必填 + 折叠可选）
└── router/routes.ts                  # [改] 新增 /platform 路由组
```

**Structure Decision**: 沿用既有 admin-api 分层（routes / services / repositories / core），前端沿用既有 views + components 划分。新增代码集中在 `tenant_*` 与 `platform_*` 命名下，不新建顶层模块。

## 实施阶段映射

| 阶段 | 内容 | 对应 spec |
|---|---|---|
| 1 | 抽 `provision_tenant()`（`setup.py` 343–463 行），setup 路由改为调用。纯重构 | FR-001~005 |
| 2 | `TenantCreateForm` 字段简化 + 部署检测移出供给链路 | FR-002、FR-003 |
| 3 | 新增 `tenants` 集合 + 索引 + 存量回填 | FR-039 |
| 4 | `bootstrap_admin_*` → `tenant_bootstrap_admin_*` 改名 | — |
| 5 | 引导向导改造（6 步 → 3 步）；`system_bootstrap` 语义变更；移除 `auth.py:228` 兜底 | FR-011~014、FR-017 |
| 6 | 平台超管：`__platform__` + 环境补建 + 鉴权依赖 + 反向守卫 + 枚举过滤 | FR-006~010、FR-019 |
| 7 | 配额不限额（企业 + 个人两条路径） | FR-035~038 |
| 8 | 租户管理 API + 平台前端页 + 空状态引导 | FR-020~023 |
| 9 | 归档 + 恢复 + 禁止登录 + 枚举排除非 active | FR-024~027 |
| 10 | 彻底清理（三层 + 异步进度 + 墓碑 1 个月） | FR-028~034 |
| 11 | `deps` 入口 main_id 强校验 | FR-018 |

## 关键风险与对策

| 风险 | 对策 |
|---|---|
| 存量升级后无平台管理员（阻断性） | 环境配置为升级必读项；未配置时启动日志与 `/api/setup/status` 明确告警 |
| `__platform__` 被当作普通租户处理 | `directory_bootstrap.py:15`、`employee_tenant_identity.py:37,40` 追加排除；`provision_tenant()` 入口拒绝该标识 |
| 彻底清理残留（尤其向量） | 重新盘点集合清单（现有 17 个 vs 实际 72 个集合常量）；向量按 `mainId` 清除；磁盘按标识前缀清除 |
| 跨租户数据泄露 | `deps` 入口强校验；逐步消除 114 处 `or "default"` 兜底 |
| 新建租户被额度立即拦截 | `unlimited` 布尔短路，而非"给个大数字" |
