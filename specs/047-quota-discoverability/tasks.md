# Tasks: 配额可发现性与跨服务口径

**Input**: Design documents from `/specs/047-quota-discoverability/`

**Prerequisites**: plan.md (required), spec.md (required)；**046 的 T004（集合改名 `desktop_projects` → `projects`）必须先完成**

**Tests**: 前端 `node scripts/check_sfc.mjs <file>`（不跑全量 `vite build`）；后端 `tests/test_quota_consistency.py` 新增 + 既有配额测试回归。

**Organization**: 按用户故事分 Phase，US1/US2 为 P1（先做），US3–US5 为 P2；T001 起连续编号，全部 `- [ ]`。

## Phase 1: Setup

- [ ] T001 基线：`grep -rn "团队" apps/admin-web/src services/*/app` 记录全部命中（区分"文案"与"标识符"），产出「团队字样清单」到本文件末尾
- [ ] T002 [P] 基线：`grep -rn "open=quota\|openSettings\|openScopes" apps/admin-web/src` 列出全部深链调用点（确认 A2 的改动面）

---

## Phase 2: US1 独立菜单「项目管理」(P1) 🎯 MVP

**Goal**: 侧边栏出现「项目管理」，页内含项目列表 / 用量成本 / 项目额度三块。

**Independent Test**: 单击侧边栏「项目管理」→ 三块内容可见；页面无"新建项目"、无"团队"字样。

- [ ] T003 [US1] 新建 `apps/admin-web/src/views/projects/ProjectsPage.vue`：三个区块（列表 / 用量成本 / 额度配置），表格与表单沿用 `HookRulesPage.vue` 的交互范式，只引 naive-ui
- [ ] T004 [US1] 注册路由 `/projects`，`meta.title = '项目管理'`（菜单由 `useMenuOptions.ts` 依 `meta.title` 自动派生，无需改菜单文件）
- [ ] T005 [P] [US1] `apps/admin-web/src/api/projects.ts`：项目列表 + 用量/成本（合并成一个请求，避免 N+1）
- [ ] T006 [US1] 列表只读：无"新建/编辑成员"按钮；归档项目折叠进「已归档」分组（依赖 046 FR-002 的 `status`）
- [ ] T007 [US1] 额度列：已配置显示额度/周期/已用/剩余；未配置显示「未设置额度」，**不显示 0**
- [ ] T008 [P] [US1] `node scripts/check_sfc.mjs apps/admin-web/src/views/projects/ProjectsPage.vue` + `vue-tsc --noEmit` 通过

**Checkpoint**: 入口可用，但深链还指着旧地方——下一 Phase 修。

---

## Phase 3: US2 深链分流 (P1)

**Goal**: 告警"去配置"落在对应层。

**Independent Test**: 项目告警 → 项目配额视图；租户告警 → 租户额度；非法参数 → 默认视图 + 提示。

- [ ] T009 [US2] `TrafficAllocationsPage.vue` 的 `consumeOpenQuotaQuery()`：`open === 'quota'` 改为跳转 `/projects?open=quota`（原为 `openSettings()`）
- [ ] T010 [US2] 新增 `?open=tenant` → 打开租户额度弹窗（原"企业额度"）
- [ ] T011 [P] [US2] `ModelsPage.vue:27/766`：按告警 `scope_type` 分流——`project` → `/projects?open=quota`，`org` → `/organizations/traffic?open=tenant`
- [ ] T012 [US2] 非法/缺失参数：落默认视图 + 提示，不白屏；无权限时明确提示（不静默降级）
- [ ] T013 [P] [US2] 手工验证三条路径 + 旧书签 `/organizations/traffic?open=quota` 不 404

**Checkpoint**: US1 + US2 完成后，可发现性问题已闭环（MVP）。

---

## Phase 4: US3 驾驶舱配额异常 (P2)

- [ ] T014 [US3] `DashboardPage.vue`：新增「配额异常」卡片，消费 `/overview` 的 `quotaAnomalies`
- [ ] T015 [P] [US3] `available = false` 时渲染 `reason`（后端已给），**不得**用 0 兜底（沿用 `qualityAnomalies` 的既有处理方式）
- [ ] T016 [US3] 点击条目跳对应层配置（复用 T009/T010 的深链）
- [ ] T017 [P] [US3] `node scripts/check_sfc.mjs apps/admin-web/src/views/dashboard/DashboardPage.vue`

---

## Phase 5: US4 空态与旧入口 (P2)

- [ ] T018 [US4] `ProjectsPage.vue` 空态：文案「项目在 user-web 里选本地目录创建」+ 跳转链接
- [ ] T019 [P] [US4] `TrafficAllocationsPage.vue:25` 的「团队 / 项目额度」按钮改为跳转 `/projects`；按钮文案改「项目额度」
- [ ] T020 [US4] 同页额度弹窗：移除项目 tab，只留**租户额度**
- [ ] T021 [P] [US4] 文案清理（FR-006）：按钮、tab 名、拒绝消息里的「团队」→「部门」；**标识符一律不动**（`scope_type="team"`、`teamRemainingPoints`、`setup_team`、`/traffic-allocations/teams/...`）

---

## Phase 6: US5 跨服务口径一致 (P2)

- [ ] T022 [US5] `services/{chat-api,admin-api}/tests/test_quota_consistency.py`：同内容 fixture（四层策略 + 固定用量），两侧 `get_quota_summary` JSON 逐字段比对，差异时打印字段名
- [ ] T023 [US5] 先跑出差异（预期失败），记录差异清单到本文件「口径差异」小节
- [ ] T024 [US5] 统一 tz 语义：两份 `quota_policy.py` 二选一（全 aware 或全 naive），文件头注明选择与理由；`admin-api` 未装 `pytest-asyncio`，用文件内 `@async_test` 包装
- [ ] T025 [P] [US5] T023 转绿；既有 `test_quota_three_level.py` / `test_quota_unlimited.py` / `test_setup_quota.py` / `test_governance_us4_us5.py` 全绿（SC-006）
- [ ] T026 [P] [US5] 反证测试有效：人为把一侧口径改坏 → 测试必须失败 → 改回

---

## Phase 7: Polish

- [ ] T027 [P] 042 `spec.md` 补「实现落点索引」（FR-009），标注 `93428a82` 提交信息误标为 032-033-034
- [ ] T028 [P] 042 `spec.md` / `plan.md` 双向声明：项目概念以 046 为准（FR-010）
- [ ] T029 [P] 补 042 的 T023（C1）：`node scripts/check_sfc.mjs apps/admin-web/src/views/organizations/TrafficAllocationsPage.vue` + 手工联调记录
- [ ] T030 [P] `specs/INDEX.md` 047 行更新；035 `review-...md` §7.2 标注批次 A/B/C 完成状态

---

## Dependencies & Execution Order

```
046 T004（集合改名）── 阻塞 T003/T005
  └─ US1：T003–T008
       ├─ US2：T009–T013（T009 依赖 T003 的页面存在）
       │    └─ US3：T016 复用 T009/T010 深链
       └─ US4：T018–T021（T019 依赖 T003）
US5：T022–T026 ── 与 A 批并行，无依赖
Polish：T027–T030 ── 最后
```

- **T004（046）是硬前置**：新页面读 `projects`，改名没做就是空列表。
- **T009 与 T003 同批**：深链目标必须先存在，否则点了 404。
- **T021（文案清理）放在最后**：页面结构定型后再统一替换，避免改两遍。

## 团队字样清单（T001 产出，待填）

| 位置 | 类型 | 处理 |
|---|---|---|
| （待 T001 执行后填写） | 文案 / 标识符 | 改 / 保留 |

## 口径差异（T023 产出，待填）

| 字段 | chat-api | admin-api | 结论 |
|---|---|---|---|
| （待 T023 执行后填写） | | | |

## Notes

- [P] 任务 = 不同文件、无依赖
- 所有前端改动只做 SFC 单文件编译 + `vue-tsc`，**不跑全量 `vite build`**（本机 >10min）
- 标识符白名单见 `specs/042-three-level-quota/spec.md` 顶部「标识符对照表」
- B0（`points_unlimited` 补 `, True`）不在此处，见 `specs/042-three-level-quota/tasks.md` T024
