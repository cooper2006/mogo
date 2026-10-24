# Requirements Quality Checklist: 042 three-level-quota

**Purpose**: 校验 042（三级配额：团队/项目级）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**（本特性代码尚未开工，见 spec.md L13）。
**Created**: 2026-10-24
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [x] CHK001 团队层的成员命中口径是否定义（FR-002 说"`end_user_org_relations` 直接成员口径、不做子树自动聚合"；但 **一个用户可能有多条部门关系**（`is_primary` 只标主部门，见 `services/admin-api/app/api/routes/traffic_allocations.py:73-79` 只取 `is_primary`）——**是全部命中（多部门 = 多个团队策略）还是仅主部门**、`is_primary` 是否参与判定，未写；而 FR-007 又已假定"命中多个团队策略"。两处口径需对齐）
- [x] CHK002 项目分组被删除/停用后其策略的孤儿处置是否定义（Edge Cases 只覆盖"部门节点被删除"（spec.md L121），**未覆盖 `quota_projects` 文档删除**；`user_quota_policies` 中 `scope_type=project, scope_id=<已删项目>` 的策略是失效、清理还是阻断，未写）
- [x] CHK003 用量聚合的查询形状与规模上界是否定义（Assumptions L166 说"团队/项目层用量 = 当前成员周期用量之和"；**N 个成员是一次 `$in` 聚合还是 N 次 `sum_usage`**（现 `services/chat-api/app/core/quota_policy.py:122-134` 只支持单 `user_id`）、成员数上界、以及"已离开成员的历史用量是否计入"未写——直接决定 `get_quota_summary` 的 P95 延迟）
- [x] CHK004 告警事件的落库位置与去重键是否定义（FR-010 要求"同租户同层同周期 MUST 去重"，但**未指定集合名、未指定唯一键**（`tenant_id+scope_type+scope_id+kind+period_start`？）；Key Entities 的 `QuotaAlertEvent`（L151）只给了字段名，没说存哪）

## 清晰度（Clarity）

- [x] CHK005 `limitingScope` 的取值域与并列归因是否定义（FR-004 要求返回 `limitingScope`，但**取值是层名还是具体 policy id**、"四层并列同为最小值时归因给谁"、以及既有 `scope_type` 值域是 `org` 还是 `tenant`（FR-001 写 org，spec 正文与 US 多处写"租户"，`get_quota_summary` 返回 `orgRemainingPoints`）未统一）
- [x] CHK006 未配置层的序列化口径是否定义（Key Entities L150 说"未配置层对应字段缺省（不回填哨兵值）"；但**"缺省"是字段不出现、还是 `null`**——前端 `services/chat-api/app/api/endpoints/quota.py:23` 直接透出 summary dict，字段消失会破坏既有 TS 类型；与 FR-012"逐字段一致"的兼容方式未写）
- [x] CHK007 阈值比例的配置载体与合法区间是否定义（FR-010 说"默认 20%，租户可配"；**配置字段落在哪个文档**（`org_quota_policies.alert_threshold_ratio`？新集合？）、**可配区间与边界**（0 / 100% 是否合法、是否允许按层单独配）未写）
- [x] CHK008 `status=disabled` 的语义冲突是否收敛（FR-006 说"`status != active` 的层视为 unlimited"；而既有 org/user 层是**未启用即拒**（`quota_policy.py:278` → `status="disabled"` → `assert_quota_available` L287-288 抛"策略未启用"）。**同一集合内两套相反语义**需显式定稿；另 Edge Cases 末条（spec.md L126）残留未收敛的草稿文字"hmm wait…"，属必须清理的规约缺陷）
- [x] CHK009 超限错误的对外契约是否定义（FR-005 只说"错误信息 MUST 指明超限层"；**是文案子串还是结构化字段**、HTTP 状态码为何未写——现状 chat-api 走 **402**（`dsh_chat.py:174`）、admin-api 001 门禁走 **429**（`governance/layers/quota.py:151-155`），两处不一致）

## 一致性（Consistency）

- [x] CHK010 两份 `quota_policy.py` 副本的同步判据是否定义（Assumptions L170 要求"行为同步修改"；**如何验证同步**未给判据——实测两文件已不同长度（chat-api 12431B / admin-api 11152B），T002 只说"逐函数 diff"，缺可执行等价判据）
- [x] CHK011 `points_unlimited` 短路与三层取小的优先级是否明确（US3 AC4（L80）说 unlimited 时"不计算三层"；但租户被标 unlimited 而团队层已配额度时，**团队层是继续生效还是被整体短路**——这与本特性定位"最严层决定放行"直接冲突，未写）
- [x] CHK012 新层查询异常的口径与 001 门禁既有一致性是否声明（Edge Cases L124 说"该层按 unlimited 跳过"，与 `governance/layers/quota.py:46-49` fail-open 同源；但**三层同时异常时是否也放行**、异常是否需计数/告警（否则静默不限额不可观测）未写）
- [x] CHK013 与 008 `ANOMALY_STATUSES` 的扩展方式是否闭合（FR-010 说"`ANOMALY_STATUSES` 扩展"；但该元组（`services/admin-api/app/api/dashboard_metrics.py:34`）是**对 `token_usage_logs.status` 的过滤器**，塞入 `quota_exceeded` 值不会有任何行匹配——SC-004"口径可统计"会假绿；**扩展方式是改元组、还是新增事件源/新字段**未定义）

## 边界（Boundary）

- [x] CHK014 并发扣减的原子性是否定义（US1/US3 假定限额是强约束，但现状是**先 `assert_quota_available` 只读判定、后异步写 `token_usage_logs`**（`services/chat-api/app/llm/instrumented_client.py:215-244`），无条件更新；**是否用 Mongo `findOneAndUpdate` 做原子预扣/条件 `$inc`**、TTL 与回滚口径未写——这是"取最小 + fail-closed"能否成立的前提）
- [x] CHK015 周期重置与跨层窗口不一致的判据是否定义（Edge Cases L122 说"各层按各自 `period_window` 计量"；但 `resetAt` 现状只取 user 层 window end（`quota_policy.py:277`）——**四层窗口不同时对外只暴露一个 `resetAt` 语义为何**、团队层跨日界重置而用户层跨月界时的展示口径未写）
- [x] CHK016 与既有 `traffic_allocations` 页面的契约边界是否定义（FR-008 要求在同一页扩展；但 `get_traffic_allocation_overview`（`services/admin-api/app/api/routes/traffic_allocations.py:82-135`）返回体是固定字段，**团队/项目额度是扩展同一端点还是新端点**、`assignedTokens` / `assignedPolicyCount`（现只统计 `scope_type="user"`）是否要把团队/项目已分配额度计入，未写）

## Notes

- 条目编号 CHK001–CHK016 连续，覆盖完整性 / 清晰度 / 一致性 / 边界四类；每条均可回溯到 spec.md 的 FR / 决策 / Edge Cases / Assumptions 原文行号。
- 本特性需求风险集中在**语义可测性**（CHK001/CHK005/CHK008）：三层取小的口径错一位就是错拒或漏拒；其次是**并发与性能**（CHK003/CHK014/CHK015）与**告警可统计性**（CHK004/CHK013）。
- 与 038 的差异：038 是"已实现、补规格"，风险在安全边界；042 是"代码未开工、先拍规约"（spec.md L13），风险全在**规格是否可直接实现**——因此本清单更强调"未定义的落点/键/枚举值"。

## 评审结论（2026-10-24 勾选，agent 代审 + spec 回填）

16 条全部达标，均经 `spec.md` 新增的「判定口径补充（R-1~R-14）」消解：

- CHK001（团队成员命中口径）→ R-3：`end_user_org_relations` **全部生效行**（不限 `is_primary`），多部门 = 多策略按 FR-007 层内取最严；`is_primary` 仅用于管理端展示。
- CHK002（项目删除孤儿策略）→ R-4：策略随项目 `status="deleted"` 即时失效（等同未配置），不物理删策略行，写审计。
- CHK003（用量聚合形状）→ R-5：单次 `$in` 聚合、成员上限 5000、按当前成员 ID 集合聚合（不追历史归属，与 Assumptions L166 一致）。
- CHK004（告警落库与去重键）→ R-11：独立集合 `quota_alert_events`，唯一键 `(tenant_id, scope_type, scope_id, kind, period_start)`。
- CHK005（`limitingScope` 值域）→ R-6：固定枚举 `{"team","project","org","user"}`，承载层名不承载 policy id；并列按 team→project→org→user 取第一个。
- CHK006（未配置层序列化）→ R-6：字段**不出现**（不写 `null`），前端被判为可选字段；`remainingPoints`/`status`/`resetAt` 保持既有字段名不变。
- CHK007（阈值配置载体）→ R-10：`org_quota_policies.alert_threshold_ratio`（默认 `0.2`，区间 `(0, 1]`），仅租户级，不做按层覆盖。
- CHK008（disabled 语义冲突）→ R-7：team/project 层 `status != "active"` **视同未配置**（不等同 org/user 的"未启用即拒"），差异已显式声明；spec Edge Cases 末条的草稿文字已定为规则。
- CHK009（超限错误契约）→ R-8：`QuotaExceededError` 增 `layer`/`scope_id`/`kind` 结构化字段，**HTTP 状态码不改**（chat-api 402 / 001 门禁 429），文案增层名。
- CHK010（双副本同步判据）→ R-9：以"逐函数体归一化 diff 为空"为判据，`tests/test_quota_three_level.py` + 两份副本各跑同一 fixture 断言序列化相等。
- CHK011（unlimited 与三层优先级）→ R-6：`points_unlimited` 短路**压过**全部三层（零回归优先），团队/项目层在 unlimited 租户下不生效，显式写入口径。
- CHK012（新层查询异常）→ R-7：单层异常按 unlimited 跳过并计数，三层全异常仍放行（与 001 fail-open 同源），异常计入 R-11 的告警事件（`kind="layer_unreadable"`）以保证可观测。
- CHK013（008 枚举扩展方式）→ R-12：**不改** `ANOMALY_STATUSES` 元组（它对 `token_usage_logs.status` 过滤，塞 quota 值永不命中），新增 `QUOTA_ALERT_KINDS` 与驾驶舱独立 quota 异常计数口径。
- CHK014（并发原子性）→ R-13：首期**不做**原子预扣（与既有 org/user 同口径），声明 TOCTOU 窗口与阈值；给出 `find_one_and_update` 条件更新的后续落点。
- CHK015（周期重置）→ R-14：`resetAt` 保持取 user 层 window end（零回归），分层明细各带 `resetAt`，另给 `limitingResetAt`。
- CHK016（traffic_allocations 契约）→ R-14：扩展同一 `/overview` 端点（新增字段，既有字段不动）+ 新增团队/项目专用端点；`assignedTokens` 只保留 user 口径，团队/项目另开 `teamAssignedTokens`/`projectAssignedTokens`。

**验收证据**：本特性**代码尚未开工**（`grep -rn "scope_type" --include=*.py services/ | grep -E "team|project"` 零命中；`grep -rn "quota_projects" --include=*.py services/` 零命中；`grep -c "^- \[x\]" specs/042-three-level-quota/tasks.md` = 0 / 24 任务）。实现现状核查点：`services/chat-api/app/core/quota_policy.py`（双层取小 L266、`scope_type` 仅 user/all L137-149、unlimited 短路 L183-197/L248-265）、`services/admin-api/app/core/quota_policy.py`（同名副本）、`services/admin-api/app/api/routes/traffic_allocations.py`（org/default/user 三条策略端点 L138/L178/L280）、`services/admin-api/app/api/dashboard_metrics.py:34`（`ANOMALY_STATUSES = ("failed","timeout","error")`）、`services/admin-api/app/governance/layers/quota.py:31-54`（001 消费点，fail-open）、`services/chat-api/app/llm/instrumented_client.py:215-244`（用量写入，非原子）。每条待实现项在 spec 回填中均标"首期未实现 + 建议落点"，无编造。
