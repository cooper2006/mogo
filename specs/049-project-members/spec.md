# Feature Specification: 项目成员与项目层配额收口

**Feature Branch**: `049-project-members`

**Created**: 2026-11-05

**Status**: Draft

**Input**: 用户口径（2026-11-05 会话）：
1. admin 端「项目管理」页无数据——经核查是后端读路径停留在 042 的 `quota_projects`（0 行），未切到 046 统一后的 `projects` 表（ADR-8 + 046 FR-012 的残留）。
2. 「项目」当前纯个人维度，要加「成员」：落点为 user-web 侧边栏非默认项目「…」下拉（`apps/user-web/src/App.vue` 的 `toggleProjectMenu`，现有「重命名/删除项目」项），默认项目不渲染菜单；选择成员参考用户管理，从 `end_users` 选、可按部门过滤、可多选。
3. 语义拍板（用户确认）：
   - 配额口径恢复「项目成员」语义——项目层配额 = 该项目**成员**（含创建者）的会话用量合计（回到 042 口径，但成员来源改为 `projects.member_user_ids` 新字段 + 创建者）。
   - 可见性：`GET /projects` 从「我的」改为「我的 ∪ 我作为成员的」（046 D1 的纯个人语义就此扩展为协作语义）。

## 背景（为什么做）

046（ADR-8）把三套"项目"收敛成 `projects` 一张表（项目 = 工作目录，纯个人、无成员），并废弃 042 `quota_projects` 的成员内嵌数组。执行时留下两处残留：

| 残留 | 位置 | 后果 |
|---|---|---|
| admin 项目管理读错表 | `services/admin-api/app/services/quota_projects.py:21` 仍 `PROJECT_COLLECTION = "quota_projects"` | admin「项目管理」恒空列表（quota_projects 0 行；真实数据在 `projects` 2 行） |
| 项目层配额 deleted 判断查旧表 | `services/admin-api/app/core/quota_policy.py:265` `QUOTA_PROJECT_COLLECTION` | 空表 = 恒查不到 → 恒放行，暂无害但语义错 |
| 成员概念缺失 | `projects` 无成员字段；`chat_sessions.project_id` 的配额按"项目内全部会话用户"计 | 无法表达"只有这 3 个人是这个项目的成员"；可见性只能"仅本人" |

本特性一次收口：**读路径切到 `projects` + 项目加成员（可见性 ∪ 配额成员口径）**。不改 042 引擎结构（四层取小不变），只换项目层的成员来源与项目实体来源。

> **与 046 的关系**：046 D1「纯个人」是 046 的决策；本特性是用户主动把产品语义推进到「个人 + 可协作」（成员 = 可见性 + 配额口径），并记录在此。046 FR-012「`quota_projects` 成员内嵌数组下线」**继续成立**——新成员语义落在 `projects.member_user_ids`，与旧 `quota_projects` 表无关（旧表彻底退役）。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 给项目加成员，别人能在侧边栏看到 (Priority: P1)

员工 A 建了项目 P（选目录），在侧边栏「… → 成员」里按部门挑选了 B、C；B、C 登录自己的 user-web，侧边栏直接出现 P（带会话分组）。A 随时可移除成员，被移除者侧边栏 P 消失（历史会话与成本保留）。

**Why this priority**: 这是本特性新增能力的核心闭环；没有它"协作"无从谈起。

**Independent Test**: A 建 P → A 加 B 为成员 → B 的 `GET /projects` 返回含 P → B 侧边栏出现 P 分组；A 移除 B → B 再查列表无 P。

**Acceptance Scenarios**:

1. **Given** 项目 P 的成员含 B，**When** B 调 `GET /api/v1/projects`，**Then** 返回 P（`GET` 的过滤条件为 `user_id = me OR member_user_ids ⊇ me OR _id = "default"` 语义上的"我的 ∪ 我参与的"）。
2. **Given** B 不是 P 成员且 P 非默认项目，**When** B 调 `GET /projects`，**Then** 不含 P（不可见、不可直接写）。
3. **Given** A 在 P 的「…」菜单点「成员」，**When** 打开弹窗，**Then** 左侧部门树（来自本租户 `org_units`）、右侧用户多选列表（来自 `end_users`，按所选部门及其下级过滤）；勾选保存后 `PATCH /projects/{id}` 带 `member_user_ids` 全量集合。
4. **Given** 项目 P 的成员含 B，**When** B 直接 `PATCH /projects/{P}` 改成员，**Then** 403（成员管理权归创建者；被移除只能等创建者操作——见 Edge Case 2）。
5. **Given** 默认项目（`_id = "default"`），**When** 侧边栏渲染，**Then** 不出「…」菜单（现有 `v-if="group.id !== DEFAULT_PROJECT_ID"` 保持），自然也不出「成员」项。

---

### User Story 2 - 项目层配额按"成员用量"计 (Priority: P1)

管理员给项目 P 配了 10 万 token/月。P 的成员（含创建者）本月合计用了 10 万 → 再调用被拒且错误信息指明项目层；非成员（哪怕其会话因历史原因挂在 P 下）的用量不计入。

**Why this priority**: 配额口径是本特性与 042/046 引擎的接线点；口径错了等于 042 的项目层白做。

**Independent Test**: P 配额度 = 成员 A 一次用量 → A 调用成功、B（成员）再调用被拒（项目层）、C（非成员）调用成功（不受项目层约束——C 本就不在该项目的成员口径内，其会话若挂 P 属迁移遗留）。

**Acceptance Scenarios**:

1. **Given** P 配了项目层额度且 `status = active`，**When** 任一 P 成员发起 LLM 调用，**Then** 项目层剩余 = 额度 −（P 的 `member_user_ids` ∪ 创建者）在本周期 `token_usage_logs` 用量合计，参与四层取小。
2. **Given** P 未配项目层策略，**When** 成员调用，**Then** 项目层不参与取小（042 SC-003 零策略等价，行为不变）。
3. **Given** P `status = archived`，**When** 成员调用，**Then** 项目层不参与取小（046 US2 场景 2，保留）。
4. **Given** P 无成员（纯个人项目），**When** 创建者调用，**Then** 项目层用量口径 = 创建者本人（`member_user_ids` 为空时按"创建者兜底"，与 046 现状一致）。

---

### User Story 3 - admin「项目管理」显示真实项目 (Priority: P1)

管理员打开 admin-web「项目管理」，看到的是租户内**全部** `projects` 行（含成员数、创建者、周期用量/成本、项目层额度配置入口）；配额度不再 404；归档项目折叠到「已归档」。

**Why this priority**: 这是本次报障的直接修复——页面现在恒空，运营/管理全链路断。

**Independent Test**: `GET /api/v1/traffic-allocations/projects-with-usage` 返回 `projects` 表的行（2 条：默认 + test），且 `PUT /projects/{id}/policy` 对真实项目 id 不再 404。

**Acceptance Scenarios**:

1. **Given** 租户有 2 条 `projects` 行，**When** 管理员打开「项目管理」，**Then** 列表 2 行（默认项目 + test），字段：名称（`title`）、创建者（`user_id` → 用户名）、成员数（`member_user_ids` 长度）、状态、周期用量/成本、额度配置。
2. **Given** 某项目 `status = archived`，**When** 查看列表，**Then** 折叠进「已归档」分组（复用 `ProjectsPage.vue` 既有 `activeRows` / `archivedRows` 拆分）。
3. **Given** 管理员给真实项目 id 配额度（`PUT /projects/{id}/policy`），**When** 请求，**Then** 200 且 `user_quota_policies` 落一条 `scope_type=project, scope_id=<项目 id>` 行（不再 404）。
4. **Given** 某项目已配额度，**When** 查看该行，**Then** 显示额度/周期/本期已用/剩余；未配置显示「未设置额度」（047 US1 验收 3，保持）。

---

## Edge Cases

- **创建者被自己移除**：允许（创建者也是成员，`member_user_ids` 可不含创建者；但可见性永远含创建者——列表过滤条件为 `user_id = me OR member_user_ids ⊇ me`）。
- **成员账号被禁用/删除**：成员列表保留 id；配额口径在用量查询时天然只统计活着的用量行，无需清理；弹窗过滤展示时跳过非 active 用户。
- **默认项目不设成员**：`_id = "default"` 拒绝 `member_user_ids` 变更（与"不可归档/删除/重命名"同级，400）；默认项目配额口径仍为"本 (tenant, user) 全部"。
- **项目被创建者删除（046 侧现有 DELETE 语义）后**：成员字段随项目行消失；历史用量/策略行保留（046/042 语义不变）。
- **`quota_projects` 旧表**：本特性后**彻底无读方**（写方 047 T020 后前端已停用）；不删表、不迁移（0 行，2026-11-05 核查），只在文档标记退役（`docs/` 或 042 spec 的落地索引补一行）。
- **跨服务口径**：`chat-api` 与 `admin-api` 两份 `quota_policy.py` 的项目层成员来源**必须同口径**（都读 `projects.member_user_ids` ∪ 创建者），047 T022 的 `test_quota_consistency.py` 矩阵加一行成员用例，防漂移。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `projects` 集合 MUST 新增可选字段 `member_user_ids: [str]`（用户 `_id` 列表，去重、上限 500）；创建者不落此字段（可见性/配额由 `user_id` 兜底）。
- **FR-002**: `PATCH /api/v1/projects/{id}`（chat-api）MUST 接受 `member_user_ids` 全量集合；**仅创建者（`user_id = me`）可写**，非创建者写 → 403；默认项目写成员 → 400。
- **FR-003**: `GET /api/v1/projects` MUST 返回「我的 ∪ 我作为成员的」项目（过滤：`user_id = me OR me ∈ member_user_ids`；默认项目保持"每用户一条可见"语义不变——每人自己的默认项目，不做 ∪）。**默认项目部分的偏差为已批准豁免，见文末「实现豁免」。**
- **FR-004**: 部门过滤用户选择端点 MUST 提供（chat-api 新增 `GET /api/v1/projects/member-candidates?department_id=...`）：读 `end_users` + `org_units`（`path_ids` 前缀匹配部门及下级）+ `end_user_org_relations`，返回 `{id, name, mobile, email, loginName, departmentName}` 列表；无 `department_id` 时全租户 active 用户。
- **FR-005**: user-web 侧边栏非默认项目「…」菜单 MUST 增加「成员」项（内联三元文案，与既有一致）；弹窗 = 部门树 + 用户多选 + 保存（调 FR-002 的 PATCH）；创建者可管理，非创建者成员**只读**（弹窗可打开看，无保存按钮，或干脆隐藏入口——二选一，实现取"可看不可改"）。
- **FR-006**: 项目层配额成员口径 MUST 改为 `projects.member_user_ids ∪ 创建者`（`chat-api` 与 `admin-api` 两份 `quota_policy.py` 同改；`admin-api` 的 `_layer_state` 同时把 `quota_projects` deleted 判断改为 `projects.status == "archived"`）；`user_quota_policies` 的 `scope_id` 继续 = `project_id`（046 FR-012 不变）。
- **FR-007**: admin-api 读路径 MUST 切到 `projects`：`quota_projects.py` 的 `list_projects` / `get_project` 读 `projects` 表；`project_view` 输出字段兼容前端 `QuotaProject` 契约（`name` ← `title`、`memberUserIds` ← 新字段、`memberCount`、`status` ∈ active|archived，前端"已归档"分组直接消费）；`traffic_allocations.py` 的 `POST /projects`（新建）与 `PUT`/`DELETE`（改名/软删配额分组）**退役**——项目只能由 user-web 创建（047 US1 验收 2 的"只读"），端点保留 410 Gone 或直接下线路由（实现取**下线**，前端 `createQuotaProject` 等 5 个函数同批删调用点）。
- **FR-008**: `PUT /projects/{id}/policy` / `DELETE /projects/{id}/policy` MUST 对真实项目 id 生效（`_require_project` 改查 `projects`）；404 语义：项目不存在或已 archived。
- **FR-009**: 用量/成本段（admin「项目管理」的 `projects-with-usage`）MUST 按项目聚合 `token_usage_logs`（`project_id = 项目 id`，现有实现），口径不变；新增"成员数"列。
- **FR-010**: 迁移期读兼容（046 FR-011 延续）：`member_user_ids` 缺失时按"仅创建者"处理（现状），**MUST NOT** 把缺失解释为"所有人"。

### Non-Goals

- 不做"成员邀请/通知"（加入后对方刷新才可见，无 push）。
- 不做"成员角色"（owner/editor）——只有"创建者"一个特权位。
- 不改 042 引擎四层取小结构、不改 `scope_type` 枚举、不改 `user_quota_policies` 集合名。
- 不做项目级"共享聊天"（成员可见项目 ≠ 成员共享会话内容；会话归属仍按 046 创建者侧边栏）。
- 不迁移 `quota_projects` 历史数据（0 行，2026-11-05 核查）。

## Success Criteria

- SC-001: 2 条 `projects` 行在 admin「项目管理」可见；`projects-with-usage` 返回 2 行且成员数列非空（含创建者兜底后的语义）。
- SC-002: 成员 B 的 `GET /projects` 含 A 建的 P；非成员 C 的 `GET /projects` 不含 P。
- SC-003: 项目层配额：成员用量合计命中限额被拒（错误文案含"项目层"），非成员不受约束；无策略时零行为变化。
- SC-004: `test_quota_consistency.py`（047 T022）加"成员口径"用例后双服务全绿。
- SC-005: `quota_projects` 在 `services/` 读路径 0 命中（grep `services/*/app` 只允许出现退役注释/文档引用）。

## Clarify 记录（2026-11-05 与用户对齐）

- 配额口径：项目层 = **成员（含创建者）用量合计**（用户原话「配额应该是项目下所有成员的会话用量合计」）。
- 可见性：B「可以看到作为成员的项目」。
- 成员选择：`end_users` + 部门过滤（参考 admin 用户管理 `directory.py::list_users` 的 `path_ids` 子树 + `end_user_org_relations` 关联实现）。
- 菜单落点：`App.vue` 非默认项目「…」下拉（现有「重命名/删除项目」旁），**不是**右键；默认项目不出菜单（现有 `v-if` 已覆盖）。

## 实现豁免（2026-11-05 用户拍板「按 spec 严格收口」后确认）

收口时逐条核对了 4 处实现与 spec/plan 的偏差，其中 D-1（写端点保留 410 Gone）、D-3（`tenant_purge.py` 保留旧表清理项）、D-4（T019 仅静态源码比对）**已全部返工对齐 spec**，详见 `tasks.md`「偏差处理」与 ADR-9「豁免与严格收口」。**唯一保留的偏差**登记如下：

- **豁免项**：FR-003 中「每人自己的默认项目，不做 ∪」。
- **实际行为**：`GET /projects` 的 `$or` 额外纳入 `{_id: "default"}`，默认项目按**租户共享兜底项**处理，同租户所有用户可见该行。
- **原因**：046 遗留的 `pg_compat` 把 `id` 设为全局主键，同租户第二个用户 upsert `"default"` 会 `ON CONFLICT DO NOTHING` 而拿不到自己的行。改主键/DDL 会影响 046 数据面、超出 049 范围。
- **影响面**：仅默认项目这一个兜底行；非默认项目仍严格按「创建者 ∪ 成员」可见。默认项目本就不可写成员（FR-002 → 400）、不渲染「…」菜单，不参与协作语义。
- **后续**：若要把默认项目改回每人一条，需单独立项处理主键与历史数据，不能在本批次顺带改。
