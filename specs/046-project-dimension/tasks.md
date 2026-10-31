# Tasks: 项目维度统一（项目 = 工作目录）

**Input**: Design documents from `/specs/046-project-dimension/`

**Prerequisites**: plan.md (required), spec.md (required)

**Tests**: 后端 pytest（chat-api / admin-api 既有测试树）+ 迁移脚本幂等测试；前端用 `node scripts/check_sfc.mjs` 单文件编译校验（不做全量 `vite build`，本机 >10min）。

**Organization**: 按 035 §8 的三阶段（P0 数据模型 → P1 回填 → P2 切读）分 Phase，每阶段内按用户故事组织；T001 起连续编号，全部 `- [ ]`。

## Phase 1: Setup

- [ ] T001 记录基线：`git status --porcelain` 快照 + `grep -rn "desktop_projects" --include=*.py services/ apps/` 全量清单（改名影响面），产出到本文件末尾「改名影响面」小节
- [ ] T002 [P] 确认 `agent_kernel_bindings` 文档形状与 `source_workspace_id` 覆盖率（`distinct` 计数 + 空值计数），决定回填脚本的分批大小

---

## Phase 2: P0 数据模型（读写行为不变）

**Purpose**: 让新产生的数据**有项目归属**，但不改变任何既有读路径。完成后系统行为与改造前一致。

### US1 项目实体（FR-001/002/003/013）

- [ ] T003 [US1] `services/chat-api/app/api/endpoints/projects.py`：集合常量 `desktop_projects` → `projects`，**HTTP 路径与响应字段名一律不动**（FR-013）
- [ ] T004 [US1] 迁移脚本 `scripts/migrate_046_project_dimension.py` 增加 `--rename-collection` 子命令：`renameCollection` + 幂等判断（目标已存在则跳过并告警）
- [ ] T005 [P] [US1] `projects` 补 `status` 字段（`active` / `archived`，默认 `active`）+ 建索引 `{tenant_id, user_id, status}`
- [ ] T006 [US1] 默认项目幂等 upsert：`_id = "default"`、`status = "active"`、`title = "默认项目"`；仿 `directory_repository.ensure_root_department` 的写法；`_id = "default"` 拒绝归档/删除（spec Edge Case 3）
- [ ] T007 [P] [US1] `services/chat-api/tests/test_projects_rename.py`：改名后 CRUD 全通 + 默认项目 upsert 连跑两次只 1 条 + 默认项目归档被拒

### US3 计量与归集（FR-005/006/007）

- [ ] T008 [US3] `services/chat-api/app/token_usage/models.py`：`workspace_id` → `project_id`；同步改 `llm/instrumented_client.py` 的记录构造（回退链收敛为 `project_id or "default"`）
- [ ] T009 [P] [US3] `services/admin-api/app/api/routes/analytics.py`：下钻返回 `workspaceId` → `projectId`（前后端同批改，见 T021）
- [ ] T010 [US3] `dsh_runtime/model_gateway/token.py` + `service.py`：claims / output_spec 增加 `user_id`
- [ ] T011 [US3] `dsh_runtime/profile/resolver.py`：模型网关令牌补 `user_id = snapshot.subject_user_id`（对齐工具网关 `:40-46`）
- [ ] T012 [US3] 网关按 `request.sessionId` 反查 `agent_kernel_bindings.source_workspace_id` → `project_id`，带短 TTL 缓存（同会话只查一次），未命中落 `"default"` 并计数（FR-006）
- [ ] T013 [P] [US3] `enterprise_capabilities/content/service.py` + `presentation/service.py`：`set_request_context` → `merge_request_context`（FR-007）
- [ ] T014 [US3] `tests/test_project_attribution.py`：构造一次网关调用，断言 `token_usage_logs` 行的 `project_id` / `user_id` 非空；未绑定的会话落 `"default"`

### US1 会话归属（FR-004）

- [ ] T015 [US1] `dsh_runtime/conversation/repository.py`：会话创建写 `project_id`（code = 绑定的 workspace id；web = `"default"`）
- [ ] T016 [P] [US1] 迁移脚本 `--add-session-field`：`chat_sessions` 补 `project_id`（先允许空，P2 再收紧）

**Checkpoint**: P0 完成后新数据有归属、旧读路径零变化。此时可停在这里观察一段时间，不影响线上行为。

---

## Phase 3: P1 全量回填（D4）

- [ ] T017 [US3] 迁移脚本 `--backfill`：遍历 `agent_kernel_bindings`，按 `source_workspace_id` 回填会话 `project_id`；无绑定 → `"default"`
- [ ] T018 [US3] 回填分批 500 + `update_many` 幂等 + 失败清单落 `backups/046-backfill-failures-<ts>.json` + 断点续跑（记录最后处理的 `_id`）
- [ ] T019 [P] [US3] `tests/test_backfill_project_id.py`：构造 3 类会话（有绑定/无绑定/已归档项目），连跑两次断言第二次写入 0 条（SC-004）
- [ ] T020 [US3] 回填后校验：`{project_id: null}` 与 `{project_id: ""}` 命中 0 条（SC-001）；「未分配」占比统计输出到脚本末尾

**Checkpoint**: 存量会话 100% 有项目归属，成本段可以开始按项目归集。

---

## Phase 4: P2 切读

### US1 侧边栏分组（FR-010/011）

- [ ] T021 [US1] `apps/user-web/src/App.vue`：分组键改 `project_id`；去掉 `filter(!code_project?.workspace_id)` 的排除逻辑，web 会话进默认项目分组
- [ ] T022 [P] [US1] 迁移期读侧兼容 `project_id or workspace_id or "default"`（FR-011），并留一条 TODO 注明移除时点
- [ ] T023 [US1] `node scripts/check_sfc.mjs apps/user-web/src/App.vue` 编译通过；手工验证两个分组都可见

### US2 自动归档（FR-009）

- [ ] T024 [US2] `apps/user-web/src/composables/code/userBoundProjects.ts`：对账时发现目录不存在 → 调 `PATCH /projects/{id}` 置 `archived`；目录恢复 → 置回 `active`
- [ ] T025 [P] [US2] 服务端 `PATCH /projects/{id}` 只接受 `status` 字段变更，`_id = "default"` 返回 400
- [ ] T026 [US2] `services/admin-api/app/services/quota_projects.py`（或 042 的 `_project_scope_ids`）：只取 `status = active` 的项目参与取小
- [ ] T027 [P] [US2] `tests/test_project_archive.py`：归档项目不参与配额取小；归档保留策略行与历史用量；恢复后立即生效（SC-005）

### US3 驾驶舱与配额（FR-012）

- [ ] T028 [US3] `services/admin-api/app/api/routes/dashboard.py`：成本段「空间」改「项目」（与 048 的业务线删除同批改，避免两次动同一个函数）
- [ ] T029 [P] [US3] `apps/admin-web/src/views/dashboard/DashboardPage.vue`：维度标签 `space: '空间'` → `project: '项目'`，类型定义同步
- [ ] T030 [US3] 042 侧收敛：项目层 `scope_id = project_id`，`quota_projects` 成员内嵌数组不再作为成员来源（FR-012）
- [ ] T031 [P] [US3] `tests/test_dashboard_project_dimension.py`：成本段 `projectAttribution.available = true`、分桶合计与 `totalCost` 对账、web 会话落默认项目（SC-002）

---

## Phase 5: Polish

- [ ] T032 [P] 文档同步：035 `review-...md` §8 标注 P0/P1/P2 完成状态；`specs/INDEX.md` 046 行更新
- [ ] T033 [P] 042 `spec.md` / `plan.md` 的「项目分组」表述按本特性收敛结果回填
- [ ] T034 全量回归：`services/chat-api` 与 `services/admin-api` 既有配额/项目/驾驶舱测试全绿；`vue-tsc --noEmit` 两 app 各 0 错误

---

## Dependencies & Execution Order

```
T001–T002（基线）
  └─ P0：T003–T007（项目实体）   T008–T016（计量与会话）  ← 两组可并行
       └─ P1：T017–T020（回填）── 必须在 T008/T012 之后（否则回填的是空字段）
            └─ P2：T021–T031 ── T028/T029 与 048 同批；T030 依赖 042 已实现
                 └─ Polish：T032–T034
```

- **T012 是整个特性的卡点**：没有它，回填和驾驶舱都拿不到项目归属。
- **T028/T029 与 048 强耦合**：同一函数（`_attribution_dimensions`）要同时删业务线段、改空间段，**必须同批改**，否则两次改同一块代码。
- **T024 依赖 T025**（客户端要调的服务端能力先就位）。
- **发布顺序**：T004 的集合改名必须"停旧实例 → 改名 → 起新实例"，不能滚动升级（spec Edge Case 6）。

## 改名影响面（T001 产出，待填）

| 位置 | 现状 | 目标 |
|---|---|---|
| （待 T001 执行后填写） | | |

## Notes

- [P] 任务 = 不同文件、无依赖，可并行
- 每阶段结束是一个可交付检查点：P0 完成后线上行为不变，P1 完成后数据齐备，P2 完成后用户可见
- 迁移脚本所有子命令都必须幂等 + 支持 `--dry-run`
- 不动 `user_quota_policies` 集合名（042 Non-Goal 已声明）
