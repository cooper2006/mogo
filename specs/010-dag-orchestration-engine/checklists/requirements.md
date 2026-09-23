# Requirements Quality Checklist: 010 dag-orchestration-engine

**Purpose**: 校验 010（通用 DAG 编排引擎：四模式/拓扑/环检测/条件跳过/节点重试）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-07-08
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [ ] CHK001 四编排模式（FR-1）的每种是否都定义了节点"输入/输出契约"（节点间如何传数据，supervisor 如何分派/聚合的边界）？
- [ ] CHK002 "无依赖节点可并行"（FR-2）是否定义并行的"资源约束"（clarify 已定并发度 4，FR 正文是否同步？超限节点排队还是拒绝？）
- [ ] CHK003 条件跳过（FR-4）"跳过可追溯"是否定义追溯内容（跳过原因/求值结果/被跳过的下游是否标记）？
- [ ] CHK004 节点失败阻塞下游（FR-6）是否定义"阻塞"的完整语义（仅直接下游还是全下游闭包，被阻塞节点状态如何标记）？

## 清晰度（Clarity）

- [ ] CHK005 clarify 已定 JSON 条件对象（OQ-1）——FR-4 正文是否同步"禁用任意代码、仅受限算子"（还是正文只写"表达式求值"而无安全边界）？
- [ ] CHK006 clarify 已定并行度 4（OQ-2）——FR-2 是否声明默认并发度（还是仅 clarify 记录，正文无值）？
- [ ] CHK007 "编排定义声明式、可版本化（与 002 对接）"（FR-8）的"版本化"是否定义版本字段（编排定义如何标识版本、旧版本如何存）？
- [ ] CHK008 环检测"报错含环路径"（FR-3）是否定义环路径的输出格式（节点序列 vs 节点 + 边，是否定位到具体节点名）？

## 一致性（Consistency）

- [ ] CHK009 与 007（llm-gateway-resilience）"节点重试与模型重试分层"（FR-5/Notes + clarify OQ-3）——007 spec 是否反向声明"节点级重试包裹模型调用"（两边分层口径是否一致）？
- [ ] CHK010 与 009（hooks-interception）"节点执行前后挂 PreToolUse/PostToolUse 钩子"（Notes/FR-7）——009 是否声明"节点执行"是其钩子触发点（两边挂载关系是否对齐）？
- [ ] CHK011 与 002（session-versioning）"工作流版本化是 002 后续范围，本特性只提供引擎"（Notes/FR-8）——002 spec 是否声明 GraphSpec 版本化对接 010 引擎（边界是否清晰）？
- [ ] CHK012 "现有内容规划可迁移、行为等价"（FR-9 + Non-Goals）——clarify 已定双轨 + 等价测试（OQ-4），spec 是否声明"双轨"策略（还是仅写"可迁移"而无过渡策略）？

## 边界与歧义（Edge cases & Ambiguity）

- [ ] CHK013 "表达式语法错误 → fail_closed 跳过或报错"（US3 Acceptance，原 spec 标注需 clarify）——clarify 是否已定（当前 clarify 记录未覆盖"语法错误"行为，仅定了算子集）？
- [ ] CHK014 节点"部分成功"（节点内多步，部分完成）的语义（是原子成功/失败还是可恢复中间态）是否定义？
- [ ] CHK015 supervisor 模式"监督节点协调子节点"的失败传播（监督节点本身失败/子节点全失败）是否定义？
- [ ] CHK016 并行度 4（clarify）与"节点内调 LLM"（007）叠加时的端到端并发预算（多 DAG × 并发度 × 节点内 LLM 调用）是否有总预算约束？

## Notes

- 本清单为需求质量门禁，全部条目需审阅人逐条评估后勾选；未勾选项构成 `/speckit-implement` 的拦截门禁。
- 标 `[x]` 仅代表"需求质量达标"，不代表实现完成。
- **CHK013 是遗留缺口**：US3 标注"表达式语法错误策略需 clarify"，但当前 clarify 记录未覆盖该行为，建议补充 clarify。
- 跨特性分层/挂载（CHK009/CHK010/CHK011）需与 007/009/002 三边口径统一。
