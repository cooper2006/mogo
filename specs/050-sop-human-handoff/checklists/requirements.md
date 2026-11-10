# Requirements Quality Checklist: 050 sop-human-handoff

**Purpose**: 校验 050（SOP 转人工节点）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-11-09
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 语义生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [ ] CHK001 `human_approval` 节点 payload 的**完整 schema** 是否定义（FR-001 列 approver/timeout/on_reject/prompt 四键，但 approver 的取值形态（用户 ID？岗位角色 ID？二者如何区分）、必填/可选性、非法值行为未给出，加载期无法校验）
- [ ] CHK002 **票据 TTL 与长时挂起的匹配**是否定义（决策 #1 复用 `ApprovalRuntime.issue`，但该机制现行为短 TTL 一次性票据；审批可能挂起 24h+，票据过期后的决策路径未写——tasks T003 已登记核实，spec 层口径缺失）
- [ ] CHK003 **RunCheckpoint 的上下文增量结构**是否定义（FR-004 要求"已完成节点不重复执行"，共享上下文如何从 checkpoint 重建、增量与全量的取舍、大上下文的尺寸上限未给）
- [ ] CHK004 **待办的可见性与数据面**是否定义（FR-007 说"站内审批入口"，ApprovalTodo 由哪个 API 暴露、审批人如何看到跨运行的待办列表、与既有审批页的关系未写）
- [ ] CHK005 OQ-1~OQ-4 四个待澄清项是否全部消解并回填（超时默认值、IM 推送边界、needs_review 处置、保留期——clarify 门禁未过不得 implement）

## 清晰度（Clarity）

- [ ] CHK006 "应答式触达"的**触发语义**是否明确（决策 #5：审批人下次与 bot 交互时提示待办——若审批人从不与 bot 交互，待办是否永远沉默？站内入口是否为唯一可靠触达需明示）
- [ ] CHK007 运行状态机 `needs_review` 的**进入/退出条件**是否完整（US2-3 崩溃无幂等声明进入、Edge Case 审批人离职进入；退出路径（管理员重跑/跳过/改派）仅 OQ-3 提及，未定值）
- [ ] CHK008 "单活租约"的**租约粒度与失效判定**是否定义（FR-005 禁止并发恢复；租约 TTL、持有者崩溃后的接管时机、与恢复扫描周期的关系未给）
- [ ] CHK009 驳回"附理由"的**强制性与长度约束**是否定义（FR-003 要求附理由；空理由是否拒绝、理由最大长度、进审计的脱敏口径未写）

## 一致性（Consistency）

- [ ] CHK010 **节点类型 vs 文档模式**的落点是否与 044 先例一致（plan 声明不改 VALID_MODES、审批是节点类型；但 loader 现有节点级 `mode` 字段语义是 round_robin/debate——审批节点用 payload 键还是 mode 值需与 044 R-17/R-18 口径对齐，避免两套节点类型机制）
- [ ] CHK011 契约文档落点是否核对（FR-010 指向 010 目录 `contracts/orchestration.md`——该文件由 044 T025 新建，实际存在性与当前六模式内容需核实后增补，不得假设不存在）
- [ ] CHK012 审计出口是否与 001/044 口径一致（FR-008 事件进 001 审计流；事件命名（`dag.*` 还是 `run.*`）、与 044 R-9 的 payload 内嵌明细口径是否同构未写）
- [ ] CHK013 双后端兼容声明是否可执行（FR-011 要求经 027 门面；新集合 `orchestration_runs`/`approval_todos` 是否需 R3 关系扁平化登记、PanWeiDB 侧建表流程未写）

## 边界与歧义（Edge Cases & Ambiguity）

- [ ] CHK014 **并行分支多审批节点**的运行级状态与决策冲突是否覆盖（Edge Cases 提及各分支独立挂起；两分支同时驳回、一批准一驳回时运行终态如何判定未写）
- [ ] CHK015 **挂起运行取消**与在途决策的竞态是否覆盖（管理员取消瞬间审批人提交批准——票据作废与决策消费的先后序、幂等结果未写）
- [ ] CHK016 **超时判定与批准决策的竞态**是否覆盖（恢复扫描判定超时的同一时刻审批人批准——以谁为准、是否允许"超时后宽限"未写，fail-closed 口径需要确定性判定序）

## Notes

- 本 checklist 生成于 spec 首版（2026-11-09），全部未勾待 `/speckit-checklist` 代审；代审达标后回填 spec「判定口径补充」节（044 先例 R-1…R-N 逐条对应 CHK）。
- OQ 类缺口（CHK005）与口径类缺口分开处理：前者走 `/speckit-clarify`，后者走代审回填。