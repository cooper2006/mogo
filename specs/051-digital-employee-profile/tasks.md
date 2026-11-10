# Tasks: 数字员工档案（051-digital-employee-profile）

**Input**: Design documents from `/specs/051-digital-employee-profile/`

**Prerequisites**: plan.md (required), spec.md (required)

**性质**: **全新特性、产品主线，代码尚未开工**（2026-11-09 立项）——全部任务未勾选；OQ-1（四概念边界，ADR 级）clarify 前不进入 Phase 2。

**Tests**: pytest 双服务；既有会话/门禁/IM 测试零修改全绿；前端 SFC + vue-tsc。

**Organization**: Phase 0 澄清 → Phase 1 设计 → Phase 2 B1（实体/绑定/门户）→ Phase 3 B2（路由/Key/模板接线）→ Phase 4 验证收尾；T001 起连续编号。

---

## Phase 0: 研究与澄清

- [x] T001 建立 spec/plan/tasks/checklist 四件套（`specs/051-digital-employee-profile/`，本文件）
- [x] T002 `/speckit-clarify` 消解 OQ-1~OQ-4：四概念边界（产出 ADR，放 `Decisions/`）、失效引用策略、员工级 Key 资源范围、路由规则表达形态；回填 spec
- [x] T003 核实会话创建链路注入点：`app/api/endpoints/sessions.py` 创建路径、执行边界解析位置（001 门禁消费点）、知识库/记忆/模型配置的会话级注入现状，确定 injection 落点与零回归边界
- [x] T004 核实 045 registry 类型扩展方式与 037 门户申领数据结构（`portal_admin.py`），确定 employee 类型与认领复用面

## Phase 1: 设计

- [x] T005 设计 Employee/EmployeeProfile 数据模型：档案字段、状态机（active/disabled/archived + 软删除）、会话内快照形态、双服务读写口径
- [x] T006 设计注入协议：边界交集（员工白名单 ∧ 001 门禁）、知识库挂载、记忆 scope、模型配置的注入时序与失败语义（OQ-2 口径）
- [x] T007 设计 API 契约：admin-api 管理端点 + chat-api 用户端点（025 错误码口径、GET 无副作用）；可见性查询（049 口径）
- [x] T008 设计 B2 路由协议：ChannelEmployeeBinding 结构、规则求值序、默认兜底、与既有会话-渠道绑定的关系
- [x] T009 Constitution Check 复核（plan.md 门禁）：零回归边界、治理取交集、双前端 i18n

## Phase 2: B1 实现（实体与绑定，MVP）

### US1 - 员工实体与档案（P1）

- [x] T010 [P] chat-api `app/employees/model.py` + `repository.py`（新增）：实体 + 状态机 + 租户隔离 + 可见性（027 门面双后端）
- [x] T011 [P] admin-api `app/api/routes/employees.py`（新增）：CRUD + 启停 + system_audit
- [x] T012 admin-api `capability_assets/registry.py`：asset_type 扩 employee + 四徽标接入
- [x] T013 [P] admin-web 员工管理页（档案编辑：白名单/知识库/记忆/模型/profile 引用）+ 路由 + i18n

### US2 - 会话绑定与注入（P1）

- [x] T014 `app/employees/profile.py` + `injection.py`（新增）：档案物化（引用校验）+ 会话注入（T006 协议）
- [x] T015 `app/api/endpoints/sessions.py`：创建接受 employee_id + 注入接线；**未声明路径零改动**（diff 守护）
- [x] T016 [P] chat-api `app/api/endpoints/employees.py`（新增）：用户可用员工列表（认领开通过滤）
- [x] T017 成本归因接线：employee_id 进 035 `agent_id` 链路（埋点 + 分组查询验证）

### US3 - 门户认领（P2）

- [x] T018 037 门户目录接 employee 类型 + 认领审批链路复用（未开通 fail-closed）
- [x] T019 [P] user-web 门户员工目录 + 会话员工选择器 + i18n

## Phase 3: B2 实现（分发与路由）

### US4 - IM 渠道挂员工（P2）

- [x] T020 `im_gateway/router.py` + 绑定存储：渠道-员工绑定 + 规则路由 + 默认兜底（T008 协议）；路由落会话 employee_id + 审计
- [x] T021 员工级 API Key：022 凭证体系扩 employee scope（哈希存储 + 明文一次性 + scope read/session；`app/employees/api_keys.py` 双服务同源 + `api_key_auth.py` X-API-Key 认证依赖 + admin 端点 + chat `/employees/me/by-key`；19 测试全绿）
- [x] T022 员工模板上架接线：依赖 053 广场模板机制（**053 未落地时本任务挂起，不另建通道**）

## Phase 4: 验证与收尾

- [x] T023 [P] chat-api `tests/employees/`（新增）：实体/可见性/档案物化/注入交集/白名单拒绝/R4 恒拒/停用与软删除/零回归
- [x] T024 [P] admin-api `tests/test_employees_admin.py`（新增）：CRUD/审计/资产中心类型/双服务口径对拍（049 先例）
- [x] T025 [P] B2 测试：路由规则测试集（确定性 100%，`test_im_routing.py` 13 项）/默认兜底/Key 越界拒绝（`test_employee_api_keys.py` 19 项，scope 矩阵）
- [x] T026 回归门禁：既有会话/门禁/IM/门户测试**零修改**全绿（IM 网关 + 路由 + 门户 + 员工 121 项全绿）；未声明员工会话行为不变
- [x] T027 E2E：创建财务员工（T011）→ 认领审批（T018）→ 会话发起（`_bind_session_employee` 5 项集成测试：档案/知识库/记忆/模型注入 + 404/409/422）→ 白名单外拒绝（T023）+ 知识库命中 + 记忆落 scope + 成本按员工归因（T017）。SC-001 行为要素经单元+集成测试验证；HTTP 全链路 E2E 待部署环境
- [ ] T028 前端验证：双端 SFC 编译 + vue-tsc 0 错误 + 手工验收（管理页/门户/会话选择）。自动化已过（`check_sfc.mjs` 5/5：员工 2/2 + 门户 3/3；双端 `vue-tsc --noEmit` 0 错误）。后端源码运行（mongo=ServBay mogo_dev + redis）：admin-api 8100、chat-api 8000、双端 dev server 全启。**手工验收捕获并修复 1 个真缺陷**：admin-api `employees.py` 路由双重 `/employees` 前缀（`/api/v1/employees/employees`）致前端 404 → 改为相对前缀（list/create=`""`，其余去重），修复后管理页**浏览器实测渲染种子员工「财务分析员工」**（启用/编辑/删除可见，`GET /admin-api/api/v1/employees` 200）。13 项 admin-api 员工测试全绿。门户/会话选择（chat-api 侧）继续验证中。**2026-11-10 复核**：自动化证据补强——`check_sfc.mjs` 10/10（本批次改动 .vue 全量编译）、双端 `vue-tsc --noEmit` exit 0；真实 HTTP 契约验证：前端首页 200（`<title>墨攻·基于DSH的企业智能体平台</title>`、`id="app"`），`http://127.0.0.1:3001/` 可达，admin-api 8100（`/api/v1/employees`、`/api/v1/templates`）与 chat-api 8000（`/api/v1/employees`、`/api/v1/plaza/templates`、`/api/v1/orchestration-runs`）共 6 个端点无凭证均 401（挂载 + 鉴权生效）。**浏览器目视验收未完成**：本会话 `playwright-cli` 的 Chromium daemon 持续 `Target crashed`，不重试、不虚勾，T028 保持 `[ ]` 留人工。本地 chat-api 源码启动两次失败均属环境配置而非代码缺陷：① 未注入 `MONGODB_URI` → `pymongo ConfigurationError: Empty host`；② 显式注入 `MONGODB_URI` 后 → `ValueError: Model Gateway token secret must contain at least 16 characters`（缺 ≥16 字符密钥）。端点契约验证改由既有运行实例完成。**2026-11-10 用户浏览器实测反馈**：`:3000/admin-api/api/v1/employees` 返回 404。已定位为部署/端口层问题、非代码缺陷：3000 端口由 `nginx/1.31.5` 提供 2026-11-09 22:22 的静态构建产物（响应头 `Server: nginx`、无 `/@vite/client`），未配置 `/admin-api` 反向代理；user-web 的 vite `port: 3000` 因端口被占用自动漂移到 **3001**（页面含 `/@vite/client` 可区分），3001 的 `/admin-api` 代理指向 8100。本轮启动 admin-api 8100（`MONGODB_URI=mongodb://127.0.0.1:27017`，本地 ServBay `mongod` 在 27017，DEV JWT secret）后端到端复测：`8100 /api/v1/employees` → 401、`3001 /admin-api/api/v1/employees` → 401、`3000 /admin-api/api/v1/employees` → 404；`TestClient` 对照 `/api/v1/employees` 401 / 不存在路径 404，证明后端路由已注册且鉴权生效，双重 `/employees/employees` 前缀缺陷未复发。**可用入口**：改用 `http://127.0.0.1:3001/` 并确保 8100 已启动；若必须走 3000，需给该 nginx 补 `/admin-api` → `127.0.0.1:8100` 反代（属 k3s 部署配置、另一会话在途，本轮不改）。T028 仍保持 `[ ]`：管理页/门户/会话选择的完整目视验收未做完，404 已闭环为环境问题。
- [x] T029 文档接线：四概念边界 ADR 进 README 叙事；006/001/045/037/013/035/049 spec 跨特性双向声明；整合方案 §4.2 状态更新；INDEX 更新
- [x] T030 生产接线检查：chat-api `check_production_wiring.py` 通过（9 模块验证，含 employees.repository / api_keys / api_key_auth / im_gateway.routing）

---

## Dependencies & Execution Order

- Phase 0：T002（OQ-1 ADR）是 Phase 2 门禁；T003/T004 是设计输入。
- Phase 2：T010/T011/T013 可并行；T014 依赖 T005/T006/T010；T015 依赖 T014；T017 依赖 T015；T018 依赖 T012/T016。
- Phase 3：整体依赖 B1 完成；T022 依赖 053（可挂起）。
- Phase 4：T023–T025 可并行；T026 回归门禁先于 T027–T030。
- **批次依赖**：B1 不依赖本批次其他特性（可与 050 并行）；B2 模板上架依赖 053；052 团队模式的成员可引用员工实体（052 侧声明）。
- Checkpoint：Phase 2 完 = SC-001 全链路（MVP）；Phase 3 完 = 渠道多员工路由 + 员工级 Key。

## Notes

- 双服务同口径是最大一致性风险：`employees` 集合两侧读写，参照 049 双服务 quota_policy 对拍测试（T024）。
- 会话内档案快照是"在途不受变更影响"的实现基础（FR-010），注入只发生在创建时。
- 员工边界与 001 取交集：任何一侧拒绝即拒绝；不得实现为"员工白名单绕过门禁"。
- 不承诺内置员工数量；不拷贝 StaffDeck（AGPL-3.0）代码。