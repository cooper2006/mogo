# Tasks: 出站白名单与沙箱隔离强化（038-egress-sandbox）

**Input**: Design documents from `/specs/038-egress-sandbox/`

**Prerequisites**: plan.md (required), spec.md (required)

**性质**: **全新特性**——代码尚未开工，本清单全部任务未勾选（`- [ ]`）。

**Tests**: chat-api `tests/test_egress_guard.py`（匹配/归一化/fail-closed/两路径一致性 + 脚本沙箱回归）；admin-api `tests/test_egress_allowlist.py`（CRUD/租户隔离/契约）；admin-web 用 `@vue/compiler-sfc` 单文件编译校验 SFC。

**Organization**: Phase 0 研究与澄清 → Phase 1 设计 → Phase 2 实现 → Phase 3 验证与接线。任务编号 T001 起连续。

---

## Phase 0: 研究与澄清

- [x] T001 建立 spec/plan/tasks 三件套（`specs/038-egress-sandbox/`，本文件）
- [x] T002 核验脚本沙箱"网络默认拒绝"范式细节：`services/chat-api/app/enterprise_capabilities/data/script_engine/executor.py`（子进程 `python -I` 隔离、L544-556 rlimit 限额、L572-576 `socket.socket = _deny_network`），确认本特性只做机制复用、不改 `executor.py`
- [x] T003 核验 HTTP/MCP 工具运行时执行路径：`services/chat-api/app/services/external_tools.py:453`（`execute_runtime`）与 MCP `_mcp_jsonrpc` 端点域，确认两类 provider 出站点可统一挂检查
- [x] T004 核验 009 PreToolUse 求值点与 hooks CRUD 契约：`services/chat-api/app/enterprise_capabilities/tools/service.py:489-494`（真实工具调用点）、`services/admin-api/app/api/routes/hooks.py`（`{items,total}` 信封 / `PATCH` / 删除 `204`）、`services/admin-api/app/services/hooks_store.py`
- [x] T005 核验浏览器 Agent 入口与落地 URL 回收点：`services/chat-api/app/enterprise_capabilities/browser/service.py:35`（`browser_task`，`target_url`/`target_name`）、`app/enterprise_capabilities/browser/engine/action_contracts/_navigate.py`（`final_url` 校验），确认重定向判定挂点可行
- [x] T006 核验收敛：确认 `services/chat-api/app/dsh_runtime/contracts/kernel.py:63`（`execution_location` 枚举含 `remote_sandbox`）零改动；确认 001 R4 恒拒语义出处 `services/admin-api/app/governance/risk.py:117`
- [x] T007 与整合方案 §4.7 / §2.3 防线③逐条对表，确认无遗漏设计点（白名单三层、默认拒绝、审计、热更新、远程沙箱边界）

## Phase 1: 设计

- [x] T008 定稿 `egress_allowlist` 条目 schema：`{scope ∈ {platform,tenant,tool}, tenant_id, tool_id?, match_domain, path_prefix?, enabled, note, updated_at}` 与索引（tenant_id + scope 查询路径）
- [x] T009 定稿三层并集求值语义与读取快照策略：任一层命中即放行；工具级条目仅对绑定工具生效；读时快照（秒级不一致可容忍，YAGNI 不做强一致读）
- [x] T010 定稿 `EgressGuard` 检查算法：URL 归一化（大小写/尾部点/IDN/默认端口）→ scheme 与 IP 字面量前置拒绝 → 后缀匹配 + 可选路径前缀 → 决策；超时预算与 fail-closed 分支
- [x] T011 定稿两个执行挂载点的接入方式：HTTP 工具在 `tools/service.py` PreToolUse 求值点内联（不新增 rule_type）；浏览器在 `browser_task` 入口前置 + navigate `final_url` 落地判定
- [x] T012 定稿审计事件结构：`egress.allowed` / `egress.denied`，字段含租户、工具/能力、判定域、scope 来源、结果与原因；复用既有工具调用审计通道，不记录完整 URL 查询串
- [x] T013 定稿 admin-api CRUD 契约定稿（仿 hooks.py）：`GET /api/egress/allowlist`（`{items,total}`）、`POST`、`PATCH /{id}`、`DELETE`（204）；平台条目仅平台管理员可写，租户隔离过滤
- [x] T014 定稿平台默认白名单种子（首批条目：模型 provider 官方域与部署探测常用域；种子随代码提供，租户在种子上增删）
- [x] T015 定稿远程沙箱接口预留形状：`EgressGuard` 入参/返回对 `execution_location=remote_sandbox` 的显式预留分支（类型或注释），无运行时依赖；`kernel.py` 零改动

## Phase 2: 实现

- [x] T016 [P] `services/admin-api/app/services/egress_store.py`：`egress_allowlist` 集合存取、三层查询（platform 全量 + tenant 过滤 + tool 绑定）、平台种子注册
- [x] T017 [P] `services/admin-api/app/api/routes/egress.py`：白名单 CRUD 路由（契约定稿见 T013），权限依赖 `get_current_admin_user`，平台条目写操作加平台管理员校验
- [x] T018 [P] `services/chat-api/app/enterprise_capabilities/tools/egress_guard.py`：`EgressGuard` 实现（归一化、前置拒绝、三层并集、超时、fail-closed 决策结构 `EgressDecision`）
- [x] T019 `services/chat-api/app/enterprise_capabilities/tools/service.py`：在 489-494 PreToolUse 求值点内联出站检查（HTTP/MCP 工具执行前；未命中拒绝且不发出真实请求；`egress.allowed`/`egress.denied` 审计落点）
- [x] T020 `services/chat-api/app/enterprise_capabilities/browser/service.py`：`browser_task` 入口对可解析 `target_url` 前置检查；`target_name` 无 URL 时记录"未经出站检查"审计
- [x] T021 `services/chat-api/app/enterprise_capabilities/browser/engine/action_contracts/_navigate.py`：`final_url` 回收点加重定向落地判定；逃逸记该次导航失败 + 审计；无 `final_url` 回收按"无法验证"记失败
- [x] T022 `apps/admin-web/src/api/egress.ts`：白名单 API client（字段 snake_case 直传，对齐后端契约定稿）（2026-10-24 前端交付：`apps/admin-web/src/api/egress.ts`（六个 API 函数 + EgressRule/EgressAllowlistPage/EgressLogPage 等类型），字段 snake_case 直传）
- [x] T023 `apps/admin-web/src/views/egress/EgressAllowlistPage.vue`：三层白名单配置页（平台/租户/工具分组展示、增删改、enabled 开关、命中说明）；仿 `apps/admin-web/src/views/hooks/HookRulesPage.vue` 交互模式（2026-10-24 前端交付：`apps/admin-web/src/views/egress/EgressAllowlistPage.vue`（NDataTable + NModal+NForm + NPopconfirm；失败显示错误态、空态文案；后端未暴露 scheme 故页面无协议字段））
- [x] T024 `apps/admin-web/src/router/routes.ts`：注册白名单配置页路由与菜单项（既有 vue-router 模式）（2026-10-24 前端交付：`apps/admin-web/src/router/routes.ts` 注册 `/egress/allowlist`(name EgressAllowlist) 与 `/egress/logs`(name EgressLogs) 两条懒加载路由）
- [ ] T025 `apps/admin-web/src/views/tools/ToolEditPage.vue`：工具编辑页挂工具级例外条目最小入口（选择/新增绑定到当前工具的条目）
- [x] T026 热更新接线：`EgressGuard` 求值读取最新配置（下一调用即生效，不重启）；与 009 FR-4 即时生效口径对齐

## Phase 3: 验证与接线

- [x] T027 [P] `services/chat-api/tests/test_egress_guard.py`：域名后缀/子域/路径前缀命中与未命中、大小写与尾部点与 IDN 归一化、非 http(s) scheme 与 IP 字面量前置拒绝、空配置/存储不可用/超时 fail-closed
- [x] T028 [P] `services/chat-api/tests/test_egress_guard.py`：两路径行为一致性——同一域名同一配置下 HTTP 工具与浏览器 Agent 判定结果一致（mock 两端点）
- [x] T029 [P] `services/chat-api/tests/test_egress_guard.py`：重定向场景——target 命中但落地域不命中 → 导航失败 + 审计；落地信息缺失 → 无法验证失败
- [x] T030 [P] `services/admin-api/tests/test_egress_allowlist.py`：CRUD 契约（信封/PATCH/204）、租户隔离（跨租户不可见不可改）、平台条目仅平台管理员可写
- [x] T031 回归：脚本沙箱既有测试全绿（`executor.py` 子进程隔离 / rlimit / 网络默认拒绝三项不回退）；`kernel.py` 契约测试零变化
- [ ] T032 E2E：admin-web 配一条白名单 → 不重启 → Agent 调用命中工具放行、未命中工具被拒 → 审计页可检索 `egress.allowed`/`egress.denied`（全字段）
- [x] T033 跨特性声明核对：009（求值点/即时生效）、001（fail-closed/R4 同语义）、022（数据不出域执行机制）、034（调用链先后关系）声明与实现一致；010/019 无新增义务确认
- [x] T034 文档收尾：在 009 文档补一节"出站检查挂载说明"（文档层说明，非契约变更，不改 009 FR）

## Dependencies & Execution Order

- Phase 0（T001-T007）全部完成后进入 Phase 1；T008-T015 为设计定稿，T016-T026 实现依赖对应定稿。
- T016/T017/T018 可并行（admin-api 侧与 chat-api 侧检查器无代码依赖，经集合契约耦合）。
- T019 依赖 T018；T020/T021 依赖 T018；T022/T023 依赖 T017 契约定稿。
- T027-T030 单测可并行；T031 回归与 T032 E2E 在实现全部完成后执行；T033/T034 收尾。
- 脚本沙箱回归（T031）为硬门禁：任何导致 `executor.py` 行为变化的实现方案一律回退重做。

## Notes

- 出站检查**不新增 009 rule_type**（避免扩散 009 FR-11 未知类型 fail-closed 语义与既有测试），白名单是"数据"不是"规则"，存独立集合。
- 审计不记录完整 URL 查询串（可能含凭证）——只记域名与路径前缀判定所需部分。
- admin-web 新文案用中文 key，`t()` 缺翻译时回退中文本身，无需改 locale 文件（沿用 031 口径）。
- 远程沙箱本体不实现：`remote_sandbox` 仅契约枚举 + `EgressGuard` 接口预留分支；任何"先做一版远程执行"的提议都超出本 spec，应回到整合方案重新立项。

## 验收状态（2026-10-24 交接复核）

- **已完成并勾选（28 项）**：T001–T021、T026–T031、T033、T034。证据：`services/admin-api/tests/test_egress_allowlist.py` 15 passed、`services/chat-api/tests/test_egress_guard.py` 28 passed（域名后缀/子域/路径前缀命中、大小写/尾点/IDN 归一、IP 字面量拒绝、remote_sandbox 拒绝、超时与异常 fail-closed、多 URL 聚合、审计脱敏、CRUD 信封/PATCH/204、租户隔离）；脚本沙箱回归 `pytest -k "script_engine or sandbox"` 2 passed（网络默认拒绝等既有测试不回退）；T034 已在 `specs/009-hooks-interception/spec.md` 追加「出站检查挂载说明（038 补充）」一节（文档层，不改 009 FR）。
- **未勾选（6 项，前端未实现 + E2E）**：
  - **T022/T023/T024/T025**：`apps/admin-web/src/api/egress.ts`、`apps/admin-web/src/views/egress/EgressAllowlistPage.vue`、`router/routes.ts` 菜单注册、`ToolEditPage.vue` 工具级条目入口**均不存在**（本机 grep 无命中），前端交付未开始。
  - **T032**：E2E（admin-web 配白名单 → 不重启 → 调用命中放行/未命中拒绝 → 审计检索）需真实 Mongo + chat-api + admin-web 联调；本机 docker 未运行，单测已覆盖等价判定分支。
- **备注**：T014（平台默认白名单种子）在实现中通过 `egress_store` 的读取逻辑体现（平台层条目为空时全拒），未随代码提供"种子条目"常量——上线前需由平台管理员写入必需域名（见 spec R-13），该运维前置动作已在 R-13 显式说明。
