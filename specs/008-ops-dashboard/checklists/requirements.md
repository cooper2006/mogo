# Requirements Quality Checklist: 008 ops-dashboard

**Purpose**: 校验 008（运营数据看板：成本/使用/质量/趋势四维）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-07-08
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [ ] CHK001 成本看板（FR-2）"模型占比 + 部门/智能体分摊 + 成本预测"是否都定义了分摊算法口径（部门维度靠什么字段，智能体维度靠什么字段）？
- [ ] CHK002 使用看板（FR-3）"活跃用户去重计数"是否定义去重键（user_id 还是 main_id，跨租户是否分开）？
- [ ] CHK003 质量看板（FR-4）"异常率"的"异常"是否枚举（失败/超时/限流 分别计还是合并计）？
- [ ] CHK004 趋势看板（FR-5）"环比/同比"是否定义"周期"粒度（日环比/周同比/月同比，spec 写"上一周期"未定周期）？

## 清晰度（Clarity）

- [ ] CHK005 clarify 已定"人工介入率 = pending_approval_count/total_calls"（OQ-1）——FR-4 正文是否同步了该口径（还是仍写"需人工审批/纠正的调用占比"而未定算法）？
- [ ] CHK006 clarify 已定 P50/P95 取 `token_usage_logs.duration_ms`（OQ-2）——FR-4 是否声明数据源（还是正文写"响应时长分位"而无源）？
- [ ] CHK007 clarify 已定瓶颈 = top-N（OQ-3）——FR-5 是否同步"首期 top-5"（还是仍写"成本/时长排序的 top 调用"无 N 值）？
- [ ] CHK008 "成本合计与总量一致"（FR-6/Success）是否定义"一致"的容差（浮点误差是否允许，对账精度）？

## 一致性（Consistency）

- [ ] CHK009 与 007（llm-gateway-resilience）"数据源对齐"（FR-8）——clarify 007 把 failover 事件落 token_usage_logs 附加字段，008 成本/质量看板是否需要这些字段（两边字段口径是否对齐，同 007 CHK009）？
- [ ] CHK010 与 006（position-rbac）"数据按租户隔离 + 管理员权限"（FR-7/Notes）——看板访问的最小角色是否声明（全能力管理员 vs 岗位角色"管理员"）？
- [ ] CHK011 Non-Goals"不改变既有 dashboard/analytics 端点返回契约（向后兼容扩展）"与"新增运营驾驶舱标签页"（clarify OQ-4）是否一致（新增标签页是加新端点还是扩展既有，契约是否变化）？

## 边界与歧义（Edge cases & Ambiguity）

- [ ] CHK012 空租户（FR-9）"0 指标 + 空态引导"是否定义各维度的空态文案与引导（是同一空态还是分维度）？
- [ ] CHK013 "成本预测基于近 N 期"（US2）的 N 是否定义默认值（spec 未定 N，clarify 也未覆盖）？
- [ ] CHK014 时间范围筛选（FR-3）的时区口径（UTC vs 本地时区，跨 0 点的数据归哪日）是否声明？
- [ ] CHK015 "异常可下钻到具体请求"（FR-10）的下钻深度是否定义（到请求 ID 即可，还是含完整 payload，payload 是否脱敏）？

## Notes

- 本清单为需求质量门禁，全部条目需审阅人逐条评估后勾选；未勾选项构成 `/speckit-implement` 的拦截门禁。
- 标 `[x]` 仅代表"需求质量达标"，不代表实现完成。
- **CHK009 是关键一致性点**：与 007 共享 token_usage_logs 数据源，需双向确认字段口径（含 007 新增的 failover 字段）。
- clarify 已定值（CHK005/CHK006/CHK007）需确认是否已回填 FR 正文；CHK013 的 N 值是遗留缺口，建议补充 clarify。
