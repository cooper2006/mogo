# 042 三级配额 — 整改方案

> **已合并**：本文件内容已并入 `specs/035-cost-attribution/review-2026-10-30-dimension-source-audit.md`——现状核对见其 §5、问题清单见 §6（P0-1…P2-2）、整改方案见 §7.2、落地顺序见 §8（两个特性共用 `token_usage_logs` + `org_units` 同一数据底座，且 042 的 `quota_projects` 原为 035 空间维度的候选载体，现已按 ADR-8 收敛到「项目 = 工作目录」）。**后续修订以合并后的文档为准**，本文件保留作为历史副本，不再单独更新。

- 日期：2026-10-30
- 范围：只读核实 + 方案，**未修改任何代码**
- 一句话结论：**数据层与策略层是完整落地的**（四层策略、三层取小、fail-closed、告警事件、审计日志都在），缺口集中在「看得见」和「管得住」——入口不可发现、深链指错、告警无 UI、主力 Agent 流量在单轮内绕过配额、两份 `quota_policy` 已漂移。

---

## 一、现状核对（FR → 实现 → 结论）

| FR | 实现落点 | 结论 |
|---|---|---|
| FR-001 四层 `scope_type` | `user_quota_policies` 复用，`chat-api/core/quota_policy.py:28-29` 定义 `TEAM_SCOPE/PROJECT_SCOPE` | ✅ |
| FR-002 团队 = 部门树节点 | `_team_scope_ids` 查 `end_user_org_relations`（直接成员，无子树聚合） | ✅ |
| FR-003 项目 = 新建轻量实体 | 集合 `quota_projects`，`services/quota_projects.py`；`_id` 用 `uuid4().hex` 字符串（与 policy 的 `scope_id` 形态一致，匹配无坑） | ✅ |
| FR-004 分层取小 + `limitingScope` | `get_quota_summary` → `_scoped_layers` 层内取最严 → 层间 `min`（`quota_policy.py:459-470`） | ✅ |
| FR-005 超限拒绝并指明层 | `assert_quota_available` → `_layer_denial_message`，文案含团队/项目名 | ✅ |
| FR-006 未配置层视同 unlimited | `_layer_state` 无策略即返回 `None`，不参与取小 | ✅ |
| FR-007 多命中取最严 | `min(states, key=remaining)` | ✅ |
| **FR-008 管理端入口** | 有 UI，但入口是弹窗内二级 tab；`?open=quota` 打开的是**企业额度** | ⚠️ **偏差** |
| FR-009 审计日志 | `_upsert_scoped_policy` 动态拼 `setup_/update_ + team/project`，写 `user_token_allocation_logs` | ✅ |
| FR-010 超限/接近告警 + 去重 | `_emit_layer_alerts` → `quota_alert_events`，`alert_key` 含租户+层+周期 | ✅ 后端 |
| FR-011 不新建推送通道 | 复用驾驶舱口径 | ✅ 后端 |
| **FR-011 前端展示** | `/overview` 已返回 `quotaAnomalies`（`dashboard.py:967`），**admin-web 零引用** | ❌ **缺失** |
| FR-012 零策略时输出不变 / 001 门禁不动 | `governance/layers/quota.py` 无 diff，等价测试存在 | ✅ |

结论：**FR-008 有偏差、FR-011 只做了后端一半**，其余 FR 实现到位。

---

## 二、问题清单（按优先级）

### P0-1 驾驶舱没有配额告警展示（FR-011 前端半边）

- 证据：后端 `dashboard.py:967` 返回 `quotaAnomalies`；`summarize_quota_alerts`（`dashboard_metrics.py:347`）已按 `exceeded / approaching / layer_unreadable` 三类聚合，并带 `available` / `reason` / `byScope` / `items`。
- 反证：`apps/admin-web/src` 全仓搜 `quotaAnomalies` **命中 0 处**。`DashboardPage.vue:265` 的 `anomaly-list` 只渲染 `qualityAnomalies`。
- 影响：管理员看不到"哪个层、哪个部门/项目、什么时候超限或接近阈值"。042 的告警能力对用户完全不可见，等于没做。
- 修法：`DashboardPage.vue` 在质量异常旁新增"配额异常"卡片，消费 `quotaAnomalies`：`total > 0` 时按 `byScope`（team/project/org/user）分组列出 `items`（层名 + kind + ratio + 时间）；`available === false` 时显示 `reason`，不渲染 0。

### P0-2 产品内唯一深链指向错误弹窗（FR-008 偏差）

- 证据：`TrafficAllocationsPage.vue:598-604` 的 `consumeOpenQuotaQuery()` 判断 `route.query.open === 'quota'` 后调用的是 `openSettings()`，打开「额度设置」（企业总额度）弹窗，而不是 `openScopes()`（团队/项目）。
- 唯一的入口方：`ModelsPage.vue:27` 与 `:766`（额度告警提示里的"去配置"）都指向 `/organizations/traffic?open=quota`。
- 影响：用户顺着告警点"去配置"，落到企业额度，**永远看不到项目配置**。这是"功能存在但没人能到达"的直接原因之一。
- 修法：`?open=quota` 改为打开团队/项目弹窗（`openScopes()`）并默认落 `team` tab；企业额度改用 `?open=enterprise`；`ModelsPage` 的链接按告警类型分流。

### P0-3 项目/团队配置的入口层级过低，且无空态引导

- 证据：入口是 `TrafficAllocationsPage.vue:25` 筛选栏里一个 `secondary` 按钮「团队 / 项目额度」→ 弹窗（`:175`）→ 第二个 tab「项目额度」（`:215`）。三级点击，菜单名"流量分配"与"项目"无语义关联。
- 空态：`quota_projects` 无种子数据，`:263` 只显示一行「暂无项目分组」。
- 提交信息：唯一引入 `createQuotaProject` 的提交是 `93428a82 feat(032-033-034): 落地评测门禁 eval-gate、canary 灰度与工具凭证加密` —— 与 042 无关，`git log --grep=042` 搜不到任何实现提交。
- 影响：按 spec 号追溯会得出"没落地"的结论（本次核实就是这样被触发的）。
- 修法：见批次 A1/A3。

### P1-1 主力 Agent 流量在单轮内绕过配额

- 证据链：
  - 每调用一次配额校验的条件是 `output_spec.user_id` 存在：`chat-api/app/llm/configured_models.py:391-401`。
  - DSH 网关的 `output_spec` **显式不含 `user_id`**：`dsh_runtime/model_gateway/service.py:176-190`（注释："不含 user_id 以跳过配额检查"）；令牌 claims 只有 `tenant_id / profile_version / model_instance_id`（`model_gateway/token.py:15-21`）。
  - DSH 侧只在**会话建立**（`dsh_chat.py:172`、`:279`）校验一次。
- 影响：一轮 Agent 会话内几十次 LLM 调用全部不校验。项目额度 1000 tokens、单轮烧掉 5 万 tokens 也能通过——`fail-closed` 语义在主力链路上被削弱为"每轮开头检查一次"。
- 修法（需拍板频率）：网关 claims 增加 `user_id`（或独立的 `metering_user_id` 旁路字段，避免触发 `configured_models` 里既有的配额短路），并在网关侧按"每 N 次调用"或"累计 token 增量"复检一次。**注意**：直接把 `user_id` 塞进 `output_spec` 会让每次调用都跑完整三层聚合（见 P1-3），必须先解决性能再打开。

### P1-2 两份 `quota_policy` 已漂移

- 证据：`chat-api/app/core/quota_policy.py` 536 行 vs `admin-api/app/core/quota_policy.py` 501 行，`diff` 显示实质差异，包括：
  - 时间基准：chat-api `datetime.now(timezone.utc).replace(tzinfo=None)`（naive），admin-api `datetime.now(timezone.utc)`（aware）；
  - `ensure_default_user_policy` 里 admin-api 多一个 `"unlimited": True` 默认值；
  - `_org_policy` 的 dual-write 写法不同。
- 影响：同一周期窗口在两端可能算出不同 `used`（naive/aware 与 Mongo 存储值比较时行为不同），驾驶舱显示的"已用/剩余"与用户端 402 判定可能不一致。这是口径漂移，不是必然 bug，但无法排除。
- 修法：先加一条**跨服务一致性测试**（同一 fixture 两端 `get_quota_summary` 输出逐字段相等），再把 tz 语义统一到 aware；短期不抽公共包（涉及部署边界），用测试锁死。

### P1-3 `quota_projects` 无索引 + 每次调用做成员聚合

- 证据：`services/quota_projects.py` 无任何 `create_index`；`_project_scope_ids` 按 `member_user_ids: user_id`（数组包含）查询；`_layer_state` 每次 `sum_usage(user_ids=members)` 做一次 `token_usage_logs` 聚合（`quota_policy.py:148-168`）。
- 影响：`assert_quota_available` 在每次 LLM 调用触发（P1-1 修好后就是"每次调用"而不是"每轮"）→ 每个命中项目/团队策略的用户，每次调用都要扫 `quota_projects` + 对成员列表做一次聚合。成员数上千时这是明显的调用延迟来源。
- 修法：`(tenant_id, status)` 与 `(tenant_id, member_user_ids)` 索引；同一请求内对 `_layer_state` 结果做 memo（`contextvars` 或请求级缓存，TTL 数秒）；必要时把 `sum_usage` 改为按 `(tenant_id, user_id)` 预聚合。

### P2-1 T023 未验收

`specs/042-three-level-quota/tasks.md:48` 的 T023（`@vue/compiler-sfc` 编译 + 手工联调）**未勾选**。这条 UI 从提交到现在没有被端到端验证过，P0-2 的深链错误正是"没联调"的产物。

### P2-2 项目软删后策略成孤儿（预期，但无巡检）

`quota_projects.py:173-184` 软删（`status="deleted"`），策略行保留（docstring 明确"孤儿策略是预期状态"）。`_project_scope_ids` 只取 active，所以不会误命中；但 `user_quota_policies` 里会永久残留 `scope_id` 指向已删项目的行，`/projects` 列表不展示 → 管理端无法发现和清理。建议至少加一条测试固化"孤儿不生效"，并在 `/teams`、`/projects` 列表响应里带一个 `orphanPolicyCount` 供运维判断。

---

## 三、整改任务（三批）

### 批次 A — 可发现性（P0，纯前端，1–1.5 天）

| 编号 | 任务 | 文件 | 验收 |
|---|---|---|---|
| A1 | 把「团队额度 / 项目分组」从弹窗二级 tab 提升为页面内一级 tab（或独立菜单项「配额与分组」） | `TrafficAllocationsPage.vue`（`:175-277` 结构调整）；如需新菜单则改 `router/routes.ts` | 进入页面即可看到三个 tab，项目分组不需要点按钮 |
| A2 | 修深链：`?open=quota` → 团队/项目；新增 `?open=enterprise` → 企业额度；`ModelsPage` 按告警类型分流 | `TrafficAllocationsPage.vue:598-604`、`ModelsPage.vue:27/766` | 从告警点"去配置"落在对应 tab；URL 回退到不带 query |
| A3 | 项目空态引导：说明"跨部门协作分组、与桌面 Code 项目无关"，并给新建入口 | `TrafficAllocationsPage.vue:263` | 空态不再是一行灰字，有可点击的"新建项目" |
| A4 | 驾驶舱补「配额异常」卡片，消费 `quotaAnomalies` | `DashboardPage.vue`（`qualityAnomalies` 旁） | 有事件时按 scope 分组展示；无事件显示 `reason`，不渲染 0 |

### 批次 B — 口径与性能（P1，后端，2–3 天）

| 编号 | 任务 | 文件 | 验收 |
|---|---|---|---|
| B1 | 跨服务一致性测试：同 fixture 下 chat-api 与 admin-api 的 `get_quota_summary` 逐字段相等 | 两个 `tests/test_quota_three_level.py` | 测试先跑出当前差异（预期 tz 相关字段不等），修完转绿 |
| B2 | 统一 tz 语义到 aware（或全部 naive，二选一并写进注释） | 两份 `core/quota_policy.py` | B1 转绿；既有配额测试全绿 |
| B3 | `quota_projects` 补索引；`_layer_state` 加请求级 memo | `quota_projects.py`（新增 `ensure_indexes`）、`quota_policy.py` | 单次 `assert_quota_available` 的 DB 往返次数下降；压测无回归 |
| B4 | 网关补 `user_id`（旁路字段）+ 单轮内复检策略 | `model_gateway/token.py`、`model_gateway/service.py`、`configured_models.py` | 单轮多调用场景下项目额度被正确拦截；不传 user_id 的既有调用方零影响 |
| B5 | 孤儿策略巡检字段 | `traffic_allocations.py` 的 `/teams`、`/projects` | 列表响应带 `orphanPolicyCount`；有测试固化"孤儿不参与取小" |

### 批次 C — 文档与验收（P2，0.5 天）

| 编号 | 任务 | 验收 |
|---|---|---|
| C1 | 补 T023：`node scripts/check_sfc.mjs apps/admin-web/src/views/organizations/TrafficAllocationsPage.vue` + 手工联调（新建项目 → 配额度 → 成员对话超限 → 移除成员恢复 → 驾驶舱出现配额异常） | tasks.md T023 勾选，附联调结论 |
| C2 | 在 `specs/042-three-level-quota/` 增加「实现落点索引」小节：把 042 的代码落点与提交号列出（`93428a82` 里含 042 实现），避免后续按 spec 号检索扑空 | 新人按 042 检索能一次命中 |
| C3 | 与 035 的双向声明：035 的「空间」维度若选 D2 方案（复用 `quota_projects` 做分摊视图），需在 042 spec 里写明"项目分组同时是 035 空间维的候选数据源" | 两份 spec 互相引用 |

---

## 四、明确不做

- **不新建推送通道**（FR-011 已定）。
- **不把项目层改成"按项目归属单次调用"**：`token_usage_logs` 里没有 project 维度，042 的用量口径是"当前成员用量之和"。若要做"按项目归属"（035 的空间维度需要），那是 035 的议题，且一人可属多项目会导致成本重复计数、`reconciles` 破坏 —— 只能做分摊视图，不能与 `totalCost` 对账。
- **不抽 `quota_policy` 公共包**：两份副本分属两个服务、部署边界不同，短期用一致性测试锁死比抽包风险低。
- **不改 `ANOMALY_STATUSES`**（R-12 已定：它过滤 `token_usage_logs.status`，塞 quota 值永不命中）。

---

## 五、依赖与顺序

```
A1/A2/A3（前端可发现性）  ──┐
A4（驾驶舱告警卡片）       ──┼──> C1 联调验收
B1/B2（口径一致）         ──┤
B3（索引+缓存）           ──┴──> B4（网关补 user_id，必须先有 B3 否则每次调用变慢）
B5（孤儿巡检） 独立
```

B4 是唯一有外部依赖的改动（要动 DSH 协议与令牌签发），建议单独立项、单独灰度；A 批可以先上，用户立刻能看见项目配置和配额告警。

---

## 六、需要拍板

1. **团队/项目配置放哪**：页面内一级 tab（改动小、和现有页一致），还是独立菜单「配额与分组」（更易发现，但多一个页面）？
2. **单轮内配额复检频率**：每轮一次（现状）/ 每 N 次 LLM 调用 / 按累计 token 增量阈值触发？后者最准但要网关侧维护计数器。
3. **`quota_policy` 两份副本怎么收**：保留双份 + 一致性测试（推荐，短期），还是抽公共包（要解决两个服务的部署边界）？
4. **035 的空间维度是否复用 `quota_projects`**：如果复用，042 这边要提前加"成员集合投影"的只读接口；如果不用，两件事互不影响。
