# Requirements Quality Checklist: 032 eval-gate

**Purpose**: 校验 032（评测门禁：发布前硬阈值阻断）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-10-23
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [x] CHK001 指标分母为 0 时的取值与判定口径是否定义（Edge Cases 只说"空期望引用不参与引用支撑率分母"、"拒答用例不进任务成功率分母"，但**未定义分母为 0 时该指标视为"不适用免检"还是"按 0.0 阻断"**；若按 0.0 则一个测试集全部为拒答用例的 Skill 会因"引用支撑率 0"被误杀）？
- [x] CHK002 拒答话术词表是否给出最小必需集合（FR-005 只写"拒答话术"，来源仅指向 `knowledge_qa_agent.py`；判定器命中哪些词才算拒答、词表如何随实现演进，评审无法据此判定达标）？
- [x] CHK003 `expectations` 的匹配语义是否定义（FR-005 写"期望要点匹配"，但未说明是**全部命中（AND）**还是**任一命中（OR）**、是子串包含还是分词覆盖——两种口径会得出完全不同的任务成功率）？
- [x] CHK004 dry-run 的完整产出边界是否定义（FR-010 只说"不阻断、不产生发布、不落阻断审计"，**未说明是否仍落 `skill_eval_runs` 运行记录**、低于阈值时返回 200+`passed=false` 还是 4xx）？
- [x] CHK005 阈值策略的可配范围是否穷举默认值（Key Entities 列了 `min_cases`/`max_cases`/`timeout_seconds`，但 FR-006 只说"阈值策略租户可配"，**未明确这三项是否也随策略可配、默认值是多少**）？

## 清晰度（Clarity）

- [x] CHK006 单用例超时与整体超时的关系是否定义（FR-011 只给"整体超时默认 300s"，**单次 LLM 调用超时未定义**，无法区分"整体超时"与"单用例卡死"；Edge Case 又说"复用 007 韧性"，007 的重试是否计入 300s 也未写明）？
- [x] CHK007 `EvalGateBlocked` 的 HTTP 状态码语义是否分层（SC-001 只写"4xx"；不达标、无测试集/样本不足、网关不可用/超时三类失败的语义不同，前端需区分"补测试集"与"稍后重试"，未分层则实现各有取舍）？
- [x] CHK008 `expected_refs` 的匹配粒度是否定义（Edge Case 指向 `citation_resolver.py`，其 citation id 为 `document_id:chunk_id` 复合串；`expected_refs` 存 document_id 还是复合 id、匹配是子串包含还是前缀相等，直接决定引用支撑率的分子口径）？
- [x] CHK009 存量 Skill 被阻断时的补数据引导是否可验证（Edge Case 只写"管理员需先补测试集"，US3 只要求展示报告；**无测试集与样本不足两种阻断的提示文案是否要指明"去哪补、补几条"**未定义）？

## 一致性（Consistency）

- [x] CHK010 审计写入失败的处理是否与 001 一致（FR-008 要求阻断与放行都落 `gate_events`，但**未说明写入失败时放行还是 fail-closed**；001 `audit.py` 对落库异常判 DENY，032 若不显式声明会与治理基线相反）？
- [x] CHK011 与 001 `gate_events` 既有文档结构的字段映射是否声明（FR-008 只要求 `event_type` 与指标字段，未说明是否复用 001 的 `decision`/`layer`/`detail`；001 的 `decision` 是 ALLOW/DENY 枚举，直接复用语义不等价）？
- [x] CHK012 与 036 的消费契约是否闭合（Key Entities 说"036 可信评级消费本实体"，但**未声明 036 读取哪些字段、032 是否保证这些字段只增不改**）？
- [x] CHK013 凭据传递方式是否与 chat-api 网关契约对齐（FR-004 说用 `backend_service_token`，但未定义头名/令牌形态；Phase 0 研究显示网关端点是 `Authorization: Bearer` + NDJSON 流，与 `X-MOGO-Service-Token` 服务凭据不是同一套 —— spec 是否应声明"spec 不锁定头名，以 chat-api 网关契约为准"）？

## 边界与歧义（Edge cases & Ambiguity）

- [x] CHK014 用例数上限的两处语义是否统一（FR-002 说"超限创建被拒 400"，gate 执行侧也有 `max_cases` 上限；**两处是否同一数值、执行侧超限应阻断还是截断**未定义）？
- [x] CHK015 并发发布的重复评测成本是否被接受（Edge Case 说"既有版本唯一约束兜底、不引入额外锁"，但两次并发 publish 会**各跑一次评测（双倍 LLM 成本）**，spec 未声明这是可接受的既定取舍）？

## Notes

- 本清单为需求质量门禁，全部条目需审阅人逐条评估后勾选；未勾选项构成 `/speckit-implement` 的拦截门禁。
- 标 `[x]` 仅代表"需求质量达标"，不代表实现完成。

## 评审结论（2026-10-23 勾选，agent 代审 + spec 回填）

**原生达标（2 项，无需改 spec）**
- CHK009：FR-007 已要求"提示补充测试集"、US3 已要求展示报告，阻断提示的可验证性成立；具体文案属实现细节，spec 不应锁定。
- CHK015：Edge Case 已声明"版本唯一约束兜底、不引入额外锁"，取舍方向明确。

**spec 回填后达标（13 项，回填见 [spec.md](../spec.md#判定口径补充2026-10-23speckit-checklist-回填) 的 R-1~R-13）**
- CHK001 → R-1（分母为 0 记 `null` 并跳过阈值比较，避免全拒答测试集被"引用支撑率 0"误杀）
- CHK002 → R-2（拒答话术最小必需词表 + 命中任一即拒答 + 单测锁定）
- CHK003 → R-3（`expectations` 子串 AND 语义；空期望不进任务成功率分母）
- CHK004 → R-4（dry-run 落 `skill_eval_runs`、不落 `gate_events`、低于阈值返回 200 + `passed=false`）
- CHK005 → R-5（六项策略默认值表 + 租户/Skill 两级 + 禁止 `enabled` 关闭字段）
- CHK006 → R-6（单用例 60s 与整体 300s 的取小关系，007 重试耗时计入单用例预算）
- CHK007 → R-7（409 补数据 / 502 重试 / 503 审计失败三层状态码）
- CHK008 → R-8（`expected_refs` 允许 `document_id` 或 `document_id:chunk_id`，匹配为子串包含）
- CHK010 → R-9（审计写入失败 fail-closed，与 001 `audit.py` 落库异常判 DENY 一致）
- CHK011 → R-10（复用 001 字段并补 `event_type`；`decision` 用 `blocked|passed`，与六层链 `ALLOW/DENY` 不同枚举，故不参与链式判定）
- CHK012 → R-11（对 036 的五个字段只增不改契约）
- CHK013 → R-12 / R-12.1 / R-12.2（凭据头名不锁定，以 chat-api 网关实际契约为准；实现阶段补证：网关只认 HMAC 签名令牌而非 `v1|...` 服务令牌，故 admin-api 新增 `eval_gate/gateway_auth.py` 签发器，且请求体须恰好携带 `profileVersion`/`modelInstanceId`/`provider`/`model`/`messages` 五字段并与令牌 claims 一致）
- CHK014 → R-13（创建期 400 与执行期 409 使用同一 `max_cases`；并发重复评测为既定取舍）

**结论**：15/15 达标，需求质量门禁通过，可进入 `/speckit-implement`。

