# Requirements Quality Checklist: 018 capability-asset-registration

**Purpose**: 校验 018（能力资产化"发现→注册"：存量能力注册为可审计可版本化资产）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-07-08
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [ ] CHK001 "能力契约"（FR-3）是否枚举契约字段（输入/输出/错误/SLA 四段，clarify 已定 GraphSpec 思路，FR 是否同步这四段 schema）？
- [ ] CHK002 "存量业务能力"（FR-1）是否定义"存量"的范围（哪些算需资产化的能力：审批/查询/下单等，spec 举例但未穷举扫描目标）？
- [ ] CHK003 "资产状态 active/deprecated/下线需审批"（FR-6）是否穷举状态（是否含 draft/灰度/停用，spec 只写三种，与 004 Skill 状态机是否对齐）？
- [ ] CHK004 "owner + 审计"（FR-3）的 owner 是否定义到粒度（责任人到用户还是到岗位角色，与 006 RBAC 的 owner 映射是否声明）？

## 清晰度（Clarity）

- [ ] CHK005 clarify 已定"契约 schema = 输入/输出/错误/SLA 四段，JSON 声明式"（OQ-1）——FR-3/FR-9 是否同步该 schema（还是正文只写"标准化契约"无字段）？
- [ ] CHK006 clarify 已定"自动扫描识别标准 REST/MCP 契约，非标准必须人工补全"（OQ-2）——FR-2"人工补全标记"是否同步该分工边界（spec 写"识别 + 人工补全"是否清晰区分自动/人工各管什么）？
- [ ] CHK007 clarify 已定"资产与 004 Skill 多对多，用 skill_refs 关联"（OQ-3）——FR-4"注册资产可被 Agent 发现与调用"是否同步多对多关系（一个资产可被多 Skill 引用）？
- [ ] CHK008 clarify 已定"下线审批 = 全能力管理员角色，留 001 审计"（OQ-4）——FR-6 是否同步审批角色（还是正文只写"下线需审批"无角色）？

## 一致性（Consistency）

- [ ] CHK009 与 004（skillhub-lifecycle）"资产化是 Skill/工具的叠加层，不改变 004 契约"（FR 隐含/Non-Goals）——004 是否声明 018 的资产可引用其 Skill（004 CHK012 提过 004/016 边界，018 与 004 的资产化边界是否一致）？
- [ ] CHK010 与 012（a2a-agent-gateway）"显式标记 a2a_exposed 才生成 AgentCard"（clarify OQ-5）——012 是否声明其 AgentCard 生成受 018 的 a2a_exposed 标记约束（012 CHK010 提过，两边是否对齐）？
- [ ] CHK011 与 001（gatekeeper）"资产调用过 001 门禁/审计"（FR-8）——001 是否声明能力资产调用是其受管调用（001 Non-Goals 特性编号引用是否含 018，同 001 CHK011）？

## 边界与歧义（Edge cases & Ambiguity）

- [ ] CHK012 "契约变更版本递增，旧版可回看"（FR-5）的"回看"是否定义（旧版契约是否可查、可恢复调用，还是仅历史留档）？
- [ ] CHK013 能力扫描发现"已注册资产"再次扫描时的去重（同能力被重复发现是否识别为同一资产，spec 未提去重键）是否定义？
- [ ] CHK014 "全量资产治理视图"（FR-7）的下钻深度（到单个资产详情 vs 仅列表统计，视图含哪些字段）是否定义？
- [ ] CHK015 资产 owner 变更/转移（责任人调岗）时的资产归属是否定义（owner 字段是否可转移，转移是否留审计）？

## Notes

- 本清单为需求质量门禁，全部条目需审阅人逐条评估后勾选；未勾选项构成 `/speckit-implement` 的拦截门禁。
- 标 `[x]` 仅代表"需求质量达标"，不代表实现完成。
- P2 后置特性，CHK 项可在 018 排期前集中处理。
- **CHK010 是关键一致性点**：018 的 `a2a_exposed` 标记与 012 的 AgentCard 生成需双向对齐；clarify 已定值（CHK005/CHK006/CHK007/CHK008）需确认是否已回填 FR 正文。
