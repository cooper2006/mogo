# Requirements Quality Checklist: 017 three-scope-memory

**Purpose**: 校验 017（三范围 Memory 粒度：个人/Workspace/组织三级记忆）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-07-08
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [ ] CHK001 "三级范围"（FR-1）的 Workspace 范围是否定义边界（哪个"工作区"，一个租户多个 Workspace 还是会话即 Workspace，spec 未定 Workspace 粒度）？
- [ ] CHK002 "写入可指定范围，默认个人级"（FR-3）与"会话沉淀默认 Workspace"（FR-5）是否矛盾（FR-3 默认个人 vs FR-5 沉淀默认 Workspace，两条"默认"是否冲突，需统一默认策略）？
- [ ] CHK003 "范围升级个人→组织需授权"（FR-4）是否定义授权角色（哪个岗位角色可授权，clarify 已定"全能力管理员"，FR 是否同步）？
- [ ] CHK004 "记忆生命周期衰减/清理可配置"（FR-8）是否定义生命周期字段（衰减周期默认值、清理触发条件，clarify 已定 30 天衰减，FR 是否同步）？

## 清晰度（Clarity）

- [ ] CHK005 clarify 已定"个人会话默认 personal、多人协同默认 workspace、组织需显式提升"（OQ-1）——FR-3/FR-5 是否同步该默认策略（FR-3"默认个人"与 FR-5"默认 Workspace"的区分是否按"单/多人会话"界定）？
- [ ] CHK006 clarify 已定"衰减周期 30 天，访问命中重置计时"（OQ-2）——FR-8 是否同步衰减/清理的量化口径（还是正文只写"可配置"无默认值）？
- [ ] CHK007 "跨范围读取按可见性隔离"（FR-2）的"可见性"是否定义（个人仅本人、Workspace 仅成员、组织全组织，三者可见性是否逐一定义）？
- [ ] CHK008 "组织级记忆写入受 001 治理约束"（FR-7）的"治理约束"是否定义（走 001 哪一层——授权 + 审计，具体约束点 spec 是否清晰）？

## 一致性（Consistency）

- [ ] CHK009 与 005（knowledge-rag）"个人范围复用 005 个人知识底层存储，不重复建库"（clarify OQ-4）——005 是否声明其个人知识可作为 017 的 personal scope 底层（014/015 CHK 提过 005 检索融合，017 是否同步"记忆进 RAG 检索范围"，clarify OQ-5 定了进检索，FR 是否同步）？
- [ ] CHK010 与 002（session-versioning）"会话沉淀记忆按范围共享"（FR-5/Notes）——002 是否声明其会话沉淀可产记忆（002 CHK011 提过 002 快照是 011 经验源，017 是否也消费 002 会话，三者数据流是否对齐）？
- [ ] CHK011 与 006（position-rbac）"组织级写入授权 = 全能力管理员角色"（clarify OQ-3）——006 是否声明"全能力管理员"可授权组织级记忆（角色能力维度是否含记忆提升权）？

## 边界与歧义（Edge cases & Ambiguity）

- [ ] CHK012 个人记忆在用户离职/删除账号后的处置（是否随账号失效，组织/Workspace 记忆是否保留）是否定义？
- [ ] CHK013 "记忆自动摘要/压缩"被排除（Non-Goals），那长记忆超限如何处理（截断？拒绝写入？spec 未提）是否定义？
- [ ] CHK014 同一内容被写入多个范围（个人 + Workspace 各存一份）时的"冲突/冗余"是否定义（去重 vs 各存独立，spec 未提）？
- [ ] CHK015 记忆"检索进 RAG 范围"（clarify OQ-5）的可见性过滤（检索时按 scope 可见性过滤，与 FR-2 隔离口径是否一致）是否定义？

## Notes

- 本清单为需求质量门禁，全部条目需审阅人逐条评估后勾选；未勾选项构成 `/speckit-implement` 的拦截门禁。
- 标 `[x]` 仅代表"需求质量达标"，不代表实现完成。
- P2 后置特性，CHK 项可在 017 排期前集中处理。
- **CHK002 是明确矛盾点**：FR-3"默认个人级"与 FR-5"会话沉淀默认 Workspace"两条默认策略冲突，需按 clarify OQ-1 的"单/多人会话"区分统一修正 spec。
- clarify 已定值（CHK005/CHK006）需确认是否已回填 FR 正文。
