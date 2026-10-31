# Feature Specification: 项目维度统一（项目 = 工作目录）

**Feature Branch**: `046-project-dimension`

**Created**: 2026-10-31

**Status**: Draft

**Input**: `specs/035-cost-attribution/review-2026-10-30-dimension-source-audit.md` §7.1（D0–D8 决策）与 §8 落地顺序 P0/P1/P2。用户口径：「项目首先作为会话的归集入口，还要对应本地桌面目录，便于编写智能体（code）」；「chat-api 中的项目要和 user-web 中的项目一致，是一个概念，配额项目也建议用这个概念」。

> **与既有 spec 的关系**：本特性**不新建项目抽象**，而是把已存在的三套同名概念收敛成一套——user-web 的工作目录、chat-api 的 `desktop_projects`、042 的 `quota_projects`。035 的「空间」维度改名为「项目」后，本特性负责让它**真正有数据**。042 的配额项目层按本特性收敛（`scope_id = project_id`）。
>
> **不落代码的前置**：本文件为 SDD 正向流程的规约产物，`tasks.md` 全部未勾选；代码改动待 `/speckit-implement` 阶段。

## 背景与问题（为什么现在做）

同一份代码里有三个"项目"，各自有 id、互不相认：

| 概念 | 载体 | 谁在用 | 问题 |
|---|---|---|---|
| 工作目录 | user-web 本地注册表 `DshWorkspace`（`platform/types.ts:81-91`，含 `path`） | 员工选目录、跑 code 会话 | 路径只在本机，服务端没有实体 |
| 桌面项目 | `chat-api` 集合 `desktop_projects` + `api/endpoints/projects.py` | code 会话绑定、侧边栏分组 | 与配额、成本完全无关 |
| 配额项目 | `admin-api` 集合 `quota_projects`（成员内嵌数组） | 042 项目层额度 | 是"自定义分组"，与目录无关 |

后果：成本/用量的「项目」维度**拿不到数据**——`TokenUsageRecord.workspace_id` 线上恒空（`instrumented_client.py:203` 的回退链没有上游供给）；web 会话没有项目归属，侧边栏靠 `filter(!code_project?.workspace_id)` 把非 code 会话排除在分组外；042 的项目额度管的是另一批 id。**一个会话的成本，说不清属于哪个项目。**

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 选一个本地目录就是一个项目 (Priority: P1)

员工在 user-web 里选本地目录创建项目，之后用该项目发起 code 会话；不选目录直接聊天的 web 会话，自动归到「默认项目」。两种会话在侧边栏里都能按项目分组看到，不会因为"没绑目录"而消失在分组之外。

**Why this priority**: 这是整个特性的地基——项目要先成为**会话的唯一归集入口**，后面的成本、配额才有意义。没有这一步，项目维度永远是空的。

**Independent Test**: 新建一个项目（选目录）→ 发起 code 会话 → 再开一个不选目录的会话；查库断言两条会话的 `project_id` 分别为该 workspace id 与 `"default"`，且侧边栏两个分组都可见。

**Acceptance Scenarios**:

1. **Given** 员工已登录且本地有可选目录，**When** 创建项目并选目录，**Then** 项目落库（`projects` 集合，`_id = workspace_id`），侧边栏出现该项目分组。
2. **Given** 员工不选目录直接新建对话，**When** 会话建立，**Then** 会话 `project_id = "default"`，归入「默认项目」分组。
3. **Given** 租户内任意用户首次访问，**When** 系统初始化其项目空间，**Then** 幂等生成一条 `_id = "default"` 的默认项目（重复执行不产生第二条）。
4. **Given** 两个员工各自建了同名项目，**When** 分别查询，**Then** 互不可见（项目归属 `tenant_id + user_id`，不是租户级共享实体）。

---

### User Story 2 - 目录不在了，项目自动归档 (Priority: P1)

员工的本地目录被删掉（或换了机器）后，那个项目不再出现在活跃分组里，也不会继续占用配额；但它的历史会话、历史成本一条不丢，恢复目录后可以重新启用。

**Why this priority**: 不归档就会留下"永远配不上目录的僵尸项目"，侧边栏越用越乱、配额还会被一个已不存在的项目吃掉。归档是让项目生命周期闭环的最小机制。

**Independent Test**: 手工删掉某项目的本地目录 → 客户端下一次对账 → 断言该项目 `status = archived`、侧边栏活跃分组不再显示、配额取小不再命中；把目录恢复并触发对账 → `status` 回到 `active`。

**Acceptance Scenarios**:

1. **Given** 项目登记过目录而该目录已不存在，**When** 客户端完成一次项目对账，**Then** 上报并把该项目置 `archived`。
2. **Given** 项目已归档，**When** 计算任意层的配额，**Then** 该项目不参与取小（等价于停用），但其策略行与历史用量保留。
3. **Given** 项目已归档且目录恢复，**When** 客户端再次对账，**Then** 项目回到 `active`，配额立即重新生效，无需重建项目。
4. **Given** 服务端，**When** 未收到客户端上报，**Then** **不得**自行扫描磁盘或按时间推测归档（服务端不知道目录是否存在）。

---

### User Story 3 - 成本与用量按项目看得见 (Priority: P2)

运营在驾驶舱的成本段看到「项目」分组：哪个项目花了多少、多少次调用；点进单次调用明细能看到这次调用属于哪个项目。原先恒为「未分配」的那一栏开始有真实分桶。

**Why this priority**: 这是 035 承诺但没兑现的部分。它依赖 US1 的数据供给，所以排在后面；但它是"项目"这个概念唯一对管理层可见的价值出口。

**Independent Test**: 用同一项目跑 3 次对话 → 查驾驶舱成本段，`projectAttribution.available = true` 且该项目分桶的 `calls = 3`、成本合计与 `totalCost` 对账一致；下钻明细里该 3 条的 `projectId` 均非空。

**Acceptance Scenarios**:

1. **Given** 项目内已有调用，**When** 打开驾驶舱成本段，**Then** 「项目」分组 `available = true`，分桶按成本降序，合计与 `totalCost` 对账（`reconciles` 绿）。
2. **Given** 项目内尚无调用，**When** 打开同一视图，**Then** 显示 `available = false` + `reason`，**不填零**（延续 008 诚实占位纪律）。
3. **Given** 单次调用明细，**When** 展开某条记录，**Then** 返回 `projectId` 且与所属会话一致。
4. **Given** web 会话（无目录），**When** 归集，**Then** 落入「默认项目」分桶，不落「未分配」。

---

### User Story 4 - 项目额度按项目 id 生效 (Priority: P2)

租户管理员给某个项目配额度后，该项目下所有成员的用量合计受这道限额约束；不再需要"新建分组 + 勾选成员"这套独立实体。

**Why this priority**: 042 已经实现了三层取小的引擎，本故事只是把项目层的 `scope_id` 从"分组 id"换成"项目 id"。工作量小，但它决定了"项目"能否成为配额的载体。

**Independent Test**: 给某项目配额度 = 一次调用用量 → 该项目成员 A 调用成功、成员 B 被拒且错误信息指明项目层；把项目归档后两人恢复。

**Acceptance Scenarios**:

1. **Given** 项目已配额度，**When** 该项目下任一成员发起对话，**Then** 项目层剩余 = 项目总额度 − 该项目周期内用量之和，参与四层取小。
2. **Given** 项目层剩余为 0 而其他层仍有剩余，**When** 成员发起对话，**Then** 被拒（`QuotaExceededError`）且错误信息指明项目层。
3. **Given** 项目被归档，**When** 其成员发起对话，**Then** 项目层不参与取小（US2 场景 2）。

---

### Edge Cases

- **同一本地目录被两个项目绑定**：允许（客户端注册表以 workspace_id 为键，不同 workspace_id 可指向同一路径）；服务端不校验路径唯一性——路径不上云。
- **项目登记了但目录从未存在过**（用户手工改库）：按"目录不存在"处理，下一次对账归档。
- **默认项目被误归档**：`_id = "default"` 的项目**不可归档、不可删除**；客户端上报归档时服务端拒绝并返回明确错误。
- **会话在项目归档后继续使用**：允许查看历史；新调用按归档项目不计入配额（US2 场景 2），但成本照记（成本是事实，不该被配额语义抹掉）。
- **迁移窗口内新老字段并存**：读侧按 `project_id or workspace_id or "default"` 兼容，避免空值落「未分配」。
- **集合改名窗口内旧进程仍在写 `desktop_projects`**：改名必须与代码发布同一窗口，滚动升级期间旧实例会写进已改名的集合而报错——发布顺序为"停旧实例 → 改名 → 起新实例"。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 项目实体 MUST 唯一化为集合 `projects`（原 `desktop_projects` 改名，D6）；`_id` MUST 为 workspace id（客户端生成），默认项目为保留值 `"default"`（D2）。
- **FR-002**: `projects` MUST 记录 `tenant_id` / `user_id` / `title` / `worktree` / `status` / 时间戳；`status ∈ {active, archived}`；MUST 建索引 `{tenant_id, user_id, status}`。
- **FR-003**: 系统 MUST 为每个 `(tenant_id, user_id)` 幂等生成一条 `_id = "default"` 的默认项目（重复调用不产生第二条）；默认项目 MUST NOT 被归档或删除。
- **FR-004**: `chat_sessions` MUST 具备 `project_id` 字段；code 会话取绑定的 workspace id，web 会话取 `"default"`；**新会话 MUST NOT 留空**。
- **FR-005**: 用量事实 MUST 以 `project_id` 归集（`TokenUsageRecord.workspace_id` 改名 `project_id`）；单次调用下钻 MUST 返回 `projectId`（原 `workspaceId`）。
- **FR-006**: 模型网关令牌 MUST 携带 `user_id`（与工具网关令牌对齐）；网关 MUST 按会话 id 反查绑定得到 `project_id`（带短 TTL 缓存，查不到落 `"default"`）；**MUST NOT 信任请求体里客户端上报的 workspace id**。
- **FR-007**: 内容/呈现等旁路服务 MUST 以合并方式写请求上下文，MUST NOT 整体覆盖（避免冲掉 `agent_id` / `skill_id`）。
- **FR-008**: 系统 MUST 提供一次性回填：遍历会话绑定把历史会话的 `project_id` 补齐（无绑定者落 `"default"`）；回填 MUST 分批、可重入、产出失败清单（D4）。
- **FR-009**: 项目归档 MUST 由客户端对账触发上报（D7）；服务端 MUST NOT 定时扫描或按时间推测；归档 MUST 保留策略行与历史用量。
- **FR-010**: 侧边栏 MUST 按 `project_id` 分组展示会话，web 会话归入默认项目分组，**MUST NOT** 因"无 workspace 绑定"被排除。
- **FR-011**: 迁移期读侧 MUST 兼容 `project_id or workspace_id or "default"` 三级回退。
- **FR-012**: 042 配额项目层 MUST 以 `project_id` 为 `scope_id`；原 `quota_projects` 的"成员内嵌数组"语义 MUST 下线（不再作为项目成员来源）。
- **FR-013**: 项目相关 HTTP 契约 MUST 保持不变（路径仍为 `/projects`，字段名不变）；集合改名与字段改名 MUST NOT 造成对外接口破坏。

### Key Entities

- **Project**：`{_id (= workspace_id | "default"), tenant_id, user_id, title, worktree, status: active|archived, created_at, updated_at}`。本地目录路径**不在**服务端存储（只在客户端注册表 `DshWorkspace.path`）。
- **ChatSession.project_id**：会话的项目归属，必填；与 Project 多对一。
- **TokenUsageRecord.project_id**：调用的项目归属（冗余字段，供聚合），与会话一致。
- **DshWorkspace**（客户端侧，既有）：`{id, title, path, ...}`，本特性只增加"与 Project 对账"的职责，不改变其结构。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 存量会话 `project_id` 空值率 = 0（回填后按 `{project_id: null}` 或空串查询命中 0 条）。
- **SC-002**: 驾驶舱成本段「项目」分组 `available = true` 且分桶合计与 `totalCost` 对账一致；「未分配」分桶占比 < 5%（迁移窗口外的稳定态）。
- **SC-003**: 项目 CRUD 与侧边栏分组无回归——既有项目相关接口全部通过，`/projects` 路径与字段名不变。
- **SC-004**: 回填脚本幂等：连续执行两次，第二次写入 0 条。
- **SC-005**: 归档项目不参与任何层的配额取小（构造归档 + 额度用尽的 fixture，断言请求放行）。
- **SC-006**: 侧边栏中"无项目归属"的会话数 = 0（含 web 会话）。

## Assumptions

- 员工使用的是自研的 user-web 客户端（不是 DSH 桌面端/web 端），项目创建与目录选择都在该客户端完成。
- 一个用户可有多台设备，同一 workspace_id 可能只在其中一台有目录——归档判定以"最后一次对账的设备"为准，不要求全设备一致。
- 项目不做多人共享（D1）：项目天然属于 `tenant_id + user_id`，不引入成员表。
- 配额不是本特性的关键项（D5）：用量事实主体是会话，用户/项目只是会话属性，默认不限额。
- 集合改名可接受短暂停机（单租户部署形态，无跨版本并存要求）。

## Non-Goals

- 不做多人共享项目、不做跨用户会话共享。
- 不把本地目录路径上传到服务端（隐私边界，`worktree` 只存分支/仓库标识，不存绝对路径）。
- 不引入 `missing-dir` 等中间状态（D7 已定：只有 active / archived 两态）。
- 不做项目层配额的能力扩展（单轮复检、项目层索引优化、新告警通道）。
- 不重命名 `user_quota_policies` 集合（历史遗留，改名收益为零）。
