# Tasks: 项目成员与项目层配额收口

**Input**: Design documents from `/specs/049-project-members/`

**Prerequisites**: 046 代码已落地（2026-11-01）；047 代码已落地（2026-11-01）；2026-11-05 核查确认 `quota_projects` 0 行、`projects` 2 行。

**Tests**: 双服务 pytest；前端 `node scripts/check_sfc.mjs <file>`（不跑全量 `vite build`）。

**Organization**: 按 plan 的 5 Phase；T001 起连续编号。

**落地状态（2026-11-05 22:10 严格收口复核）**：T001–T021、T023、T024 已完成；**T022 全链路手工验证待执行**。用户已拍板「按 spec 严格收口」：D-1 三个 410 写路由已删除并同步改测试、D-3 `tenant_purge.py` 旧表清理项已移除、D-4 已补运行时双服务 `get_quota_summary` 项目层对拍用例；D-2 记录为**已批准豁免**（046 遗留存储约束，见文末）。21:28 复核 `mogo-chat-api-1` / `mogo-admin-api-1` 已恢复 `healthy`（`/ready` 200），早前 `PoolTimeout` 已消失；T022 剩余阻塞 = 用户将提供的 admin 会话 / 登录方式 + A/B/C 三个真实账号与写操作授权，网关 API 前缀/认证待确认。验收命令、事故修复与豁免见文末「落地证据」。

## Phase 0: 基线与决策记录

- [x] T001 基线：`git status --porcelain` 快照；`grep -rn "quota_projects" services/ apps/` 全量清单（产出到本文件末尾「quota_projects 命中清单」），区分读路径 / 写端点 / 前端函数 / 文档
  > 证据：命中清单见文末；`services/*/app` **读路径 0 命中**，`apps/` 前端写函数 0 调用点（仅 1 处退役注释）。
- [x] T002 [P] `Decisions/ADR-9-项目成员-可见性与配额口径.md`：记录决策（成员 = 可见性 ∪ 配额口径；创建者兜底不落库；`quota_projects` 退役；046 D1 纯个人语义扩展为协作语义），引用 046 FR-012 与 ADR-8 的关系
  > 证据：ADR-9 含 Context / Decision 4 条 / Consequences / Implementation notes / 豁免与严格收口 / Alternatives。
- [x] T003 [P] `specs/INDEX.md` 新增 049 行；`specs/042-three-level-quota/spec.md` 的「实现落点索引」节补一行：`quota_projects` 表于 049 退役（读路径 0 命中），成员语义迁到 `projects.member_user_ids`
  > 证据：`specs/INDEX.md` 049 行（22:10 已同步严格收口后的验收数据）；042 spec:262 退役标记。

## Phase 1: US3 读路径修复（最小可交付）

**Goal**: admin「项目管理」显示真实项目；配额度不再 404；`quota_projects` 读路径清零。

**Independent Test**: `GET /api/v1/traffic-allocations/projects-with-usage` 返回 `projects` 表的 2 行；`PUT /projects/{真实 id}/policy` 200。

- [x] T004 `services/admin-api/app/services/quota_projects.py`：`PROJECT_COLLECTION` 语义改为读 `projects`——`list_projects` 查 `projects`（`status` 映射：archived 也返回，由前端分组）；`get_project` 查 `projects`；`project_view` 字段映射（`name` ← `title`、`memberUserIds` ← `member_user_ids or []`、`memberCount`、`status` ∈ active|archived、`note` ← ""）；模块 docstring 标记"049：读 `projects`，`quota_projects` 退役"
  > 证据：`PROJECT_COLLECTION = "projects"`（:26）；字段映射（:52-70）；三个写函数改为 `RuntimeError` 退役（:95-129）。
- [x] T005 `services/admin-api/app/api/routes/traffic_allocations.py`：`_require_project` 改查 `projects`（archived 视为 404，语义对齐 046 US2）；`POST /projects`、`PUT /projects/{id}`、`DELETE /projects/{id}` 三个写 `quota_projects` 的端点下线（删路由，FR-007）；`PUT/DELETE /projects/{id}/policy` 保持（FR-008）
  > 证据：`_require_project` 走 `projects_service.get_project`；**22:10 严格收口已把三个 410 Gone 壳路由整体删除**（连带清理无引用的 `ProjectPayload`），文件 717 行、净 `+12 / −103`；注释写明项目只能由 user-web 经 chat-api 创建。`test_quota_projects.py` 已改为断言「三个写路由不再注册 + gone handler 不存在」，10 passed。policy 端点保留。
- [x] T006 `apps/admin-web/src/api/traffic-allocations.ts`：删 `createQuotaProject` / `updateQuotaProject` / `deleteQuotaProject` 及对应 `QuotaProject` 写 payload 类型（保留读类型，字段名兼容）；`apps/admin-web/src/views/organizations/TrafficAllocationsPage.vue` 删 5 个调用点与相关 UI（项目 tab 047 T020 已移除，只余 import 与残留 handler）
  > 证据：`TrafficAllocationsPage.vue` 净删 88 行 / 加 3 行（import / ref / computed / 4 handler / UI），`grep createQuotaProject apps/` 仅剩 1 处退役注释。
- [x] T007 `apps/admin-web/src/views/projects/ProjectsPage.vue`：确认 `status === "archived"` 进 `archivedRows`（047 T006 已写"归档折叠"，核对现状是否直接可用，否则最小改动）
  > 证据：**零改动**——047 T006 的 `activeRows` / `archivedRows` 拆分已直接消费 `status`。
- [x] T008 [P] `grep -rn "quota_projects" services/admin-api/app` = 0 命中（文档注释除外）；`pytest services/admin-api/tests/test_quota_three_level.py` 全绿
  > 证据：admin-api 5 个相关测试文件 **51 passed**；剩余命中分类见文末清单。

## Phase 2: US1 成员与可见性

**Goal**: 项目有成员；`GET /projects` 返回"我的 ∪ 我参与的"；user-web「…」菜单出「成员」弹窗。

- [x] T009 `services/chat-api/app/api/endpoints/projects.py`：`ProjectPatch` 加 `member_user_ids: Optional[List[str]]`（上限 500，去重、去空）；`PATCH` 路由：非创建者写成员 → 403；默认项目写成员 → 400（与现有默认项目约束同级）；落库 `projects.member_user_ids`
  > 证据：`:69`、`:201-210`（去空 / 去重保序 / 排除创建者 / 上限）；`:177-193` 权限判断。上限原实现 1000，本轮按 FR-001 修正为 `MAX_PROJECT_MEMBERS = 500`。
- [x] T010 `services/chat-api/app/api/endpoints/projects.py`：`GET /projects` 过滤改 `{"tenant_id": t, "user_id": me, ...} OR {"member_user_ids": me}`（PanWeiDB 表达按 plan OQ-3 实测：优先双查询并集；`_ensure_default_project` 不变——每人自己的默认项目不做 ∪）
  > 证据：`:153-163` 单查询 `$or`（`user_id` / `member_user_ids` / `_id: "default"`），未走 OQ-3 担心的 `$elemMatch`；`_ensure_default_project` 不变。**D-2 已批准豁免**：默认项目为租户共享兜底项，见文末与 spec FR-003 实现注。
- [x] T011 `services/chat-api/app/api/endpoints/projects.py`：新增 `GET /projects/member-candidates?department_id=`（plan OQ-1）：`org_units.path_ids` 前缀匹配部门及下级 + `end_user_org_relations` 关联 + `end_users`（仅 active、展示字段白名单 `{id, name, mobile, email, loginName, departmentName}`）；无参数时全租户 active 用户；部门树复用 `org_units` 全量（`{tenant_id, status: active}`，前端组树，`parent_id` + `depth`）
  > 证据：`:220-238` 部门树端点；`:241+` 候选端点（子树过滤 + 展示字段白名单）。
- [x] T012 `apps/user-web/src/api/sessions.ts`：`updateDesktopProjectMembers(projectId, memberUserIds)`（PATCH `member_user_ids`）+ `listProjectMemberCandidates(departmentId?)`；`DesktopProject` 类型加 `member_user_ids?: string[]`
  > 证据：新增 `_id` / `tenant_id` / `user_id` / `member_user_ids` 字段与 3 个 API 函数（成员 PATCH / 候选 / 部门树）。
- [x] T013 [P] 新增 `apps/user-web/src/components/project/MemberPicker.vue`（plan OQ-2）：部门树（`org_units` 全量组树）+ 用户多选（按选中部门过滤，可清空过滤）+ 已选成员 chip（可移除）+ 保存（调 T012）；非创建者打开时只读（无保存按钮）；默认项目不可打开（菜单项 T014 不渲染）
  > 证据：201 行，部门树 + 用户多选 + 已选 chip + 保存；非创建者只读。
- [x] T014 `apps/user-web/src/App.vue:2790-2804`「…」菜单：加「成员」项（内联三元 `locale === 'en' ? 'Members' : '成员'`，图标用既有 16px stroke 风格），`@click` 打开 `MemberPicker`；`v-if="group.id !== DEFAULT_PROJECT_ID"` 不变（默认项目天然无菜单）；新增 `memberPickerFor` ref 与关闭逻辑（对齐 `toggleProjectMenu` 的既有交互）
  > 证据：4092 行，相对 HEAD **+38 行 / −0 行**：import（:14）、`type DesktopProject`（:30）、state + handler（:682 / :692）、菜单项（:2833-2836）、`<MemberPicker>`（:2611-2620）；`v-if` 约束未动。**本轮修复**了上一轮的截断事故，见文末「事故与修复」。
- [x] T015 [P] `pytest services/chat-api/tests/test_projects_rename.py`（回归）+ 新增 `services/chat-api/tests/test_project_members.py`：成员写权限矩阵（创建者 200 / 非创建者 403 / 默认项目 400）、`GET` 可见性（我的 / 我参与的 / 别人的 不可见）、候选端点（部门过滤子树命中、active only）
  > 证据：`test_project_members.py` 252 行；chat-api 4 个相关文件 27 passed。
- [x] T016 [P] `node scripts/check_sfc.mjs apps/user-web/src/App.vue apps/user-web/src/components/project/MemberPicker.vue` + `vue-tsc --noEmit`
  > 证据：user-web SFC 2/2、`vue-tsc` rc=0 且 0 行输出；admin-web SFC 2/2、`vue-tsc` rc=0 且 0 行输出。同时核对文件行数（App.vue 4092 行），排除截断态假阳性。

## Phase 3: US2 配额口径

**Goal**: 项目层配额 = 成员（∪创建者）用量合计；双服务同口径。

- [x] T017 `services/chat-api/app/core/quota_policy.py`：项目层成员来源 `_scope_members`（`:220-229` 现为 chat_sessions distinct）改为查 `projects` 取 `member_user_ids ∪ user_id`（plan OQ-4 创建者兜底）；`:243` 的用量过滤 `{tenant_id, project_id}` 保持
  > 证据：`:244-260`（缺字段回退 046 语义）、`:274-288`（archived 不参与取小）。
- [x] T018 `services/admin-api/app/core/quota_policy.py`：镜像 T017（`:220-229` 同改）；`_layer_state`（`:265`）的 `quota_projects` deleted 判断改为 `projects.status == "archived"` → 返回 None（不参与取小，046 US2 场景 2）
  > 证据：`:241-257`、`:271-286`，与 chat-api 逐行同构。
- [x] T019 [P] `services/chat-api/tests/test_quota_consistency.py`（047 T022 既有矩阵）加成员口径用例：同 fixture 下双服务 `get_quota_summary` 的 `project` 层 `total/used` 逐字段一致；无成员项目 = 仅创建者口径
  > 证据：实际落在 `services/admin-api/tests/test_quota_consistency.py`（chat-api 侧无同名文件）。**22:10 严格收口补齐运行时对拍**：新增 `TestProjectLayerRuntimeConsistency` 4 例，以唯一模块名 `spec_from_file_location` 动态加载两侧 `quota_policy.py`（绕开同名 `app.core.quota_policy`），stub 掉 `log_print` / `product_edition_fields` / `get_db`，用同一份 fake DB fixture 分别跑 `get_quota_summary`，逐字段比对 `projectTotalPoints` / `projectUsedPoints` / `projectRemainingPoints` / `projectScopeId` / `projectName` / `projectResetAt`，并捕获 `sum_usage(user_ids=...)` 锁死成员口径。覆盖「成员∪创建者=600 且排除非成员 4000」「无成员项目=仅创建者 100」「创建者重复去重」「archived 项目层缺席」；原有 3 例静态源码比对保留。另用 `/tmp/qa/verify_049_d4.py` 做身份核对（两侧 `__file__` 不同、`utc_now` tz-aware/naive 不同）与变异验证（删掉 chat 侧创建者合并后用例立即 1 failed），排除假阳性。
- [x] T020 [P] `pytest services/chat-api/tests/test_quota_three_level.py services/admin-api/tests/test_quota_three_level.py services/chat-api/tests/test_quota_unlimited.py` 全绿（SC-003/004）
  > 证据：chat-api 4 文件 **27 passed**；admin-api 5 文件 **51 passed**（`test_quota_consistency.py` 14 例，其中新增 4 例运行时对拍；`test_quota_unlimited.py` 仅 admin-api 有，T020 原命令里 chat-api 侧该文件不存在）。

## Phase 4: 验证收尾

- [x] T021 收口：`grep -rn "quota_projects" services/` = 0 命中（退役注释除外，按 SC-005）；`grep -rn "QUOTA_PROJECT_COLLECTION" services/admin-api/app` 0 命中
  > 证据：`QUOTA_PROJECT_COLLECTION` 在 `services/*/app` **0 命中**；`quota_projects` 在 `services/*/app` **读路径 / 写路径 / 集合常量 0 命中**（SC-005 达成）。**D-3 已收口**：`tenant_purge.py` 的清理集合项已移除，只剩注释；剩余 24 处全为退役注释 / 模块名 / 函数名 / 测试断言文本（清单见文末）。字面「`services/` 全量 0 命中」仍不达成，但已无任何运行时引用旧表。
- [ ] T022 [P] 全链路手工验证（quickstart 清单）：admin 页 2 行 → 配额度 200 → 成员 A 用量命中限额 → B 被拒文案"项目层" → 归档后不约束
  > **未完成，待用户提供凭据**：用户已选择「我提供凭据」。21:28 复核服务已恢复 `healthy`（`/ready` 200，`mogo-gateway-1` 3000 → 200），早前 `PoolTimeout` 重启循环已终止。剩余阻塞 = admin 会话 / 登录方式 + 创建者 A / 成员 B / 非成员 C 三个真实账号 + 配额度/加成员的写操作授权；网关 `/api/v1/...` 直连返回 404（前缀或认证待确认），栈内 DB 凭据与服务外部库不一致，无法用 psql 旁路核对数据面。清单已写入 `quickstart.md`，凭据就绪后按序执行即可。
- [x] T023 [P] `specs/049-project-members/checklists/requirements.md` 勾选（需求质量 15 项）
  > 证据：实际 19 项（CHK001–CHK019）全部 `[x]`；文件已声明 `[x]` 表示需求质量达标、不表示实现完成。
- [x] T024 [P] `docs/pending-review/` 或 042 spec 索引补 `quota_projects` 退役说明（与 T003 呼应）
  > 证据：042 spec「实现落点索引」新增收口段（:262）；ADR-9 Decision 2；`quota_projects.py` 模块 docstring；`specs/INDEX.md` 049 行。

---

## 落地证据

**严格收口后验收命令（2026-11-05 22:10）**

| 范围 | 命令 | 结果 |
|---|---|---|
| user-web SFC | `cd apps/user-web && NODE_PATH=$(pwd)/node_modules node ../../scripts/check_sfc.mjs src/App.vue src/components/project/MemberPicker.vue` | 2/2 ok |
| admin-web SFC | `cd apps/admin-web && NODE_PATH=$(pwd)/node_modules node ../../scripts/check_sfc.mjs src/views/organizations/TrafficAllocationsPage.vue src/views/projects/ProjectsPage.vue` | 2/2 ok |
| 双端类型 | `cd apps/<app> && ./node_modules/.bin/vue-tsc --noEmit -p tsconfig.json` | user-web / admin-web 均 rc=0、0 行输出 |
| chat-api 测试 | `cd services/chat-api && PYTHONPATH=$PWD/sandbox_script .venv-qa/bin/python -m pytest <4 文件> -q -o addopts=` | **27 passed** |
| admin-api 测试 | `cd services/admin-api && .venv/bin/python -m pytest <5 文件> -q -o addopts=` | **51 passed** |
| 一致性单文件 | `cd services/admin-api && .venv/bin/python -m pytest tests/test_quota_consistency.py -q -o addopts=` | **14 passed**（10 静态 + 4 运行时） |
| D-4 有效性自检 | `cd services/admin-api && .venv/bin/python /tmp/qa/verify_049_d4.py` | 身份核对 OK；变异后 `1 failed, 3 passed`（预期失败） |
| 读路径收口 | `grep -rn "QUOTA_PROJECT_COLLECTION" services/*/app` | 0 命中 |

**事故与修复（App.vue 截断）**

上一轮会话的 python 脚本在 `for line in lines:` 里命中锚点后 `break`，随后直接 `open(p,'w').write('\n'.join(out))`——`out` 只累积到命中行，`apps/user-web/src/App.vue` 从 4054 行被静默截成 31 行（停在 import 列表中间）。残缺文件让 `vue-tsc` 反而"零报错通过"，形成假阳性。本轮从 `git show HEAD:apps/user-web/src/App.vue` 取回全文（HEAD = `65b28809`，与 `origin/main` 同版），对 5 个锚点逐一断言唯一后精确重放 049 改动，先写临时文件回读校验、再替换；最终 4092 行（+38 / −0），SFC 与 `vue-tsc` 真实通过。

**偏差处理（2026-11-05 22:10，用户拍板「按 spec 严格收口」）**

- **D-1 已收口**：原实现把 `POST/PUT/DELETE /traffic-allocations/projects` 保留为 410 Gone（FR-007 允许的备选）。现已**删除三个路由及其 handler**，同步把 `test_quota_projects.py` 的 410 断言改为「路由不再注册 + gone handler 不存在」，并清理无引用的 `ProjectPayload`。`test_quota_projects.py` 10 passed。
- **D-3 已收口**：`tenant_purge.py` 租户清理集合清单里的 `"quota_projects"` 项已移除（旧表 0 行、表壳保留不删，spec Edge Cases 第 5 条），只剩说明性注释；`services/*/app` 已无该集合的读 / 写 / 常量引用。
- **D-4 已收口**：T019 从「仅静态源码比对」升级为**同 fixture 运行时对拍**，见 T019 证据；并用变异测试证明用例能捕获口径偏差。
- **D-2 已批准豁免（唯一保留的偏差）**：FR-003 写「每人自己的默认项目，不做 ∪」。存储层 `pg_compat` 的 `id` 是全局主键，同租户第二个用户 upsert `"default"` 会 `ON CONFLICT DO NOTHING` 拿不到自己的行；实现把 `{_id: "default"}` 纳入 `$or`，使租户内所有用户可见该兜底行。属 046 遗留的存储约束，改 DDL 超出 049 范围且会影响 046 数据面，**经用户确认作为文档豁免保留**：已在 `spec.md` FR-003 实现注、ADR-9「豁免与严格收口」与本节登记。上线后若要把默认项目改回每人一条，需单独立项处理主键。
- **FR-001 上限**：实现原为 1000，本轮按 spec 修正为 500（`MAX_PROJECT_MEMBERS`）。

## quota_projects 命中清单（T001 基线 / T021 收口）

`services/*.py` 共 **24 处**，**无一处是运行时读取 / 写入 `quota_projects` 集合**：

| 类别 | 位置 |
|---|---|
| 退役注释 / docstring | `admin-api/app/services/quota_projects.py:1,3,5,10,25`；`admin-api/app/core/quota_policy.py:21,221`；`chat-api/app/core/quota_policy.py:224`；`admin-api/app/services/tenant_purge.py:203`（D-3 清理项已删，仅注释）；`admin-api/tests/test_project_archive.py:113`；`admin-api/tests/test_quota_three_level.py:198` |
| 退役 `RuntimeError` 文案（写函数已不可调用） | `admin-api/app/services/quota_projects.py:103,108,121,123,127,129` |
| 模块名 / 函数名（非旧表引用） | `admin-api/app/api/routes/traffic_allocations.py:32,607`；`admin-api/tests/test_quota_projects.py:17` |
| 一致性测试断言文本 | `admin-api/tests/test_quota_consistency.py:134,135,137,138` |

`grep -rn "quota_projects" apps/` **0 命中**；`admin-web/src/api/traffic-allocations.ts:180` 有 1 处退役注释（含已删的 3 个写函数名，0 调用点）。
