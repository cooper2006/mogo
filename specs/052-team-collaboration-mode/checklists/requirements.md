# Requirements Quality Checklist: 052 team-collaboration-mode

**Purpose**: 校验 052（团队协作模式）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-11-09
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [x] CHK001 **TeamPlan 分派表的 schema** 是否定义（FR-002 说领导产出"成员 × 子任务"，但分派表的字段结构（子任务描述/验收标准/依赖关系）、领导 LLM 输出的 JSON 形态与解析失败行为未给——OQ-1 只覆盖验收判定，拆解输出同样需要 schema）
- [x] CHK002 **验收判定的 schema 与解析失败语义**是否定值（OQ-1 待澄清：verdict/opinion/target_member 字段、非法 JSON 是 fail-closed 还是重试、重试次数未定）
- [x] CHK003 **黑板的尺寸与生命周期约束**是否定义（OQ-4 待澄清：单条目上限、运行级总量上限、超限行为；黑板内嵌 050 快照——快照尺寸约束联动未写）
- [x] CHK004 **接管触发条件**是否定值（OQ-3 待澄清：验收分歧/达上限前/人工主动三类哪些首期交付、YAML 如何声明）
- [x] CHK005 OQ-1~OQ-4 与 050 落地双门禁是否确认（clarify 未过或 050 未落地不得 implement）

## 清晰度（Clarity）

- [x] CHK006 "重指派"的**语义与上限**是否明确（FR-005 说重指派有上限；重指派是换成员还是同成员重试、上限默认值（OQ-2）、与 supervisor 失败阈值 1.0 的关系未写）
- [x] CHK007 验收"退回对应成员"的**意见传递形态**是否定义（US2 说成员读取意见重做；意见进成员 runner 的哪个输入键、成员能否读到黑板历史版本未写）
- [x] CHK008 "团队运行完成"的**最终产出合成**是否定义（US2-1 说"验收通过的成员材料合成"；合成由领导节点做还是引擎拼接、合成失败语义未写）
- [x] CHK009 接管"覆盖领导判定"的**决策选项集**是否定义（US3 说接受/指定重做/终止；三选项的结构化形态、指定重做能否超轮次上限未写）

## 一致性（Consistency）

- [x] CHK010 **050 快照承载团队状态**的结构兼容性是否核实（决策 #3/#6 把黑板/TeamRunState 内嵌 orchestration_runs；050 尚未落地，其快照 schema 未冻结——本 spec 的假设需在 050 设计期双向确认，避免实现期返工）
- [x] CHK011 事件口径是否与 044 R-9 一致（FR-007 说明细收 payload；team 的轮次/验收/黑板事件命名与 payload 结构需与 044 candidates/rounds 同构声明，避免审计流计数口径漂移）
- [x] CHK012 契约落点是否核对（FR-011 指向 010 contracts/orchestration.md——044 T025 已建六模式表，本特性增补第七行，需核实文件现状）
- [x] CHK013 employee_id 软依赖口径是否与 051 一致（FR-010 说 051 未落地忽略记事件；051 spec 的注入时机是会话创建时——team 成员执行的注入点是否同口径需双向声明）

## 边界与歧义（Edge Cases & Ambiguity）

- [x] CHK014 **部分成员 accept 部分 rework** 的混合判定是否覆盖（验收循环按成员逐个判定还是整批判定；一个成员达上限另一个未完成时团队终态未写）
- [x] CHK015 **接管挂起期间成员在途执行**的处置是否覆盖（Edge Cases 说验收循环冻结；已启动的成员执行是等待完成还是软取消（044 R-6 口径）未写）
- [x] CHK016 **领导 rework 指向未产出成员**的非法判定是否覆盖（target_member 不存在或该成员无产出时 fail-closed 还是忽略，未写）
- [x] CHK017 **team 文档级与节点级形态差异**是否定义（044 R-17/R-18 区分文档级与节点级；team 的文档级（整图即团队）与节点级（payload 声明成员）两种形态的成员解析口径未写）

## Notes

- 本 checklist 生成于 spec 首版（2026-11-09），全部未勾待 `/speckit-checklist` 代审；达标后回填 spec「判定口径补充」节。
- CHK010 为跨批次设计协调项：050 快照 schema 冻结前，本特性的黑板/状态结构以假设声明，实现期回填。

## 评审结论（2026-11-10 勾选，agent 代审 + spec 回填）

**原生达标（2 项，无需改 spec）**
- CHK005：OQ-1~OQ-4 已在 spec「待澄清（clarify 门禁）」节经「OQ 决议（2026-11-09 实现批次，按 spec 已定默认值消解并记录）」逐条消解；「clarify 未过 / 050 未落地不得 implement」双门禁在 spec 跨特性关系（050 硬依赖）、plan.md Constraints、tasks.md Prerequisites / 外部门禁三处一致确认，口径完整无歧义。
- CHK012：FR-011 / US4 / SC 已锁定契约落点 = 010 `contracts/orchestration.md`，增量 = 六模式表→七模式 + team YAML 形态示例，验收 = 示例可经 loader 加载 + 七模式与 `VALID_MODES` 一致；代审核对该文件现存 044 R-10 补建的六模式表与 §7 team 段，FR-011 与文件现状方向一致。「核实文件现状」属实现期验证动作、非 spec 层需求缺口，故原生达标。

**spec 回填后达标（15 项，回填见 [spec.md](../spec.md#判定口径补充2026-11-10speckit-checklist-回填) 的 R-1~R-15）**
- CHK001 → R-1（TeamPlan 分派表 JSON schema `{assignments}` + 解析失败 fail-closed）
- CHK002 → R-2（ReviewVerdict schema + 解析失败 fail-closed / 首期不重试，消除「有限重试、重试次数未定」残留歧义 + 轮次上限默认 3 钳制 1..5）
- CHK003 → R-3（黑板 `{author}:{key}` 命名空间 + 运行内生命周期 + 单条 64KiB / 总量 1MiB + 超限 fail-closed）
- CHK004 → R-4（接管首期 P2 预留为软依赖、复用 050 票据/决策/审计但不强制 `awaiting_approval` 跨进程挂起，真挂起留二期；首期仅人工主动触发 `takeover:`，自动触发二期）
- CHK006 → R-5（重指派 = 失败恢复同成员重跑，与验收 rework 为两个独立计数器；上限默认 3 钳制 1..10；失败阈值沿用 supervisor 1.0）
- CHK007 → R-6（rework 意见经 `context["team"]["review_opinion"]` 传入 + 成员可读黑板全部历史版本）
- CHK008 → R-7（最终产出 = 引擎确定性拼接各成员最新验收版本，非 LLM 合成；拼接缺条目 fail-closed）
- CHK009 → R-8（接管决策枚举 `accept|rework|terminate` 结构化 + 全审计；rework 占一轮且不超上限；terminate / 非法枚举 fail-closed）
- CHK010 → R-9（team 状态内嵌 050 `orchestration_runs` 自由形态共享上下文 `context["team"]`、不改 050 schema；只增不改 + 适配器双向确认口径，消解「假设需 050 设计期确认」歧义）
- CHK011 → R-10（一层 `item.*` + 明细收 `payload.team`、不派生嵌套 `item.*`；`team.*` 事件前缀与 044 R-9 `payload.candidates/rounds` 同构）
- CHK013 → R-11（employee_id 注入点 = 成员节点执行前物化 051 EmployeeProfile，与 051「会话创建时物化快照」同口径；051 未落地忽略记事件、引用失效 fail-closed）
- CHK014 → R-12（逐成员判定 + 全员 accept 才完成；任一成员达上限整个团队 failed）
- CHK015 → R-13（冻结期在途成员执行按 044 R-6 软取消、不推进轮次计数）
- CHK016 → R-14（rework 指向未产出 / 不存在成员 fail-closed）
- CHK017 → R-15（文档级 `leader:`/`members:` 与节点级 `payload` 成员解析统一，引用不存在节点加载期 fail-closed）

**未达标留空（0 项）**
- 17 项缺口均可由 spec「判定口径补充」以一等口径消解，无「确实无法达标且无法用 spec 回填消解」的条目；无 `[ ]` 留空。代审未因代码现状（050 已落地 / tasks 已实现）改变任何勾选判断，接管硬软依赖按团队提示以回填定清首期软依赖口径。

**结论**：17/17 达标（原生 2 + 回填 15，R-1~R-15 共 15 条），需求质量门禁通过，可进入 `/speckit-implement`。