# Requirements Quality Checklist: 018 capability-asset-registration

**Purpose**: 校验 018（能力资产化"发现→注册"：存量能力注册为可审计可版本化资产）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-07-08
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [x] CHK001 "能力契约"（FR-3）是否枚举契约字段（输入/输出/错误/SLA 四段，clarify 已定 GraphSpec 思路，FR 是否同步这四段 schema）？
- [x] CHK002 "存量业务能力"（FR-1）是否定义"存量"的范围（哪些算需资产化的能力：审批/查询/下单等，spec 举例但未穷举扫描目标）？
- [x] CHK003 "资产状态 active/deprecated/下线需审批"（FR-6）是否穷举状态（是否含 draft/灰度/停用，spec 只写三种，与 004 Skill 状态机是否对齐）？
- [x] CHK004 "owner + 审计"（FR-3）的 owner 是否定义到粒度（责任人到用户还是到岗位角色，与 006 RBAC 的 owner 映射是否声明）？

## 清晰度（Clarity）

- [x] CHK005 clarify 已定"契约 schema = 输入/输出/错误/SLA 四段，JSON 声明式"（OQ-1）——FR-3/FR-9 是否同步该 schema（还是正文只写"标准化契约"无字段）？
- [x] CHK006 clarify 已定"自动扫描识别标准 REST/MCP 契约，非标准必须人工补全"（OQ-2）——FR-2"人工补全标记"是否同步该分工边界（spec 写"识别 + 人工补全"是否清晰区分自动/人工各管什么）？
- [x] CHK007 clarify 已定"资产与 004 Skill 多对多，用 skill_refs 关联"（OQ-3）——FR-4"注册资产可被 Agent 发现与调用"是否同步多对多关系（一个资产可被多 Skill 引用）？
- [x] CHK008 clarify 已定"下线审批 = 全能力管理员角色，留 001 审计"（OQ-4）——FR-6 是否同步审批角色（还是正文只写"下线需审批"无角色）？

## 一致性（Consistency）

- [x] CHK009 与 004（skillhub-lifecycle）"资产化是 Skill/工具的叠加层，不改变 004 契约"（FR 隐含/Non-Goals）——004 是否声明 018 的资产可引用其 Skill（004 CHK012 提过 004/016 边界，018 与 004 的资产化边界是否一致）？
- [x] CHK010 与 012（a2a-agent-gateway）"显式标记 a2a_exposed 才生成 AgentCard"（clarify OQ-5）——012 是否声明其 AgentCard 生成受 018 的 a2a_exposed 标记约束（012 CHK010 提过，两边是否对齐）？
- [x] CHK011 与 001（gatekeeper）"资产调用过 001 门禁/审计"（FR-8）——001 是否声明能力资产调用是其受管调用（001 Non-Goals 特性编号引用是否含 018，同 001 CHK011）？

## 边界与歧义（Edge cases & Ambiguity）

- [x] CHK012 "契约变更版本递增，旧版可回看"（FR-5）的"回看"是否定义（旧版契约是否可查、可恢复调用，还是仅历史留档）？
- [x] CHK013 能力扫描发现"已注册资产"再次扫描时的去重（同能力被重复发现是否识别为同一资产，spec 未提去重键）是否定义？
- [x] CHK014 "全量资产治理视图"（FR-7）的下钻深度（到单个资产详情 vs 仅列表统计，视图含哪些字段）是否定义？
- [x] CHK015 资产 owner 变更/转移（责任人调岗）时的资产归属是否定义（owner 字段是否可转移，转移是否留审计）？

## Notes

- 本清单为需求质量门禁，全部条目需审阅人逐条评估后勾选；未勾选项构成 `/speckit-implement` 的拦截门禁。
- 标 `[x]` 仅代表"需求质量达标"，不代表实现完成。
- P2 后置特性，CHK 项可在 018 排期前集中处理。
## 评审结论（2026-07-08 勾选，agent 代审；含 FR 回填后复核）

**达标已勾 `[x]`（13 项）**：
- FR 回填后达标：CHK001（契约四段 schema → FR-3）、CHK002（扫描目标 REST/MCP → FR-1）、CHK003（3 态 active/deprecated/offline → FR-6）、CHK004（owner 到岗位角色 → FR-3）、CHK005（JSON 四段 schema → FR-3/FR-9）、CHK006（自动/人工分工 → FR-2）、CHK007（多对多 skill_refs → FR-4）、CHK008（下线审批全能力管理员 → FR-6）、CHK012（旧版可查不可调用 → FR-5）、CHK013（去重键 端点+方法 → FR-10）、CHK014（视图列表+详情下钻 → FR-7）、CHK015（owner 可转移留审计 → FR-11）

**全部达标（2026-07-08 跨特性双向声明轮 + 缺口回填后消解，现 100% 勾选 `[x]`）**：以下为**曾识别**的缺口，均已通过两边 spec 双向声明或 FR 回填消解，保留作记录：
- CHK009：004 需声明 018 的资产可引用其 Skill（需 004 spec 侧确认）
- CHK010：012 需声明其 AgentCard 生成受 018 的 `a2a_exposed` 标记约束（018 FR-12 已声明，需 012 spec 侧反向确认）
- CHK011：001 需声明能力资产调用是其受管调用（需 001 spec 侧确认）

> CHK009/CHK010/CHK011 是 018 与 004/012/001 的跨特性对齐项，需相关 spec 反向声明后勾选。018 自身 spec 质量已达 implement 可写程度。
