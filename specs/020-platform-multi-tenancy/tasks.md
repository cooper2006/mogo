# Tasks: 平台化多租户（020）

> ⚠️ **落地审计（2026-10-03）：判定 `partial`** —— 本文件 `[x]` 只代表**任务条目已勾选**，不代表功能落地。
> 按今天的标准（生产调用方/消费方/真实数据源/端到端可证伪）重检，本特性的结论是：租户供给/平台管理员/生命周期/隔离守卫真实落地；但配额"不限额"未贯通 chat-api，新租户成员发消息被 402。
> 详见 [`specs/LANDING_AUDIT_2026-10-03.md`](../LANDING_AUDIT_2026-10-03.md)。

**Input**: Design documents from `/specs/020-platform-multi-tenancy/`

**Prerequisites**: plan.md (required), spec.md (required)

**Clarify Decisions (governing tasks, 2026-09-30，共 19 项已确认)**:

1. 平台超管形态 = 复用 `admin_accounts` + 保留标识 `__platform__`
2. 租户主表 = **新增 `tenants` 集合**，`organizations` 退为租户内档案
3. 删除租户 = 软归档，**允许恢复**
4. 配额默认 = **不限额**
5. 平台超管初始化 = **首次启动向导为主 + 环境变量预置为辅**
6. `bootstrap_admin_*` → `tenant_bootstrap_admin_*`
7. 平台超管**仅管生命周期**，不查看租户内业务数据
8. Community 个人空间**也要**不限额
9. 初始化简化 = 租户创建表单字段设计（同一份表单）
10. 部署检测 + 创建超级管理员**合并**为引导向导；租户创建表单**独立**
11. 引导**不**创建第一个租户，用空状态引导替代
12. `/setup` 已存在平台超管时降级为快捷入口
13. 归档租户的 `admin_username` **禁止登录**
14. 重置密码后**不强制**改密
15. 租户管理**同时提供归档与彻底清理**
16. 彻底清理**不需要**二次审批
17. 墓碑记录保留 **1 个月**
18. 归档租户**不计入**授权数
19. 平台超管**仅一个**

**Checklist Gate**: `checklists/requirements.md` 已 100% 勾选。

**Organization**: 后端落点 = `services/admin-api/app/services/tenant_*.py`（新）+ `app/api/routes/platform/`（新）+ 既有 `setup.py` / `auth.py` / `deps.py` / `quota_policy.py` 改造；前端落点 = `apps/admin-web/src/views/platform/`（新）+ `components/platform/TenantCreateForm.vue`（新）+ `views/auth/SetupPage.vue` 改造。

**阶段映射**: 括号内为 plan.md 的实施阶段编号。

---

## Phase 1: Setup（阶段 1 —— 抽取供给入口，纯重构）

- [x] T001 新建 `services/admin-api/app/services/tenant_provisioning.py`，定义 `provision_tenant()` 签名与 `ProvisionResult`
- [x] T002 将 `setup.py` 第 343–463 行的建租户流程迁入 `provision_tenant()`（生成标识 → 账号组 → 管理员 → 根部门 → 员工 → 组织 → 关系 → 岗位角色 → 配额 → 模型 → 知识库 → 搜索）
- [x] T003 `setup.py::setup_initialize()` 改为校验后调用 `provision_tenant()`，行为保持不变
- [x] T004 补回归测试：单租户初始化行为与重构前一致（含失败回滚）

## Phase 2: Foundational（阶段 2–4，阻塞性前置）

- [x] T005 [P] 阶段 2：`provision_tenant()` 内各可选块加守卫 —— `employee` / `model` / `additionalModels` / `externalSearch` / `quota` 全为 `None` 时跳过且不校验连通性
- [x] T006 [P] 阶段 2：从 `provision_tenant()` 与 `/initialize` 移除 `_deployment_services()` 门禁
- [x] T007 [P] 阶段 3：新建 `app/services/tenant_registry.py` —— `tenants` 集合读写、`ensure_indexes()`、`ensure_tenant_record()`
- [x] T008 [P] 阶段 3：实现存量回填迁移（按 `admin_accounts.distinct("tenant_id")` 幂等登记，排除保留标识）
- [x] T009 [P] 阶段 4：`config.py` 6 项 `bootstrap_admin_*` → `tenant_bootstrap_admin_*`
- [x] T010 [P] 阶段 4：同步 `admin_bootstrap.py`、`.env.example`、`docker-compose.yml`、`deploy/production/docker-compose.portainer.yml.tpl`
- [x] T011 [P] 阶段 4：`bootstrap_admin_role_name` 默认值由"平台超级管理员"改为"租户管理员"（消除误导）

## Phase 3: User Story 1 (P1) —— 平台引导：部署检测 + 创建平台超管（阶段 5）

**Goal**: 全新部署首次启动可通过引导创建平台超管；引导不创建任何租户。
**独立测试**: 仅 MongoDB 可用时也能完成引导；完成后登录进入空控制台。

- [x] T012 定义 `PLATFORM_TENANT_ID = "__platform__"` 常量与其校验工具
- [x] T013 `setup_repository.py`：singleton 语义改为"平台超管是否已创建"，`_ensure_setup_open()` 随之调整
- [x] T014 `setup.py` 新增 `POST /api/setup/platform-admin`（已存在返回 409）
- [x] T015 部署检测门禁收紧：仅 MongoDB 必绿，其余 5 项降级为告警（`services` 增 `core` 标记）
- [x] T016 `GET /api/setup/status` 增加 `platformAdminMissing` 告警字段
- [x] T017 前端 `SetupPage.vue`：6 步 → 3 步（部署检测 → 创建平台超管 → 完成），删除原组织/模型/搜索步骤
- [x] T018 前端完成页改为引导登录 + "去创建第一个租户"，不再展示租户 ID 与访问地址
- [x] T019 `/setup` 已存在平台超管时降级为快捷入口（决策 12）

## Phase 4: User Story 3 (P1) —— 租户隔离与登录（阶段 11）

**Goal**: 跨租户零可见；缺失或保留标识一律拒绝，不回退默认租户。
**独立测试**: 两租户同名账号各自只见自己数据；多归属账号登录出现选择步骤。

- [x] T020 [P] `auth.py:228` 移除 `setup_state.tenant_id` 兜底，改为一律走跨租户搜索 + challenge
- [x] T021 [P] `deps.py::get_current_admin_user` 入口强校验：`tenant_id` 为空 / `default` / `__platform__` 按路由类型分别拒绝
- [x] T022 [P] 新增 `get_current_platform_admin` 依赖；业务路由加反向守卫拒绝 `__platform__`
- [x] T023 [P] `directory_bootstrap.py:15` 与 `employee_tenant_identity.py:37,40` 过滤追加 `"__platform__"`
- [x] T024 补隔离测试：跨租户读取返回空；保留标识调业务接口 403

## Phase 5: User Story 2 + 4 (P1/P2) —— 创建租户与生命周期管理（阶段 8）

**Goal**: 3 个字段创建租户；平台侧可列表/改名/启停/重置密码，且不含业务指标。
**独立测试**: 仅填 3 项创建成功；列表不含成员数与用量。

- [x] T025 新建 `app/api/routes/platform/tenants.py`，实现 `POST/GET/PATCH` 与 `reset-password`
- [x] T026 `provision_tenant()` 内新增"写 `tenants` 记录"步骤（阶段 3 的 registry 接入）
- [x] T027 租户列表响应字段裁剪：仅生命周期字段，禁含业务指标
- [x] T028 前端 `components/platform/TenantCreateForm.vue`：3 必填 + 折叠可选（员工/LLM/搜索/配额）
- [x] T029 前端 `views/platform/TenantsPage.vue`：列表 / 新建 / 详情 / 重置密码
- [x] T030 前端控制台**空状态引导**（"还没有租户，立即创建"）—— 决策 11 必需
- [x] T031 `router/routes.ts` 增加 `/platform` 路由组，按 `tenantId === '__platform__'` 控制显隐
- [x] T032 登录页增加"平台管理员"入口，提交 `tenantId: __platform__`

## Phase 6: User Story 8 (P3) —— 配额默认不限额（阶段 7）

**Goal**: 新建租户零配额配置即可正常使用；两条计量路径都生效。
**独立测试**: 新租户成员不被额度拦截；改为限额后按预期拦截。

- [x] T033 [P] `org_quota_policies` 增 `unlimited` 字段；`get_quota_summary()` 企业分支短路并输出 `unlimited`
- [x] T034 [P] `organizations` 增 `points_unlimited`；`community_organization_fields()` 同步；个人分支短路
- [x] T035 [P] `assert_quota_available()` 两条路径按 `unlimited` 短路；`unlimited` 时 `remainingPoints = -1`
- [x] T036 [P] `configure_setup_quotas()` 放宽 `> 0` 强校验，不传则写 `unlimited = True`
- [x] T037 [P] `traffic_allocations.py` 的 `OrgQuotaPayload` / `DefaultPolicyPayload` 增 `unlimited`
- [x] T038 前端额度展示与编辑支持"不限额"（按 flag 渲染，不对 `-1` 做算术）

## Phase 7: User Story 5 (P2) —— 归档与恢复（阶段 9）

**Goal**: 归档后禁止登录且不计入授权数；恢复后数据完整。
**独立测试**: 归档账号登录被拒；恢复后配置与数据完整可用。

- [x] T039 实现 `DELETE /tenants/{id}`（归档）：`status=archived` + `archived_at` + `archive_reason`，同步置 `organizations` / `org_quota_policies` 为 `disabled`
- [x] T040 `auth.py` 登录校验查 `tenants.status`，非 `active` 一律 403（决策 13）
- [x] T041 实现 `POST /tenants/{id}/restore`：恢复 `active` 与相关配置
- [x] T042 租户枚举改为取 `tenants.status == "active"` 列表（`directory_bootstrap` / `employee_tenant_identity`）
- [x] T043 授权计数统一用 `count_documents({"status": "active"})` 封装（决策 18）
- [x] T044 全部生命周期操作写 `system_audit`

## Phase 8: User Story 6 (P2) —— 彻底清理（阶段 10）

**Goal**: 已归档租户可被完全清除（数据库 + 向量 + 文件），仅留墓碑 1 个月。
**独立测试**: 清理后三类存储残留为 0；未归档租户请求清理被拒。

- [x] T045 盘点并固化 `TENANT_SCOPED_COLLECTIONS`（现有 17 个不足，需扫描实际含 `tenant_id` 的集合）
- [x] T046 新建 `app/services/tenant_purge.py`：MongoDB 清理
- [x] T047 向量清理：按 `tenantId` 删除（对齐 `retrieval_client.py:45` 的过滤方式）
- [x] T048 文件清理：`knowledge_local_storage_dir` / `admin_static_dir` 下按标识前缀的目录
- [x] T049 异步任务 + 进度查询 `GET /tenants/{id}/purge-status`
- [x] T050 `POST /tenants/{id}/purge`：仅 `archived` 可执行（否则 409），`confirmName` 必须完全匹配
- [x] T051 成功置 `status=purged` 留墓碑；任一步失败中止并保持 `archived` 且记录原因
- [x] T052 墓碑记录保留 1 个月：定时清理任务（可复用 `scheduled_tasks` 机制）
- [x] T053 `setup_cleanup.py::cleanup_failed_setup()` 收紧标识校验并改为按实际写入集合回滚（与 purge 分离）

## Phase 9: User Story 7 (P2) —— 存量部署平滑升级

**Goal**: 既有部署升级后平台超管可用、既有企业被登记、数据零丢失。
**独立测试**: 在已有企业的环境升级，启动后租户列表出现既有企业且数据完整。

- [x] T054 `config.py` 新增 `platform_admin_username` / `platform_admin_password` / `platform_admin_display_name`
- [x] T055 新建 `app/services/platform_bootstrap.py`：`bootstrap_platform_admin()` 幂等 ensure
- [x] T056 `main.py` 启动钩子（第 49 行附近）追加调用；未配置时输出明确告警
- [x] T057 存量回填接入启动流程并验证幂等（重复启动不产生重复记录）
- [x] T058 发布说明：将 `ASKAI_ADMIN_PLATFORM_ADMIN_PASSWORD` 列为升级必读项

## Phase 10: 收尾

- [x] T059 前端 `views/platform/SystemHealthPage.vue`（服务健康只读）
- [x] T060 界面文案中英双语核对（constitution IV）
- [x] T061 `docs/WORK_LOG.md` 更新
- [x] T062 全量回归：单租户既有行为不破坏 + 多租户新行为全部通过
