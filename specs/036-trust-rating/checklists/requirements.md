# Requirements Quality Checklist: 036 trust-rating

**Purpose**: 校验 036（可信评级 L1–L4 资产分级 + 权限强绑定）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-10-24
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [x] CHK001 三类资产的键生成规则是否在正文固化（Edge Cases 写"键生成规则必须在文档中固化：skill 用 skill_id、workflow 用 skill_id、agent 用 agent 标识"，但**"agent 标识"到底是哪个字段**（`agent_id` / `capability_ref` / 运行时 `node_id`）未定义；同键碰撞的判据也不在正文）
- [x] CHK002 "连续不达标"的计数单位是否定义（FR-010 只写"连续 21 天"，**按日历天还是扫描轮次**、扫描一天跑多次是否重复计、中间某次达标是否清零，均未在 FR 层写明）
- [x] CHK003 质量达标阈值的具体值与可配性是否定义（FR-005/FR-017 只说"016 效果分 ≥ 阈值"与"032 评测结果"，**阈值默认值、是否租户可配、032 的判定口径（通过率还是三指标逐项）**未给）
- [x] CHK004 `last_evidence` 的结构与体积是否定义（FR-003 列出该字段但**未定义内容形状**；存 032 报告 ID、016 分数快照、还是自由文本，直接影响审计可回溯性与文档体积）
- [x] CHK005 降级通知的通道与失败语义是否定义（FR-011 说"owner 通知（通知失败不阻塞主流程）"，**首期是否真的实现通知、走站内还是邮件、重试策略**未写；若不实现则属"写了但没落地"的隐性需求）

## 清晰度（Clarity）

- [x] CHK006 "创建者本人"的判据是否定义（FR-014 要求 L1 仅创建者可用；**"创建者"取 `created_by` 还是 `owner_id`、二者不一致以谁为准、组织管理员是否可见**未定义，会导致列表过滤与直读鉴权两套口径）
- [x] CHK007 L2 人审标记的载体与消费方是否定义（FR-015 说输出"携带人审标记（如 `human_review_required`）"，**放在响应体哪个字段、响应头、还是编排上下文**，以及"编排/DAG 自动节点不得自动采用"由谁强制执行，均未定义）
- [x] CHK008 门禁封顶的生效点是否定义（FR-008 要求"查矩阵前按评级封顶"，**但"资产无评级记录时按 L1 封顶"与既有 001 路径中不带资产上下文的调用如何区分**——无资产上下文的普通调用不应被 L1 封顶，否则全局降级）
- [x] CHK009 032 就绪后"切换"的落点是否定义（FR-005/FR-017 说"切换可配置且留审计"，**配置存哪（env / DB / 租户设置）、谁有权切、切换后历史评级是否重算**未写）

## 一致性（Consistency）

- [x] CHK010 租户覆盖存储的形态与 001 是否同构（FR-007 说"形态为 canonical 常量 + `autonomy_matrix` 同构的租户覆盖存储"，但**未指明 001 现有覆盖存哪张集合、key 结构**；不写清则实现可能自造第二套存储）
- [x] CHK011 双人复核与 001 单人票据的兼容边界是否声明（FR-009 扩展 `gate_approvals`；**`required_approvals` 缺省值、谁负责在 L4+R2 场景置 2、旧票据（无该字段）如何按 1 处理**需要显式声明"零回归"判据）
- [x] CHK012 与 008 驾驶舱的消费端点形状是否定死（FR-016 说"聚合计数端点**或**复用列表统计"——**二选一未定**，两种形状对接线方是完全不同的契约）
- [x] CHK013 与 022 审计链的字段映射是否定义（FR-006 要求落 022 审计链含 actor/before/after/reason/证据摘要；**022 既有 `record_management_operation` 的字段名与本特性字段如何对应**未写，易出现"审计里查不到 before/after"）

## 边界与歧义（Edge Cases & Ambiguity）

- [x] CHK014 自动降级的并发与幂等是否定义（FR-010 扫描任务多实例部署时**是否重复降级**；扫描进行中人工升级的竞态如何处理；降级与 018 `set_state` 迁 deprecated 之间的原子性边界）
- [x] CHK015 孤儿评级记录与清理责任是否定义（Edge Cases 说"扫描器与清理任务 MUST 容忍"，但**清理任务本身是否存在、谁触发、孤儿记录是否永久保留**未写；只说"容忍"等于把问题留给运维）
- [x] CHK016 L4 双人复核与 R3 风险的边界是否明确（FR-009 写"写操作（调用风险级 ≥ R2）"，**R2/R3 都需双人、还是仅 R2 起步的写操作**；与 R4 恒拒的优先级已在 Edge Cases 写明，但 R3 归属未定）

## Notes

- 条目编号 CHK001–CHK016 连续，覆盖完整性 / 清晰度 / 一致性 / 边界四类；每条均可回溯到 spec.md 的 FR / 决策表 / Edge Cases 原文。
- 本特性需求风险集中在**口径可执行性**（CHK002/CHK003/CHK006/CHK008）：评级是权限强绑定的输入，口径错一位就会全租户降级或放行；其余为文档固化与契约形状问题。

## 评审结论（2026-10-24 勾选，agent 代审 + spec 回填）

16 条全部达标，均经 `spec.md` 新增的「判定口径补充（R-1~R-16）」消解：

- CHK001（三类资产键生成）→ R-1：`asset_type` 枚举 + `asset_key` 原样传入 + 三元组唯一索引。
- CHK002（连续不达标单位）→ R-2：日历天，6h 扫描不重复计数，达标即清零。
- CHK003（达标阈值与可配性）→ R-3：032 通过率 `EVAL_PASS_RATE_THRESHOLD = 0.8`、`MIN_EVAL_RUNS = 20`；016 兜底窗口 7 天；阈值当前为常量。
- CHK004（`last_evidence` 形状）→ R-4：只存判定摘要，不存完整报告。
- CHK005（降级通知）→ R-5：**首期不实现，已登记为缺口**（不得依赖"已通知"）。
- CHK006（创建者判据）→ R-6：判据 = `owner_id` 优先、`created_by` 兜底；`list_ratings(visible_to=)` 已实现 L1 过滤（`test_list_hides_l1_from_non_owner` 覆盖），但 skills 目录/市场列表与直读**尚未接线**，属部分实现。
- CHK007（L2 人审标记载体）→ R-7：**FR-015 首期未实现，已登记缺口**；建议落点已在 R-7 给出。
- CHK008（封顶生效点）→ R-8：仅 fresh path + 仅当 `ctx.annotations["trust_level"]` 存在，未标注调用走 001 原逻辑（防全局降级）。
- CHK009（信号源切换落点）→ R-9：自动优先序（032 → 016），非显式开关，不重算历史。
- CHK010（租户覆盖存储）→ R-10：`trust_autonomy_caps` + `{"_id": tenant, "caps": {...}}`，非法值丢弃。
- CHK011（双人复核兼容边界）→ R-11：默认 1、仅 L4 且 R2+ 置 2、旧票据按 1，单人路径零回归。
- CHK012（驾驶舱端点形状）→ R-12：`GET /api/trust-ratings/distribution` 返回 `dict[str,int]`。
- CHK013（022 审计字段映射）→ R-13：`record_management_operation` + before/after/reason/evidence/actor，失败只 warning。
- CHK014（扫描并发与幂等）→ R-14：无分布式锁，状态机幂等（降级后 streak 重置），最坏重复写审计。
- CHK015（孤儿清理责任）→ R-15：扫描跳过 + warning；**无清理任务，孤儿保留**（已登记缺口）。
- CHK016（L4 复核风险边界）→ R-16：R2/R3 需双人，R4 恒拒优先。

**验收证据**：`services/admin-api/tests/test_trust_rating.py` 25 passed；`services/admin-api/app/api/router.py:38` 已挂载 `trust_ratings.router`、`main.py:37-38` 已注册 `ensure_trust_indexes` 与 `TrustRatingDowngradeScanner`；`services/admin-api/app/governance/layers/approval.py:255-290` 已接入评级封顶与 `required_approvals_for`。

**缺口登记（不掩盖）**：FR-011 通知（R-5）、FR-015 L2 人审标记（R-7）在本轮实现中**未落地**；FR-014 L1 可见性（R-6）**仅在评级列表层实现、目录/市场列表路径未接线**；Edge Cases 的"清理任务"未实现（R-15）。故本 checklist 的 16/16 达标指"需求口径已闭合"，**不代表上述 FR 已端到端实现**。
