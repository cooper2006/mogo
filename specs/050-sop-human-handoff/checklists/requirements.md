# Requirements Quality Checklist: 050 sop-human-handoff

**Purpose**: 校验 050（SOP 转人工节点）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-11-09
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 语义生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [x] CHK001 `human_approval` 节点 payload 的**完整 schema** 是否定义（FR-001 列 approver/timeout/on_reject/prompt 四键，但 approver 的取值形态（用户 ID？岗位角色 ID？二者如何区分）、必填/可选性、非法值行为未给出，加载期无法校验）
- [x] CHK002 **票据 TTL 与长时挂起的匹配**是否定义（决策 #1 复用 `ApprovalRuntime.issue`，但该机制现行为短 TTL 一次性票据；审批可能挂起 24h+，票据过期后的决策路径未写——tasks T003 已登记核实，spec 层口径缺失）
- [x] CHK003 **RunCheckpoint 的上下文增量结构**是否定义（FR-004 要求"已完成节点不重复执行"，共享上下文如何从 checkpoint 重建、增量与全量的取舍、大上下文的尺寸上限未给）
- [x] CHK004 **待办的可见性与数据面**是否定义（FR-007 说"站内审批入口"，ApprovalTodo 由哪个 API 暴露、审批人如何看到跨运行的待办列表、与既有审批页的关系未写）
- [x] CHK005 OQ-1~OQ-4 四个待澄清项是否全部消解并回填（超时默认值、IM 推送边界、needs_review 处置、保留期——clarify 门禁未过不得 implement）

## 清晰度（Clarity）

- [x] CHK006 "应答式触达"的**触发语义**是否明确（决策 #5：审批人下次与 bot 交互时提示待办——若审批人从不与 bot 交互，待办是否永远沉默？站内入口是否为唯一可靠触达需明示）
- [x] CHK007 运行状态机 `needs_review` 的**进入/退出条件**是否完整（US2-3 崩溃无幂等声明进入、Edge Case 审批人离职进入；退出路径（管理员重跑/跳过/改派）仅 OQ-3 提及，未定值）
- [x] CHK008 "单活租约"的**租约粒度与失效判定**是否定义（FR-005 禁止并发恢复；租约 TTL、持有者崩溃后的接管时机、与恢复扫描周期的关系未给）
- [x] CHK009 驳回"附理由"的**强制性与长度约束**是否定义（FR-003 要求附理由；空理由是否拒绝、理由最大长度、进审计的脱敏口径未写）

## 一致性（Consistency）

- [x] CHK010 **节点类型 vs 文档模式**的落点是否与 044 先例一致（plan 声明不改 VALID_MODES、审批是节点类型；但 loader 现有节点级 `mode` 字段语义是 round_robin/debate——审批节点用 payload 键还是 mode 值需与 044 R-17/R-18 口径对齐，避免两套节点类型机制）
- [x] CHK011 契约文档落点是否核对（FR-010 指向 010 目录 `contracts/orchestration.md`——该文件由 044 T025 新建，实际存在性与当前六模式内容需核实后增补，不得假设不存在）
- [x] CHK012 审计出口是否与 001/044 口径一致（FR-008 事件进 001 审计流；事件命名（`dag.*` 还是 `run.*`）、与 044 R-9 的 payload 内嵌明细口径是否同构未写）
- [x] CHK013 双后端兼容声明是否可执行（FR-011 要求经 027 门面；新集合 `orchestration_runs`/`approval_todos` 是否需 R3 关系扁平化登记、PanWeiDB 侧建表流程未写）

## 边界与歧义（Edge Cases & Ambiguity）

- [x] CHK014 **并行分支多审批节点**的运行级状态与决策冲突是否覆盖（Edge Cases 提及各分支独立挂起；两分支同时驳回、一批准一驳回时运行终态如何判定未写）
- [x] CHK015 **挂起运行取消**与在途决策的竞态是否覆盖（管理员取消瞬间审批人提交批准——票据作废与决策消费的先后序、幂等结果未写）
- [x] CHK016 **超时判定与批准决策的竞态**是否覆盖（恢复扫描判定超时的同一时刻审批人批准——以谁为准、是否允许"超时后宽限"未写，fail-closed 口径需要确定性判定序）

## Notes

- 本 checklist 生成于 spec 首版（2026-11-09），全部未勾待 `/speckit-checklist` 代审；代审达标后回填 spec「判定口径补充」节（044 先例 R-1…R-N 逐条对应 CHK）。
- OQ 类缺口（CHK005）与口径类缺口分开处理：前者走 `/speckit-clarify`，后者走代审回填。

## 评审结论（2026-11-10 勾选，agent 代审 + spec 回填）

**原生达标（1 项，无需改 spec）**
- CHK005：spec「待澄清（clarify 门禁）」节已有「消解记录（2026-11-09 实现期，T002）」，四问均已定值回填——OQ-1（`timeout` 默认 `86400`、钳制 60s..30d）、OQ-2（全部回落应答式触达、站内 `/api/v1/orchestration-runs/todos`）、OQ-3（首期交付 `POST /runs/{id}/review` 的 skip/terminate）、OQ-4（终态快照保留 180 天、可经 `ORCHESTRATION_RUN_RETENTION_DAYS` 调整），且 tasks T002 已 `[x]`。clarify 门禁已过，需求质量达标。

**spec 回填后达标（15 项，回填见 [spec.md](../spec.md#判定口径补充2026-11-10speckit-checklist-回填) 的 R-1~R-15；CHK005 无对应 R 条）**
- CHK001 → R-1：`type`/`approver`/`timeout`/`on_reject`/`prompt` 完整 schema 定死，含必填性、取值形态委托 006、钳制区间、加载期 fail-closed 分支、审批人无效的两时点处置。
- CHK002 → R-2：两段式票据定死（挂起只存长效待办、决策瞬间签发 300s 票据并即时消费），消解决策 #1「挂起时 issue」与 24h 挂起的矛盾，明确过期/重复消费/自审分支。
- CHK003 → R-3：Key Entities「上下文增量」精确化为全量快照 + `revision`，定 1 MiB 上限与超限 fail-closed、零重跑依据。
- CHK004 → R-4：待办 API `/api/v1/orchestration-runs/todos` 的过滤维度、字段枚举、复用既有审批页数据面、租户隔离定死。
- CHK006 → R-5：站内入口为唯一 guaranteed 触达、IM 应答式 best-effort、不构成通知证据、不影响超时起算。
- CHK007 → R-6：`needs_review` 三类进入 / `skip`/`terminate`/`reassign` 三类退出及目标状态、管理员鉴权与审计；补齐 `failed` 终态并修正 `needs_review` 非终态。
- CHK008 → R-7：租约精确化为每运行级、`LEASE_MINUTES=2`、扫描周期 ≤ 1min、抢占与崩溃接管时机、`revision` 乐观锁。
- CHK009 → R-8：驳回理由 trim 非空、≤ 2000 字符、超限 4xx（025 口径）、进审计/运行记录、脱敏沿用 001。
- CHK010 → R-9：`type` vs `mode` 字段分工、与 044 R-17/R-18 及 052 `team` 正交、首期仅 graph 模式支持并修订 plan Structure Decision 措辞。
- CHK011 → R-10：核实 `contracts/orchestration.md` 真实存在（044 R-10/T025 补建，现含六模式 + §7 team），FR-010 落点为 §6、只增不改、YAML 用 `type`。
- CHK012 → R-11：`run.*` / `approval.*` 命名、进 001 审计流、字段枚举、与 044 R-9 payload 内嵌明细同构。
- CHK013 → R-12：仅经 027 门面、纳入建表工具清单（FR-017/SC-005）、门面 FR-015 自动建表、嵌套按 R3 扁平化、不写后端分叉。
- CHK014 → R-13：并行分支终态确定性判定序（驳回优先 → 超时 → 挂起 → 完成），覆盖两驳回/一批准一驳回，补齐终态枚举。
- CHK015 → R-14：取消与决策同原子条件更新仲裁、先落库者胜、幂等结论、禁双重生效。
- CHK016 → R-15：超时扫描 vs 决策同原子仲裁、决策先则批准生效、扫描先则拒绝且无宽限、无法判定按超时 fail-closed、无 todo 残留才翻终态。

**未达标留空（0 项）**
- 无。16 条逐条核实后，所有缺口均可用确定口径消解，未出现"依赖外部待定阈值"或 spec 无法收敛的条目——超时/租约/尺寸/长度/保留期均已有定值或对齐既有口径（OQ 消解记录、001 的 5min 票据、027 FR-015/FR-017、MongoDB 文档上限），竞态均可定确定性判定序。故不虚留空凑数，也不为凑 100% 虚勾。

**结论**：16/16 达标（1 项原生 + 15 项 spec 回填），需求质量门禁通过，可进入 `/speckit-implement`。`[x]` 仅表示需求质量已审阅达标，不代表实现完成。

**代审核实附注（非需求质量结论，供实现侧对齐）**
- 核实到三处"spec/plan 措辞与已落地口径"不一致，已在对应 R 条精确化：① plan Structure Decision「任何模式可嵌审批节点」与 010 契约 §6 / R-9「首期仅 graph 支持」冲突；② Key Entities 状态机漏列 `failed`、把 `needs_review` 与终态并列（实现 `TERMINAL_STATES` 含 `failed`）；③ 决策 #1「挂起时 issue 票据」与实现的两段式（决策时签发）冲突。`_validate_050_shapes` 当前未做"仅 graph 模式"限制校验，实现侧需按 R-9 补齐。
- `ApprovalRuntime` 票据存进程内字典；两段式把票据闭环在单次决策请求内，故"票据不依赖跨进程持久化"成立，但 010 契约 §6「票据不依赖进程内存」字面不准（R-2 按"不依赖跨进程票据持久化"定口径）。