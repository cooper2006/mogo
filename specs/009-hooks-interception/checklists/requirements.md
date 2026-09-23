# Requirements Quality Checklist: 009 hooks-interception

**Purpose**: 校验 009（五事件钩子拦截机制）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-07-08
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [ ] CHK001 三类声明式规则（deny_tool / require_field / observe）的语义是否都完整定义（require_field 缺字段时的拒绝语义、observe 记录什么字段）？
- [ ] CHK002 五事件各自的"可携带/可修改"数据是否定义（SessionStart 可注入什么上下文，SessionEnd 可清理什么）？
- [ ] CHK003 作用域（工具/会话/租户，FR-8）的叠加语义是否定义（同一调用同时命中工具级 + 租户级规则时如何合并）？
- [ ] CHK004 钩子失败时的"降级"是否仅 fail_closed（clarify 已定不可放行），spec 是否还有"部分规则失败、部分成功"的混合语义？

## 清晰度（Clarity）

- [ ] CHK005 clarify 已定"首期仅 PreToolUse"（OQ-3）——FR-1 仍列五事件，spec 是否明确"五事件为目标态、首期交付仅 PreToolUse"（避免实现误以为要一次做全）？
- [ ] CHK006 clarify 已定"超时 5s 可配"（OQ-1）——FR-3 是否同步默认值（还是正文只写"有超时保护"而无默认）？
- [ ] CHK007 "observe 规则可只记录不拦截"（clarify OQ-2）——spec 正文是否区分 observe 与 deny/require 的拦截强度（还是仅在 clarify 记录里）？
- [ ] CHK008 "规则解析失败"（FR-3）的"解析失败"是否定义（规则 JSON 非法/字段缺失/未知 rule_type 三类是否都 fail_closed）？

## 一致性（Consistency）

- [ ] CHK009 与 001（gatekeeper）"PreToolUse 是 001 六层门禁链的扩展点"（Notes/FR-5）——001 是否反向声明了 009 钩子作为其第 4 层（审批）的拦截扩展（两边扩展点关系是否双向一致）？
- [ ] CHK010 与 002（session-versioning）"会话生命周期事件是 002 的钩子载体"（FR-7）——002 是否声明 SessionStart/End/MemoryCommit 经 009 触发（同 002 CHK010）？
- [ ] CHK011 与 019（harness-elastic）"薄模式可跳过非红线 Hooks"（019 clarify OQ-2）——009 是否声明"哪些钩子是薄模式可跳过的、fail_closed 底线是否保留"（两边口径）？
- [ ] CHK012 "钩子进审计通道（与 001 联动）"（FR-5）——审计落点是 001 的审计层还是独立钩子审计集合（与 001 OQ 是否对齐）？

## 边界与歧义（Edge cases & Ambiguity）

- [ ] CHK013 deny_tool 拒绝后的错误返回语义（拒绝码/提示文案，是否区分"规则拒绝"与"门禁拒绝"）是否定义？
- [ ] CHK014 规则"声明式配置增删无需改代码"（FR-4/Success）的生效时机（即时 vs 下次会话）是否明确？
- [ ] CHK015 同一工具同时被多条规则作用时的求值顺序（deny 优先于 require？多条 observe 是否都记录）是否定义？
- [ ] CHK016 钩子执行对工具调用延迟的影响（5s 超时 × 多钩子叠加）是否有总延迟预算（spec 是否声明端到端延迟上限）？

## Notes

- 本清单为需求质量门禁，全部条目需审阅人逐条评估后勾选；未勾选项构成 `/speckit-implement` 的拦截门禁。
- 标 `[x]` 仅代表"需求质量达标"，不代表实现完成。
- **CHK009/CHK010/CHK011 是关键跨特性对齐项**：009 与 001/002/019 互为扩展点，需三边口径统一。
- clarify 已定值（CHK005/CHK006/CHK007）需确认是否已回填 FR 正文。
