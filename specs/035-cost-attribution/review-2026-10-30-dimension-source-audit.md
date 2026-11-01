# 成本归集（035）+ 三级配额（042）——核实结论与整改方案

- 日期：2026-10-30
- 范围：只读代码核实 + 设计结论，**未落地任何代码**
- 合并来源：本文件合并了原 `specs/035-cost-attribution/review-2026-10-30-dimension-source-audit.md`、`specs/042-three-level-quota/review-2026-10-30-remediation-plan.md` 与 `Decisions/ADR-8-统一项目概念-项目即工作目录.md` 的全部内容。**后续以本文件为唯一正本。**

---

## 一、结论摘要

驾驶舱成本归集段从 6 段收敛为**5 段**：**租户** / 用户 / 部门 / Agent / **项目**。业务线维度**取消**（§4.1–4.3），「企业」维度**改名为「租户」**（§4.4，维度保留）。

> 口径校准：代码里 `_attribution_dimensions()`（`dashboard.py:821-875`）返回的是 6 段（department / businessLine / agent / space / user / enterprise），**模型分组不在这 6 段里**——它由 008 的 `build_cost_section()` 单独给出（`_cost_section` 里 `section.update(...)` 才把归集段并进去）。所以"六维"是历史叫法，实际是"6 个归集段 + 模型分组"；取消业务线后为 5 段。

| 维度 | 代码里有没有这个概念 | 数据能不能进 `token_usage_logs` | 驾驶舱实际表现 |
|---|---|---|---|
| **租户**（原「企业」） | ✅ `tenant_id` | ✅ | 真实但**恒为单桶**——驾驶舱本身按租户隔离，这一段的桶永远只有一个，值等于 `totalCost`；作用是对账锚点，不是分组（§4.4） |
| 模型 | ✅ `model_name` | ✅ | 真实分桶 |
| 用户 | ✅ `user_id` | ⚠️ web 会话有，DSH Agent 网关无 | 部分 `未分配` |
| 部门 | ✅ `org_units` + `end_user_org_relations` | ⚠️ 依赖 `user_id`，同上 | 部分 `未分配` |
| Agent | ⚠️ 半有（`capability_ref` 拆分） | ⚠️ 仅内部能力执行有；主链路无 | 大部分 `未分配` 或落 `node_id` |
| **项目** | ✅ 有（user-web 的真实概念） | ❌ 计量链路没人写 | **恒为 `未分配`** |
| ~~业务线~~ | ❌ 字段不存在、无写入入口 | ❌ | 曾恒为单桶「企业总部」且 `available=True` → **取消** |

一句话：**维度不缺，缺的是"会话到人、会话到项目"这两条属性没写进调用记录。**

---

## 二、业务流层面

### 2.1 部门：真实，但依赖 `user_id`

- 部门树：`org_units`（`parent_id` / `path_ids` / `path_names`），列映射见 `admin-api/app/core/column_map.py:387-399`。
- 用户归属：`end_user_org_relations`（`tenant_id` + `user_id` + `org_id`，唯一索引 `user_org_rel_unique`）。
- 反查范式已有：`dashboard.py:765-812` 的 `_resolve_org_attribution`（用户 → 主部门 → 名称），`analytics.py:117-143` 也有同款。
- **断点**：部门只能从 `user_id` 推，所以 DSH 主力流量没有 `user_id` 时，部门维一起落空（见 2.4）。

### 2.2 项目：user-web 里是真实概念，计量链路没接

**前提**：user-web 是自研客户端，不是 DSH 官方桌面端/Web 端，所以它的项目交互就是产品事实。

真实交互（`apps/user-web/src/App.vue:404-432`）：

```
chooseProjectFolder()  → selectDshWorkspace()        本地选目录 → workspace_id
commitProjectCreate()  → renameDshWorkspace(...)     标题取目录名
                       → createDesktopProject({workspace_id, title, worktree})
                                                     上报 chat-api，落 desktop_projects
                       → userBoundProjects.add(...)  侧边栏出现项目
项目内开会话            → createDshCodeSession(workspaceId, ...)
侧边栏分组             → 按 session.code_project.workspace_id 分组（App.vue:290-320）
```

相关载体：

| 载体 | 字段 | 说明 |
|---|---|---|
| `DshWorkspace`（客户端本地注册表，`platform/types.ts:81-91`） | `workspace_id` / `title` / `path` / `git_branch` / `status` | `path` **只在客户端** |
| `desktop_projects`（chat-api，`api/endpoints/projects.py`） | `tenant_id` / `user_id` / `workspace_id` / `title` / `worktree` | 服务端唯一记录，键是 `tenant+user+workspace_id` |
| `agent_kernel_bindings`（chat-api） | `source_workspace_id` / `dsh_workspace_id` / `git_branch` | 会话与目录的绑定 |
| `attach_session_runtime_contexts`（`services/session_runtime_context.py:40-45`） | 投影成 `session.code_project.workspace_id` | 只读投影，给前端用 |

**结论：项目 = 一个工作目录**，`workspace_id` 就是它的 id。服务端早就记了（`desktop_projects`），只是**计量链路没有把它写进 `token_usage_logs`**。

三条不能违背的既有约束：

1. **执行边界**（`dsh_runtime/contracts/kernel.py:69-78`）：`execution_location == "server"` 的会话**不允许**带 `workspace_id`；`code` + desktop **必须**带。→ 项目要容纳 web 会话，就不能强制等于 workspace。
2. **路径不出客户端**（`dsh_runtime/desktop_binding.py:31`，docstring "never accepts a filesystem path"）：服务端只收不透明的 `workspace_id`。
3. **会话按人隔离**（`dsh_runtime/conversation/repository.py:60-68`，`owned()` 强制 `tenant_id + user_id`）：**项目归集 ≠ 会话共享**。

### 2.3 Agent：半通

- 内部能力执行会注入：`enterprise_capabilities/runtime/service.py:47-55` 把 `capability_ref`（如 `research.progressive@v1`）拆成 `agent_id` / `skill_id` 写进请求上下文。
- 主链路没有：DSH 网关不传任何 agent 标识，驾驶舱只能回落到 `node_id`（`dashboard.py:842`）。
- 两个能力用 `set_request_context`（**全量覆盖**，不是 merge）会把外层注入的 `agent_id`/`skill_id` 冲掉：`content/service.py:60-65`、`presentation/service.py:79-87`。

### 2.4 计量链路的真实断点（最关键）

三条流量来源，注入情况完全不同：

| 流量来源 | 入口 | `user_id` | `agent_id`/`skill_id` | 项目 |
|---|---|---|---|---|
| Web 会话（标题生成等） | `api/endpoints/sessions.py:476` | ✅ | ❌ | ❌ |
| 内部能力执行（research / content / presentation） | `runtime/service.py:47-55` | ✅ | ✅（content/presentation 除外，会被覆盖） | ❌ |
| **DSH Agent 网关（主力流量）** | `dsh_runtime/model_gateway/service.py:176-190` | ❌ **显式不传** | ❌ | ❌ |

DSH 网关的令牌声明只有三项：`tenant_id` / `profile_version` / `model_instance_id`（`model_gateway/token.py:15-21`）。

**对照发现**：同一个 `RuntimeProfileResolver.resolve` 里，工具网关令牌**已经带了 `user_id = snapshot.subject_user_id`**（`profile/resolver.py:40-46`），而模型网关令牌**没带**（`resolver.py:31-35`）。不是技术障碍，是遗漏。

推论：主力 Agent 流量的落库行里 `user_id` / `agent_id` / `workspace_id` 全为空 → 用户、部门、Agent、项目四维同时落 `未分配`，只剩租户（原企业）和模型有真实分桶。

另一处空兜底：`instrumented_client.py:203` 的 `workspace_id || project_id` 回退，全仓**没有任何地方往 `output_spec` 写这两个键**（`output_spec` 有 789 处引用，0 处写它们）；`project_id` 在 chat-api 只服务 `project_memories`，还被硬编码成 `"default"`（`sessions.py:483`）。

---

## 三、数据流层面

```
写：LLM 调用 → output_spec(= request_context ∪ 调用方入参)
              → InstrumentedLLMClient._submit_record (instrumented_client.py:190-212)
              → token_usage_logs
                 ├ user_id      ← output_spec.user_id        （DSH 网关不传）
                 ├ agent_id     ← output_spec.agent_id       （仅内部能力注入）
                 ├ skill_id     ← output_spec.skill_id       （同上）
                 └ workspace_id ← output_spec.workspace_id || project_id  ← 恒空

读：admin-api dashboard._cost_section (dashboard.py:825-880)
      ├ 部门  ← end_user_org_relations(org_id) → org_units.name
      ├ Agent ← row.agent_id || row.node_id
      ├ 项目  ← row.workspace_id                                  ← 恒空
      └ 租户/用户/模型 ← 行内字段

下钻：analytics.py:483-497（单次调用明细，含 costUsd / agentId / workspaceId）
前端：DashboardPage.vue:745-760（六维卡片，现需删掉业务线、企业改租户）
```

---

## 四、维度调整：取消业务线、企业改名租户

### 4.1 代码里不存在

1. **字段没人写。**
   - `org_units` 的列映射没有这个字段：`column_map.py:387-399`（只有 `parent_id`/`path_ids`/`path_names`/`type`/`status` 等）。
   - 部门创建/更新接口的请求体只有 `name`/`parentId`/`status`：`api/routes/directory.py:155-163`；`create_department`（:267-300）与 `update_department`（:310-330）落库字段里没有 `is_business_line`。
   - 租户初始化的根部门也没有：`repositories/directory_repository.py:81-98`（`企业总部`，`path_ids: []`）。
   - 全仓 `is_business_line` 只出现在 `dashboard.py:753/838`（035 自己写的读取与文案）和 035 的测试里。**没有一处写入。**
2. **spec 的维护口径不成立。** 035 `spec.md` R-1 称"经既有组织单元写入路径维护"，但该路径不接受这个字段，管理员只能直接改库。`checklists/requirements.md:13` 的 CHK001 问的正是这一点，结论被 R-1 一句话盖过去了。
3. **读取分支退化成单桶。** `dashboard.py:739-763` 的 `_resolve_business_line`：找不到标记就"回落最高可见祖先"——实现是遍历链找 `parent_id in (None, "")` 的节点，**那必然是根节点**。所以任何有部门关系的用户都归到 `企业总部`；而 `_build_attribution` 的 `available` 判据是"有没有非 `未分配` 的 key"，`企业总部 ≠ 未分配` → **`available=True`**。测试把这个行为固化了（`tests/test_cost_attribution_035.py:190-191`）。

### 4.2 取消理由

- 产品上组织维度只有"部门树"一层，没有"业务线"这个对象；强行用一个布尔标记派生，等于让管理员手工改库才能生效。
- 当前实现不是"缺数据"，而是**伪造出了一个看起来有数据、实际零信息量的单桶**，比 008 原来的诚实占位更误导。
- 部门树本身可以表达层级，需要"业务线视角"时用部门树的某个子树即可，不需要新维度。

### 4.3 删除清单

**代码部分（未落地，随 US2 改动同批执行）**

| 位置 | 内容 |
|---|---|
| `admin-api/app/api/routes/dashboard.py:834-838` | `business_line = _build_attribution(...)` 整块 |
| `dashboard.py:866` | 返回字典里的 `"businessLineAttribution"` |
| `dashboard.py:739-763` | `_resolve_business_line()` 整个函数 |
| `dashboard.py:765-812` | `_resolve_org_attribution()` 里 `business_line_map` 相关分支（保留部门部分） |
| `admin-web/src/views/dashboard/DashboardPage.vue:748` | 维度标签 `business_line: '业务线'` |
| `DashboardPage.vue:759` | 维度来源数组里的 `['business_line', section.businessLineAttribution]` |
| `DashboardPage.vue:421` | 类型定义 `businessLineAttribution: CostAttribution` |
| `tests/test_cost_attribution_035.py:158/190-191/202-215` | 业务线相关断言与用例（改写为"部门反查 + 项目维分桶"） |

**文档部分（2026-10-30 已同步完成 ✅）**

| 文件 | 已改内容 |
|---|---|
| `spec.md` | 标题与定位去掉"业务线"；决策表 #3 标注**已取消**并写明证据；US2 场景 4 由"业务线归集"改为"web 会话落默认项目"；FR-007 删除业务线 MUST；SC-004 加"业务线不得以任何形式回归"；R-1/R-2 作废并注明"后续不得重新引入该字段"；Key Entities 维度数改为五段 |
| `tasks.md` | T004 结论改为"字段无写入路径、不引入"；T010 六维→五段；T011 作废（保留部门口径）；T021 作废并转为**反向任务**（删代码）；T023/T028/T029/T032/T034 六维→五段；顶部加 2026-10-30 变更块 |
| `checklists/requirements.md` | CHK001/CHK002 改判为"维度取消"并注明原 R-1/R-2 与代码不符；CHK006/CHK009 按 ADR-8 更新口径；评审结论加"追加结案"段 |

> 008 不受影响：008 原本只有 `model_name` 分组，业务线完全是 035 新增的。
>
> **为什么文档先改、代码后改**：`spec` 是目标态、代码是现状，两者在整改窗口内必然短暂不一致。文档先落定可以避免"改代码时忘了改 spec"，代价是这期间读 spec 的人需要知道 §4.3 的删除清单尚未执行——所以这一行必须留着，等代码删完再删掉。

### 4.4 「企业」改名「租户」（维度保留，2026-10-30 决策）

**结论：不是取消，是改名。** 用户决策原话：「企业先实际和租户一个概念，建议就改名为租户」。

**为什么该改**：代码里这一段本来就是 `tenant_id`，没有第二个概念——

```python
# dashboard.py:858-862
enterprise = _build_attribution(
    normalized,
    dimension="enterprise",
    dimension_of=lambda row: str(row.get("tenant_id") or tenant_id).strip() or UNASSIGNED,
    note="企业维度取查询范围的 tenant_id（008 已固定租户隔离）。",
)
```

note 文案自己就写着"取 tenant_id"。产品里"企业"这个词还被用在别处（"企业定制版"是定价档位、"企业额度"是 042 的 `scope_type='org'` 层），三个"企业"指三样东西——这是必须收敛的理由。

**与业务线的关键区别**（决定了"取消"还是"改名"）：

| | 企业（→租户） | 业务线 |
|---|---|---|
| 数据源 | `tenant_id`，每行都有 | `is_business_line`，**没有写入方** |
| 桶值真假 | 真的（就是租户 id） | 假的（回落根节点，永远是"企业总部"） |
| 信息量 | 单桶——驾驶舱按租户隔离，永远只有 1 个桶，值恒等于 `totalCost` | 单桶且桶值固定，恒等于"企业总部" |
| 处置 | **改名保留**：它是 `reconciles` 的对账锚点（分组合计要跟它比） | **取消** |

**改名清单（未落地，与 US2 同批）**

| 位置 | 现在 | 改为 |
|---|---|---|
| `dashboard.py:860` | `dimension="enterprise"` | `dimension="tenant"` |
| `dashboard.py:862` | note "企业维度取查询范围的 tenant_id" | "租户维度取查询范围的 tenant_id（驾驶舱本身按租户隔离，故恒为单桶 = 总量，作用是对账锚点）" |
| `dashboard.py:870` | `"enterpriseAttribution": enterprise` | `"tenantAttribution": tenant` |
| `DashboardPage.vue:750` | `enterprise: '企业'` | `tenant: '租户'` |
| `DashboardPage.vue:761` | `['enterprise', section.enterpriseAttribution]` | `['tenant', section.tenantAttribution]` |
| `DashboardPage.vue:425` | `enterpriseAttribution: CostAttribution` | `tenantAttribution: CostAttribution` |
| `DashboardPage.vue:183/742` | 注释里的"企业" | "租户" |
| `tests/test_cost_attribution_035.py:197/236/250` | `enterpriseAttribution` | `tenantAttribution` |

**保留 `enterprise` 字符串的地方**（不是同一概念，别一起改）：`DashboardPage.vue:520` 的 `tier === 'enterprise'`（定价档位"企业定制版"）、`dashboard.py:130` 的注释（`org_quota_policies.unlimited` 指企业版空间，属 020 语义）、`org_units` 根部门名"企业总部"（数据值）。

**顺带要统一的产品文案**：042 的「企业额度」= `scope_type='org'` 层 = 租户层，按同一决策应改称「租户额度」；`?open=enterprise` 深链参数一并改 `?open=tenant`（本来就要新增，没有历史包袱）。这条落在 §7.2 A2。

---

## 五、042 现状核对（FR → 实现 → 结论）

| FR | 实现落点 | 结论 |
|---|---|---|
| FR-001 四层 `scope_type` | 复用 `user_quota_policies`；`chat-api/core/quota_policy.py:28-29` 定义 `TEAM_SCOPE/PROJECT_SCOPE` | ✅ |
| FR-002 部门 = 部门树节点 | `_team_scope_ids` 查 `end_user_org_relations`（直接成员，无子树聚合） | ✅ |
| FR-003 项目 = 新建轻量实体 | 集合 `quota_projects`，`services/quota_projects.py`；`_id` 用 `uuid4().hex` 字符串，与 policy 的 `scope_id` 形态一致 | ⚠️ **要改**：按 §7.1，项目 = 工作目录，`quota_projects` 的成员语义下线 |
| FR-004 分层取小 + `limitingScope` | `get_quota_summary` → `_scoped_layers` 层内取最严 → 层间 `min`（`quota_policy.py:459-470`） | ✅ |
| FR-005 超限拒绝并指明层 | `assert_quota_available` → `_layer_denial_message`，文案含部门/项目名 | ✅ |
| FR-006 未配置层视同 unlimited | `_layer_state` 无策略即返回 `None`，不参与取小 | ✅ |
| FR-007 多命中取最严 | `min(states, key=remaining)` | ✅ |
| **FR-008 管理端入口** | 有 UI，但入口是弹窗内二级 tab；`?open=quota` 打开的是**企业额度** | ⚠️ **偏差** |
| FR-009 审计日志 | `_upsert_scoped_policy` 动态拼 `setup_/update_ + team/project`，写 `user_token_allocation_logs` | ✅ |
| FR-010 超限/接近告警 + 去重 | `_emit_layer_alerts` → `quota_alert_events`，`alert_key` 含租户+层+周期 | ✅ 后端 |
| FR-011 不新建推送通道 | 复用驾驶舱口径 | ✅ 后端 |
| **FR-011 前端展示** | `/overview` 已返回 `quotaAnomalies`（`dashboard.py:967`），**admin-web 零引用** | ❌ **缺失** |
| FR-012 零策略时输出不变 / 001 门禁不动 | `governance/layers/quota.py` 无 diff，等价测试存在 | ✅ |

即：**FR-003 要按 §7.1 改、FR-008 有偏差、FR-011 只做了后端一半**，其余到位。

---

## 六、042 问题清单

### P0-1 驾驶舱没有配额告警展示（FR-011 前端半边）

- 后端 `dashboard.py:967` 返回 `quotaAnomalies`；`summarize_quota_alerts`（`dashboard_metrics.py:347`）已按 `exceeded / approaching / layer_unreadable` 聚合，带 `available` / `reason` / `byScope` / `items`。
- 反证：`apps/admin-web/src` 全仓搜 `quotaAnomalies` **命中 0 处**；`DashboardPage.vue:265` 的 `anomaly-list` 只渲染 `qualityAnomalies`。
- 影响：管理员看不到"哪一层、哪个部门/项目、什么时候超限或接近阈值"。
- 修法：`DashboardPage.vue` 在质量异常旁新增「配额异常」卡片；`available === false` 时显示 `reason`，不渲染 0。

### P0-2 产品内唯一深链指向错误弹窗（FR-008 偏差）

- `TrafficAllocationsPage.vue:598-604` 的 `consumeOpenQuotaQuery()` 在 `open === 'quota'` 时调用 `openSettings()`（企业额度），不是 `openScopes()`（团队/项目）。
- 唯一入口方：`ModelsPage.vue:27` 与 `:766`（额度告警里的"去配置"）都指向 `/organizations/traffic?open=quota`。
- 影响：顺着告警点"去配置"永远落到企业额度，看不到项目配置。
- 修法：`?open=quota` → 团队/项目额度；新增 `?open=enterprise`；`ModelsPage` 按告警类型分流。

### P0-3 入口层级过低、无空态引导、提交信息错位

- 入口是筛选栏一个 `secondary` 按钮「团队 / 项目额度」（`TrafficAllocationsPage.vue:25`）→ 弹窗（`:175`）→ 第二个 tab「项目额度」（`:215`）。三级点击，菜单名"流量分配"与"项目"无语义关联。
- 空态：`quota_projects` 无种子数据，`:263` 只显示「暂无项目分组」。
- 提交信息：唯一引入 `createQuotaProject` 的提交是 `93428a82 feat(032-033-034)`，与 042 无关，`git log --grep=042` 搜不到任何实现提交。
- 影响：按 spec 号追溯必然得出"没落地"的结论。

### P1-1 主力 Agent 流量在单轮内绕过配额（按 D5 降级 P2）

> 配额多数情况默认不限额、不是关键项。本条只在**显式配置额度**的租户上有意义；035 真正需要的 `user_id`（做归集）与它是同一处改动，优先级由归集侧决定。

- 配额校验条件是 `output_spec.user_id` 存在（`llm/configured_models.py:391-401`）；DSH 网关不传；DSH 侧只在会话建立时校验一次（`dsh_chat.py:172`、`:279`）。
- 影响：一轮会话内几十次调用全不校验，`fail-closed` 退化为"每轮开头检查一次"。
- 修法：补 `user_id` 即可（见 §7.1）；**不做单轮内复检**。

### P1-2 两份 `quota_policy` 已漂移（含一个真缺陷）

- 体量：chat-api 536 行 vs admin-api 501 行；时间基准 naive vs aware；`ensure_default_user_policy` 默认值不同。
- **真缺陷**：`points_unlimited` 默认值不一致 —— admin-api `quota_policy.py:351` 是 `bool(org.get("points_unlimited", True))`（缺字段=不限额），chat-api `quota_policy.py:352` 是 `if org.get("points_unlimited"):`（缺字段=限额）。后果：非 `tenant_provisioning` 创建的租户**管理端显示"不限额"、用户端调用却被 402 拦**，且每次调用白跑一遍成员聚合。
- 修法：chat-api 补 `, True`（一行）；再加跨服务一致性测试；tz 语义统一放在测试之后。

### P1-3 `quota_projects` 无索引 + 每次调用做成员聚合（按 D5 降级 P2）

- 修好 P1-2 后，多数租户走 unlimited 短路（`get_quota_summary` 聚合前就 return），这条链不执行。
- 证据：`quota_projects.py` 无 `create_index`；`_project_scope_ids` 按 `member_user_ids` 数组包含查询；`_layer_state` 每次 `sum_usage(user_ids=members)`（`quota_policy.py:148-168`）。

### P2-1 T023 未验收

`specs/042-three-level-quota/tasks.md:48` 的 T023（`@vue/compiler-sfc` 编译 + 手工联调）**未勾选**。P0-2 的深链错误正是"没联调"的产物。

### P2-2 项目软删后策略成孤儿（按"自动归档"决策收敛）

`quota_projects.py:173-184` 软删，策略行保留（docstring 明确"孤儿策略是预期状态"）。`_project_scope_ids` 只取 active，不会误命中；但 `user_quota_policies` 会残留指向已删项目的行，列表不展示。

**按 2026-10-30 决策"目录消失自动归档"收敛后**：项目不再被删，只转 `status = archived`，因此"孤儿策略"这一状态基本消失——

- **归档 ≠ 删除**：归档项目的策略行、历史成本、会话全部保留；`_project_scope_ids` 只取 `status = active`，所以归档项目不再参与配额取小（等价于"停用"），恢复后立即重新生效。
- **策略不删**：归档不动 `user_quota_policies`，避免"恢复项目后配额配置丢了"。
- **只留一个巡检项**：列出"`status = archived` 但仍挂着 active 策略"的项目，供管理员决定是恢复项目还是清掉策略。这条降为 P2 运营巡检，不是 P0 缺陷。

---

## 七、整改方案

### 7.1 项目维度接入（原 ADR-8，已定）

**核心决策**

| # | 决策 |
|---|---|
| D0 | **以 user-web 的项目概念为准**：项目 = 工作目录（`workspace_id`）。chat-api 与配额项目都向它对齐，**不引入第二套抽象** |
| D1 | 允许纯个人项目（项目天然属于 `tenant_id + user_id`，不要求成员、不要求共享） |
| D2 | web 会话（无目录）落**默认项目**，`project_id` **固定为字符串 `"default"`**（2026-10-30 拍板，不用 `default:<user_id>`）；"未分组"就是默认项目，会话 `project_id` 不留空。跨租户同名不成问题——所有查询本来就带 `tenant_id`，`"default"` 只是租户内的保留键 |
| D3 | 目录绑定可选（默认项目没有目录；有目录的项目才能跑 code） |
| D4 | 回填**全量**（`agent_kernel_bindings` 全表扫描，一次性脚本） |
| D5 | 配额不加约束：用量事实主体是**会话**，用户/项目只是会话属性；默认不限额 |
| D6 | **`desktop_projects` 集合改名 `projects`**（2026-10-30 拍板）：集合名、chat-api 路由（`endpoints/projects.py`）、user-web 客户端（`platform/` 里的 desktop project 调用）同步改；迁移用一次性 `renameCollection`，读写切换放在同一发布窗口内 |
| D7 | **目录消失 → 自动归档**（2026-10-30 拍板）：客户端 `listDshWorkspaces` 发现已注册项目的本地目录不存在时，把该项目 `status` 置 `archived` 并上报；归档保留策略与历史成本，不参与配额取小（见 §6 P2-2）。不引入 `missing-dir` 中间态——多一个状态就多一套 UI 分支，而"目录暂时不可用"（外接盘未挂载）与"目录已删"在客户端无法可靠区分 |
| D8 | **配置入口独立成菜单**（2026-10-30 拍板）：admin-web 新建独立菜单「项目管理」，只含项目，**不再出现"团队"概念**（部门维度归组织管理，配额页不做团队配置 tab）。理由见 §7.2 A1 |

**放弃的方案**：曾设计"逻辑项目（租户级实体）+ `project_workspaces`（每用户每设备绑定表）"两层模型。放弃理由：它假设"一个项目多人各自绑不同本地路径"，但 user-web 没有共享项目的产品形态；两层模型还会让项目出现两个 id，而侧边栏、会话绑定、`desktop_projects` 全都已用 `workspace_id` 作键。将来要做团队共享项目，再加绑定表即可，主键不用推翻。

**统一后的模型**

```
项目（project）   ← 集合：projects（原 desktop_projects，D6 改名）
  ├─ id = workspace_id（客户端生成；默认项目为保留值 "default"，D2）
  ├─ tenant_id / user_id        归属（决定谁能看见）
  ├─ title / worktree           服务端记录（路径不上云）
  ├─ status                     active / archived（目录消失自动 archived，D7）
  └─ 本地目录                    仅客户端注册表（DshWorkspace.path）

会话（chat_sessions.project_id）
  ├─ code 会话 = workspace_id
  └─ web 会话  = "default"

调用（token_usage_logs.project_id）
  └─ 与会话一致（冗余，供聚合）
```

**字段命名统一**：`TokenUsageRecord.workspace_id` → `project_id`。该字段线上恒空、无消费方（除 `analytics.py:496` 下钻返回 `workspaceId`），改名零成本；`instrumented_client.py:203` 的回退链收敛为 `project_id`。

**让项目维度真正有数据**（唯一卡点，与 035 方案 B 同一处改动）：

1. `RuntimeProfileResolver.resolve`（`profile/resolver.py:31-35`）给模型网关令牌补 `user_id = snapshot.subject_user_id` —— 工具网关令牌早就这么做（`:40-46`），模型网关漏了。
2. 网关按 `request.sessionId` 反查 `agent_kernel_bindings.source_workspace_id` 得到 `project_id`（带短 TTL 缓存），`"default"` 兜底。
3. **不在请求体里信任客户端上报的 workspace_id**——绑定在会话建立时已落库，服务端反查更安全。
4. `content/service.py:60-65`、`presentation/service.py:79-87` 的 `set_request_context` 改 `merge_request_context`，避免冲掉 `agent_id`/`skill_id`。

**042 侧收敛**：`quota_projects` 的成员语义下线，项目层 `scope_id` 直接用 `project_id`；项目用量若启用则 `group by project_id`。取舍：项目 = 个人目录后，"项目级配额"退化为"个人工作区级"，团队维度只剩部门树——按 D5 可接受。

**迁移（P0 不动读写行为）**

- P0（数据模型）：
  1. `chat_sessions.project_id`（可空 → 新会话必填）。
  2. `TokenUsageRecord.workspace_id` 改名 `project_id`；`analytics.py:496` 的 `workspaceId` → `projectId`。
  3. **`desktop_projects` 集合改名 `projects`**（D6）：一次性 `renameCollection`，同一发布窗口内改 chat-api 路由 `endpoints/projects.py` 与 user-web 客户端调用；路由对外仍叫 `/projects`，不改 HTTP 契约。
  4. `projects` 补 `status`（`active` / `archived`）与索引 `{tenant_id, user_id, status}`。
  5. 为每个 `tenant+user` 补一条 `_id = "default"` 的默认项目（幂等 upsert，仿 `ensure_root_department`）。
- P1（回填，D4）：遍历 `agent_kernel_bindings` 按 `source_workspace_id` 回填会话 `project_id`；无 workspace 的会话 → `"default"`。分批、可重入、带失败清单。
- P2（切读）：侧边栏按 `project_id` 分组（web 会话进默认项目，不再被 `filter(!code_project?.workspace_id)` 排除）→ 驾驶舱"空间"改"项目" → 配额（若启用）。
- 迁移期读侧兼容 `project_id or workspace_id or "default"`，避免空值落 `未分配`。

**自动归档（D7）落点**：客户端 `useUserBoundProjects`/`listDshWorkspaces` 对账时，若项目登记的 `workspace_id` 在本地注册表里找不到目录 → 调 `PATCH /projects/{id}` 置 `archived`；服务端只在 `status = active` 的项目上参与配额取小与侧边栏展示（归档项目折叠进"已归档"分组）。**不做定时扫描**——目录是否存在只有客户端知道，服务端扫描只会产生误判。

**文档同步**：`spec.md` / `plan.md` / `tasks.md` / `checklists/requirements.md` 已按"五段（租户/用户/部门/Agent/项目）+ 项目"同步改完（2026-10-30），细节见 §4.3 文档部分与 §4.4 改名清单。

**明确不做**：多人共享项目、跨用户会话共享、目录路径上云、配额能力扩展（单轮复检/项目层索引/新告警通道）。

### 7.2 042 可发现性与口径

**批次 A — 可发现性与入口（P0，纯前端 + 一处路由）**

> **2026-10-30 决策变更（D8）**：配置入口**独立成菜单**，不再往「流量分配」页面里塞一级 tab。并且**不出现"团队"概念**——042 的 `team` 层实际载体是部门树（`org_units`），产品语言应统一称"部门"，归组织管理；配额页只做项目。

| 编号 | 任务 | 验收 |
|---|---|---|
| A1 | admin-web 新增独立菜单「项目管理」（`/projects`），页面含：项目列表（只读，来自 user-web 创建）、按项目用量/成本视图、项目层配额（若启用）。**不设"团队"tab、不设"新建项目"按钮**（项目由员工在自己机器上选目录产生，管理端无法替人选目录） | 侧边栏可见独立入口；页面无"新建/编辑成员"；无"团队"字样 |
| A2 | 修深链：`?open=quota` 落到新页面的**项目配额**视图；新增 `?open=tenant` 落**租户额度**（原"企业额度"，按 §4.4 改名）；`ModelsPage` 按告警类型分流 | 从告警点"去配置"落在对应视图 |
| A3 | 项目空态引导：说明"项目在 user-web 里选本地目录创建"，给跳转链接 | 空态有可点击入口 |
| A4 | 驾驶舱补「配额异常」卡片，消费 `quotaAnomalies` | 有事件按 scope 分组展示；无事件显示 `reason` |
| A5 | 「流量分配」页面把原「团队 / 项目额度」弹窗入口改为跳转新菜单（保留**租户额度**弹窗，原"企业额度"） | 旧入口不再出现项目 tab；点击跳转新页面 |

**"团队"字样清理（随 A1 一起）**：`TrafficAllocationsPage.vue` 的「团队 / 项目额度」按钮、弹窗 tab 名、`quota_policy.py` 的 `TEAM_SCOPE` 文案、拒绝消息里的"团队"字样——**对外文案统一为"部门"**，`scope_type = 'team'` 的**存储值不改**（改枚举值要迁数据，收益为零）。这是命名收敛，不是删除部门层能力。

**批次 B — 口径（P1，后端）**

| 编号 | 任务 | 验收 |
|---|---|---|
| **B0** | **修 `points_unlimited` 默认值**：chat-api 补 `, True` | 无该字段的租户不再被 402 拦；不再白跑成员聚合 |
| B1 | 跨服务一致性测试：同 fixture 两端 `get_quota_summary` 逐字段相等 | 先跑出差异，修完转绿 |
| B2 | 统一 tz 语义（全 aware 或全 naive，二选一并写注释） | B1 转绿；既有配额测试全绿 |
| B4 | 网关补 `user_id`（仅计量旁路，见 §7.1） | 归集侧拿到 `user_id`；不传的调用方零影响 |
| ~~B3~~ / ~~B5~~ | 索引+memo / 孤儿策略巡检 → **降级 P2**（B0 修好后多数租户走短路） | 仅显式限额租户需要 |

**批次 C — 文档与验收（P2）**

| 编号 | 任务 |
|---|---|
| C1 | 补 T023：`node scripts/check_sfc.mjs apps/admin-web/src/views/organizations/TrafficAllocationsPage.vue` + 手工联调 |
| C2 | 在 042 spec 增加「实现落点索引」，列出代码落点与提交号（`93428a82` 含 042 实现） |
| C3 | 与 035 的双向声明：项目概念以本文件 §7.1 为准，042 不再维护独立的"项目分组"实体 |

**042 明确不做**：不新建推送通道；不把"按项目归属"做成配额约束（D5）；不抽 `quota_policy` 公共包（两份副本分属两个服务，用一致性测试锁死）；不改 `ANOMALY_STATUSES`（R-12）。

---

## 八、落地顺序（仅排序，暂不执行）

```
B0（一行）── 最先做，让"默认不限额"成立
P0 数据模型
  ├─ project_id 命名统一（TokenUsageRecord / analytics）
  ├─ desktop_projects → projects 改名 + status + 索引（D6/D7）
  ├─ 默认项目 "default" 幂等 upsert（D2）
  └─ chat_sessions.project_id 字段
       └─ P1 全量回填
            └─ P2 切读：侧边栏 → 驾驶舱（空间→项目）→ 配额
A1–A5（项目管理独立菜单 + 深链 + 空态 + 驾驶舱告警）── 与上面并行，纯前端 + 一处路由
业务线删除（§4.3 代码部分）── 与 A 批同批，纯删除
035 spec/tasks/checklists 同步 ── ✅ 已完成（2026-10-30）
```

依赖关系要注意两点：**P0 的集合改名（D6）必须先于 A1**（新菜单读的是 `projects`），**A5 依赖 A1**（旧入口跳转新页面）。业务线删除与 A 批无耦合，可任意顺序。

---

## 九、已确认决策（2026-10-30 17:55，cooper）

| # | 问题 | 决定 | 落到哪 |
|---|---|---|---|
| 1 | 默认项目 `project_id` 取值 | **固定 `"default"`**（不用 `default:<user_id>`） | §7.1 D2；`spec.md` R-6 |
| 2 | `desktop_projects` 是否改名 `projects` | **改**（集合名 + chat-api 路由 + user-web 客户端同步，一次性 `renameCollection`） | §7.1 D6 + 迁移 P0-3 |
| 3 | 目录消失后归档还是留中间态 | **自动归档**（`status = archived`），不引入 `missing-dir` | §7.1 D7 + 自动归档落点；§6 P2-2 |
| 4 | 团队/项目配置放哪 | **独立菜单**；且**没有团队概念、只有项目概念**——配额页只做项目，部门维度归组织管理，`team` 层对外文案统一改称"部门" | §7.1 D8；§7.2 A1/A5 + "团队"字样清理 |
| 5 | 业务线删除是否同步改 035 spec | **同步修改**（不是只在代码层删） | §4.3 文档部分 —— ✅ 已完成 |
| 6 | 「企业」维度是否保留 | **保留但改名「租户」**——"企业先实际和租户一个概念"（2026-10-30 17:59）；`enterpriseAttribution` → `tenantAttribution`，042 的「企业额度」同步改称「租户额度」 | §4.4；§7.2 A2/A5 |

**两个需要你留意的推断**（我按最小改动处理，若与本意不同请说）：

1. 第 4 条的"没有团队概念"我理解为**产品语言层面**：`scope_type = 'team'` 的存储值不改（改枚举要迁数据、收益为零），只把对外文案统一为"部门"，并把部门维度留在组织管理里。如果你的意思是**连部门层配额能力一起删**，那是删掉 042 四层中的一层，影响 `_scoped_layers` 取小逻辑，需要单独确认。
2. 第 3 条"自动归档"需要客户端上报（只有客户端知道目录还在不在），所以 D7 的落点在 user-web 的 `useUserBoundProjects` 对账逻辑，服务端不做定时扫描——否则外接盘未挂载会被误判成"目录已删"。

---

## 附：文档关系与修订记录

- 本文件是唯一正本。`Decisions/ADR-8-统一项目概念-项目即工作目录.md` 已降为决策记录（D0–D8 与指针）；`specs/042-three-level-quota/review-2026-10-30-remediation-plan.md` 为早期副本，均已标注"已合并"。
- 2026-10-30 修订：①合并三份文档；②业务线维度取消（§4）；③项目概念按"项目 = 工作目录"定案（§7.1）；④配额相关 P1 降级 P2（D5）。
- 2026-10-30 17:55 修订：§9 五个待确认项全部拍板 → 新增 D6（`projects` 改名）、D7（自动归档）、D8（独立菜单 + 去"团队"）；D2 固定 `"default"`；§4.3 拆成"代码未落地 / 文档已完成"两段；§6 P2-2 按自动归档收敛；§7.2 A 批重写为独立菜单方案并新增 A5。
- 2026-10-30 17:59 修订：**「企业」维度改名「租户」**（§4.4，维度保留）——§1 摘要与表格、§3 数据流、§7.2 A2/A5、§9 第 6 条同步更新；035 的 spec/plan/tasks/checklists 与 ADR-8 同步改名。
