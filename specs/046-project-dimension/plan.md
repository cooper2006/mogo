# Implementation Plan: 项目维度统一（项目 = 工作目录）

**Branch**: `046-project-dimension` | **Date**: 2026-10-31 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/046-project-dimension/spec.md`；决策来源 `specs/035-cost-attribution/review-2026-10-30-dimension-source-audit.md` §7.1（D0–D8）

**Note**: 本计划对应 035 落地顺序的 **P0（数据模型）→ P1（全量回填）→ P2（切读）**。三阶段严格串行，P0 的读写行为**不变**，切换点集中在 P2。代码尚未开工，`tasks.md` 全部未勾选。

## Summary

把三套同名"项目"收敛成一套：集合 `desktop_projects` 改名 `projects`（D6）、补 `status` 与索引、为每个 `tenant+user` 幂等生成默认项目 `"default"`（D2）；`chat_sessions` 增加 `project_id`、`TokenUsageRecord.workspace_id` 改名 `project_id`；网关侧补 `user_id` 并按会话反查 `agent_kernel_bindings.source_workspace_id` 得到项目归属（这是让项目维度**真正有数据**的唯一卡点）；历史会话全量回填（D4）；最后切读——侧边栏按 `project_id` 分组、驾驶舱「空间」段改「项目」、042 配额项目层 `scope_id` 直接取 `project_id`。

## Technical Context

**Language/Version**: Python 3.11+（chat-api / admin-api，FastAPI + pydantic v2 + motor）；TypeScript 5（user-web，Vue 3，无 vue-router）

**Primary Dependencies**: 既有 `chat-api/api/endpoints/projects.py`、`dsh_runtime/conversation/repository.py`、`dsh_runtime/model_gateway/{service,token}.py`、`dsh_runtime/profile/resolver.py`、`llm/instrumented_client.py`、`token_usage/models.py`、`admin-api/api/routes/dashboard.py`、`analytics.py`；user-web 的 `App.vue` / `composables/code/userBoundProjects.ts` / `platform/types.ts`。**零新第三方依赖**

**Storage**: MongoDB / PanWeiDB——`desktop_projects` → `projects`（`renameCollection`）；`chat_sessions` 加 `project_id`；`token_usage_logs` 字段改名；`agent_kernel_bindings` 只读（回填来源）；`quota_projects` 保留但成员语义下线

**Testing**: pytest（chat-api / admin-api 既有测试树）+ 回填脚本幂等测试 + 前端 `@vue/compiler-sfc` 单文件编译（`node scripts/check_sfc.mjs`）

**Target Platform**: Docker Compose 同栈部署（chat-api + admin-api + admin-web + user-web 静态包）

**Project Type**: web-service（双后端）+ web-app（admin-web）+ 客户端（user-web，自研）

**Performance Goals**: 网关反查项目归属走短 TTL 缓存（同会话多次调用只查一次），单次对话入口新增查询 ≤ 1 次；回填脚本 1 万会话量级 10 分钟内完成

**Constraints**: 项目 HTTP 契约不变（`/projects` 路径与字段名）；发布窗口内"停旧实例 → 改名 → 起新实例"，不做跨版本并存；目录路径不上云

**Scale/Scope**: 约 16 个文件（chat-api 10 / admin-api 2 / user-web 3 / 迁移脚本 1）；1 个集合改名（非新建）；零新集合、零新依赖

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Specification-First**: ✅ 本特性先出 spec/plan/tasks，D0–D8 八项决策已在 035 核查中拍板，无 NEEDS CLARIFICATION 遗留。
- **II. Enterprise Production Readiness**: ✅ 迁移分三阶段且 P0 不改读写行为；回填可重入 + 失败清单；归档不删数据。降级路径：任一阶段异常可停在该阶段（P0 完成后系统行为与改造前一致）。
- **III. Security and Data Protection**: ✅ 目录绝对路径不上云（只存 `worktree` 标识）；项目按 `tenant_id + user_id` 隔离，查询必带租户；**不信任客户端上报的 workspace_id**，改由服务端按会话绑定反查（防越权把成本记到别人项目）。
- **IV. Cross-Platform and i18n**: ✅ 新增文案走 `t()` 中文 key 回退；不改既有中英双语键。
- **V. Observability and Simplicity**: ✅ 回填脚本输出处理条数/失败清单/耗时；网关反查未命中时落 `"default"` 并计数（可观测"归不到项目"的比例），不静默吞掉。

## Project Structure

### Documentation (this feature)

```text
specs/046-project-dimension/
├── spec.md              # 本特性需求（已完成）
├── plan.md              # 本文件
├── tasks.md             # Phase 2 输出
└── checklists/
    └── requirements.md  # 需求质量门禁
```

### Source Code (repository root)

```text
services/chat-api/
├── app/api/endpoints/projects.py            # 【改】集合名 desktop_projects → projects；HTTP 契约不变
├── app/dsh_runtime/conversation/repository.py # 【改】会话写 project_id（code = workspace_id / web = "default"）
├── app/dsh_runtime/model_gateway/token.py   # 【改】claims 增加 user_id
├── app/dsh_runtime/model_gateway/service.py # 【改】output_spec 带 user_id + project_id
├── app/dsh_runtime/profile/resolver.py      # 【改】模型网关令牌补 user_id（对齐工具网关）
├── app/llm/instrumented_client.py           # 【改】回退链收敛为 project_id
├── app/token_usage/models.py                # 【改】workspace_id → project_id
├── app/enterprise_capabilities/content/service.py       # 【改】set → merge_request_context
├── app/enterprise_capabilities/presentation/service.py  # 【改】同上
└── tests/test_projects_rename.py            # 【新】改名后 CRUD + 默认项目幂等

services/admin-api/
├── app/api/routes/dashboard.py              # 【改】空间段 → 项目段（与 048 同批改维度名）
└── app/api/routes/analytics.py              # 【改】下钻 workspaceId → projectId

apps/user-web/src/
├── App.vue                                  # 【改】侧边栏按 project_id 分组；对账触发归档
├── composables/code/userBoundProjects.ts    # 【改】目录对账 → 上报 archived/active
└── platform/types.ts                        # 【改】DshWorkspace 与 Project 字段对齐（path 仅本地）

scripts/migrate_046_project_dimension.py     # 【新】P1 回填（分批、可重入、失败清单）
```

**Structure Decision**: 沿用既有 monorepo 布局，不新增服务与页面。改动集中在 chat-api 的项目/会话/计量三处、admin-api 的两个只读聚合点、user-web 的侧边栏与对账逻辑；迁移脚本放 `scripts/`（与既有迁移脚本同目录）。

## 迁移三阶段（对应 035 §8）

**P0 数据模型（读写行为不变）**

1. `projects` 改名 + `status` + 索引 `{tenant_id, user_id, status}`（D6/D7）
2. 默认项目幂等 upsert（D2），仿 `directory_repository.ensure_root_department` 的写法
3. `chat_sessions.project_id` 字段（先允许空，P2 起新会话必填）
4. `TokenUsageRecord.workspace_id` → `project_id`；`analytics.py` 的 `workspaceId` → `projectId`
5. 网关补 `user_id` + 反查 `project_id`（FR-006）——**这一步做完，新产生的用量行就有项目归属**

**P1 全量回填（D4）**

- 遍历 `agent_kernel_bindings`，按 `source_workspace_id` 回填会话 `project_id`；无绑定 → `"default"`
- 分批 500、`update_many` 幂等、失败清单落文件、可重入

**P2 切读**

- 侧边栏按 `project_id` 分组（web 会话进默认项目，去掉 `filter(!code_project?.workspace_id)` 的排除）
- 驾驶舱「空间」段改「项目」段（与 048 的业务线删除同批）
- 042 配额项目层 `scope_id = project_id`，`_project_scope_ids` 改为按项目状态过滤

## Complexity Tracking

| 需要说明的点 | 为什么必须这样 | 更简单的替代为何不可行 |
|---|---|---|
| 集合改名（而非新建 + 双写） | 语义准确，且项目数据量小、无跨版本并存要求 | 新建 `projects` + 双写要长期维护两套读写，改名一次到位 |
| 网关反查项目归属 | 客户端上报可伪造，会把成本记到别人项目 | 信任请求体 → 越权与脏数据；绑定时已落库，服务端反查更可靠 |
| 归档由客户端触发 | 目录是否存在只有客户端知道 | 服务端定时扫描会把"外接盘未挂载"误判为"目录已删" |
