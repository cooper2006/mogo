# Requirements Quality Checklist: 056 unified-approval-kernel

**Purpose**: 校验 056（审批单一内核）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-11-12
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 语义生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [ ] CHK001 R-1 中 `ApprovalKernel` 类的完整方法签名是否均已定义（issue / decide / cancel / list_todos / reassign / resolve_timeout），各方法的入参/返回值 schema 是否明确（如 `expected_revision` 如何传入——调用方持有还是 Kernel 内部管理？）
- [ ] CHK002 R-2 的 revision 原子条件更新在 Mongo vs PanWeiDB 两侧的 `update_one` filter 行为是否一致（Mongo `$where: {revision: N}` vs PG `WHERE revision = N`），双后端均需覆盖
- [ ] CHK003 R-3 角色型审批人的「暂不支持」决策是否有明确的升级路径说明（phase 何时支持、数据模型是否需要扩展 `approver_type` 字段）
- [ ] CHK004 R-4 改派的 `resume_token` 重签机制：旧 token 是立即失效还是 grace period？调用方（前端待办页）是否需要感知 token 变更？
- [ ] CHK005 E2（存量数据兼容视图）的具体实现方式未写——是 read-through proxy 还是只读 SQL view？schema 兼容性如何保证？

## 清晰度（Clarity）

- [ ] CHK006 R-1 中「strategy pattern 注入 `on_decide` hook」的具体接口形状未给出（是 callable、event bus、还是直接 if/elif source 分发）
- [ ] CHK007 R-6 审计事件命名规范中 `approval.sop.decided` 等 action 名称是否与 001 `gate_events` 既有命名空间冲突（已有 `portal.approved`、`employee.created` 等前缀）
- [ ] CHK008 Phase 6 T029-T031 改造旧代码时，deprecated shim 的保留期限是否明确（下个版本删还是无限期保留）

## 一致性（Consistency）

- [ ] CHK009 R-5 身份校验对三种 source 都要求 `actor_id == approver_id`，但 admin-api 侧既有 RBAC 体系是通过 position_roles 做角色→用户映射，这里是否还需要二次校验（RBAC 已在 gate 层做过）？
- [ ] CHK010 plan.md Phase 2 T011 `decide()` 中的「按 source 分发回调 hook」与 spec R-1 「回调业务侧」的对应关系是否清晰（tool → gate 放行、portal → requests.granted、sop → run_store.resume()）
- [ ] CHK011 复审报告 P1-3 要求 SOP 审计进 001 gate_events，R-6 也要求此行为；但现有 `orchestration_runs.events[]` 是否同步保留（双写还是迁移）需明示

## 边界与歧义（Edge Cases & Ambiguity）

- [ ] CHK012 多分支并行审批中「一分支驳回导致其他分支 expire」的原子性：`resolve_timeout()` 一次性处理所有 pending 节点，还是逐节点 expire？并发下是否会漏掉某些节点？
- [ ] CHK013 D1 存量数据「read-through proxy」方案若选 SQL view（PanWeiDB 侧），view 的定义和维护成本未评估
- [ ] CHK014 改派后原审批人的「通知」事件（D2 clarify）如果 IM 渠道不可用，是否重试、重试几次、降级到站内消息？

## Notes

- 本特性的核心风险在于「三套状态机合并」的影响面——CHK009/CHK011 是直接相关的契约一致性问题，需在 implement 前明确
- D1/D2/D3 三个 clarify 项均在 spec 中标记为「非阻塞」，但实际 implement 时会成为具体的设计决策点，建议在 Phase 0 完成后尽快拍板
