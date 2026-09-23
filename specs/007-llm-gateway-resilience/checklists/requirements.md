# Requirements Quality Checklist: 007 llm-gateway-resilience

**Purpose**: 校验 007（LLM 网关韧性：failover/降级/退避/计量）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-07-08
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [ ] CHK001 failover（FR-1）"主/备供应商"是否定义"主"与"备"的判定依据（配置显式声明 vs 按优先级推断，spec 仅写"失败自动切换"）？
- [ ] CHK002 degradation_chain（FR-2）"逐级降档"是否穷举降档维度（模型规格/供应商/能力档，"降档"指降到什么）？
- [ ] CHK003 计量维度（FR-6）供应商/模型/租户/智能体四维度是否都定义了"智能体"维度取值来源（哪个字段标识智能体）？
- [ ] CHK004 成本估算（FR-5）是否定义"估算"的口径（按 token 单价 × 用量，单价来源是哪张价格表，与 008 的 MODEL_PRICES 是否同一表）？

## 清晰度（Clarity）

- [ ] CHK005 FR-9"单供应商行为与现状一致"是否可验证（如何证明 failover 层对单供应商是 no-op）？
- [ ] CHK006 clarify 已定退避默认 1.5s/30s/±10%/3 次（OQ-2）——spec 正文 FR-3 是否同步了"默认 3 次"，还是仍写"可配置"而无默认值（FR 正文与 clarify 记录是否一致）？
- [ ] CHK007 clarify 已定"仅文本模型"（OQ-3）——FR-1/FR-2 的韧性语义是否显式限定"文本 LLM 调用"，避免实现误用于图像调用？
- [ ] CHK008 "降级事件记录降级前/后模型与原因"（US2）的"原因"是否枚举（上游 429/5xx/超时/手动切换，还是自由文本）？

## 一致性（Consistency）

- [ ] CHK009 与 008（ops-dashboard）"计量落 token_usage_logs 附加字段"（clarify OQ-4）——008 spec 是否声明了这些新增字段（failover_from/failover_to/degradation_step），两边字段口径是否对齐？
- [ ] CHK010 与 001（gatekeeper）"供应商凭据遵循 001 安全原则不进仓库"（Notes）——与 001 的 PII/密钥脱敏口径是否一致（凭据是密钥管理还是 PII 脱敏）？
- [ ] CHK011 Non-Goals"不实现成本预算硬限流（配额由特性 001 负责）"与 001 的配额三维是否对齐（001 配额是"工具调用次数"，007 是"LLM 调用 token/成本"，二者配额维度是否概念一致）？

## 边界与歧义（Edge cases & Ambiguity）

- [ ] CHK012 所有供应商全故障（无备）时，failover + 降级链耗尽的错误语义是否与"单供应商故障"区分（US2 只写了链耗尽，全故障场景未提）？
- [ ] CHK013 重试中途会话被用户取消/网关超时的交互（重试是否应响应取消信号）是否定义？
- [ ] CHK014 计量在"failover 切换成功"时的归属（切换前后多次调用的 token/成本归到哪个供应商/模型维度）是否明确？
- [ ] CHK015 tenacity 抖动 ±10%（clarify OQ-2）的"默认 + jitter"是否需 spec 级声明（还是纯实现细节，spec 不应暴露实现）？

## Notes

- 本清单为需求质量门禁，全部条目需审阅人逐条评估后勾选；未勾选项构成 `/speckit-implement` 的拦截门禁。
- 标 `[x]` 仅代表"需求质量达标"，不代表实现完成。
- **CHK009 是关键一致性点**：clarify 把 failover 事件落在 `token_usage_logs` 附加字段，需 008 spec 同步声明这些字段，避免 007/008 字段口径各说各话。
- clarify 已定值（CHK006/CHK007）需确认是否已回填 FR 正文。
