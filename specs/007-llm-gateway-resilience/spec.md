# Feature Specification: LLM Gateway Resilience

**Feature Branch**: `007-llm-gateway-resilience`

**Created**: 2026-07-08

**Status**: Draft

**Input**: 补齐规划文档清单 2（P0）"LLM 网关韧性"：主→备供应商故障转移 failover、降级链 degradation_chain（主模型失败逐级降档）、指数退避重试、用量/成本计量上报。改动集中在 `llm/model_router.py` + providers 模块，影响面可控。

## User Scenarios & Testing *(mandatory)*

用户故事按优先级排列，每个独立可交付、可测试。

### User Story 1 (P1) — 主→备供应商故障转移（failover）

LLM 调用按配置的主/备供应商顺序执行；主供应商失败（超时/限流/服务不可用）时自动切换备用供应商重试，用户无感知；所有失败与切换事件记录日志。

**Acceptance Scenarios:**
- 主供应商 500/超时 → 自动切备用供应商，请求成功
- 主、备均失败 → 返回聚合错误（含各供应商失败原因）
- 切换事件 → 日志记录供应商、耗时、失败原因、最终命中供应商
- 仅配置单一供应商 → failover 不启用，按现有行为

### User Story 2 (P1) — 降级链 degradation_chain

主模型调用失败时按配置的降级链逐级降档（如 高性能 → 中档 → 轻量），直到某档成功或链耗尽；降档记录可追溯。

**Acceptance Scenarios:**
- 主档模型失败 → 降到链中下一档，成功则用该档结果
- 链逐级失败 → 链耗尽后返回降级链耗尽错误
- 降档事件 → 记录降级前/后模型与原因

### User Story 3 (P1) — 指数退避重试

对可重试错误（限流 429、瞬时 5xx、超时）按指数退避 + 抖动重试，最大次数与退避上限可配置；不可重试错误（鉴权失败 401/403）不重试直接失败。

**Acceptance Scenarios:**
- 429 限流 → 按退避间隔重试至成功或达上限
- 401 鉴权失败 → 不重试，立即返回
- 重试次数与间隔 → 日志可观测

### User Story 4 (P2) — 用量/成本计量上报

每次 LLM 调用记录 token 用量（输入/输出）与估算成本，按供应商/模型/租户/智能体维度聚合上报，供驾驶舱（特性 008）消费。

**Acceptance Scenarios:**
- 调用后 → 记录 TokenUsageRecord（模型、供应商、token、时间）
- 按维度聚合 → 成本可分摊到部门/智能体
- 计量数据 → 落库可查询，与特性 008 驾驶舱对接

### Notes / Assumptions
- 本特性补齐规划文档 §2.2 / 清单 2（P0 生产可用性直接受益），属缺口新特性
- 现有基础：`llm/model_router.py`（ModelRouter.resolve，仅多供应商选择 + config_fallback，无 failover/degradation_chain/退避/计量）
- 现有 provider：`llm/providers/`（azure_openai/azure_responses/azure_gpt_image/default_openai/qwen）
- 现有计量骨架：`token_usage/`（TokenUsageRecord 模型、push 上报、dispatcher）
- 与特性 008（驾驶舱）的关系：本特性的计量上报是驾驶舱成本看板的来源
- 与特性 001（gatekeeper）的关系：供应商凭据管理遵循 001 安全原则（不进仓库）
- 退避/重试默认值需 clarify（最大重试次数、退避基数、抖动幅度）

## Functional Requirements

- FR-1: LLM 调用支持主/备供应商 failover（**仅文本 LLM 调用**，图像走 `azure_gpt_image` 自身重试），失败自动切换并记录；**主/备由配置显式声明顺序**（非推断）
- FR-2: 支持 degradation_chain 逐级降档（**降档维度 = 文本模型档位：高性能→中档→轻量，仅文本**），链耗尽返回明确错误
- FR-3: 可重试错误（429/5xx/超时）指数退避 + 抖动重试；**默认退避基数 1.5s、上限 30s、抖动 ±10%、最大重试 3 次（均可配）**，沿用既有 `azure_gpt_image` 值避免行为漂移
- FR-4: 不可重试错误（401/403）不重试直接失败
- FR-5: 每次调用记录 token 用量（输入/输出）与估算成本；**成本 = token 单价 × 用量，单价取自 008 的 MODEL_PRICES 价格表（两边同一张表）**
- FR-6: 用量/成本按供应商/模型/租户/智能体维度聚合（**智能体维度取调用的 `agent_id` 字段**），供特性 008 驾驶舱消费
- FR-7: failover/降级/重试/计量事件全部日志可观测（**事件落 `token_usage_logs` 附加字段 `failover_from`/`failover_to`/`degradation_step`，不新增独立 collection**）
- FR-8: 供应商与降级链通过配置声明，不硬编码（扩展点）
- FR-9: 仅配置单一供应商时行为与现状一致（向下兼容，不破坏现有调用）
- FR-10: 所有供应商全故障（无可用备）→ 返回聚合错误（含各供应商失败原因），与"单供应商故障"区分

## Non-Goals
- 不实现 LLM 响应缓存（属独立能力）
- 不实现多模态/图像模型的独立 failover（图像走 azure_gpt_image，本期仅文本模型韧性）
- 不改变现有 model_router 的选择语义（intent/stage/node 优先级保留）
- 不实现成本预算硬限流（配额由特性 001 门禁层负责）
- 不引入新的 LLM 供应商接入（本期韧性作用于既有 providers）

## Success Criteria
- 主供应商故障时 failover 成功率 100%（有备用供应商前提下）
- 降级链耗尽 100% 返回明确错误（不静默）
- 可重试错误按配置次数退避，不可重试错误 0 次多余重试
- LLM 调用计量记录覆盖率 100%（token + 成本）
- 单供应商配置场景行为与现状一致（回归 0 破坏）

## Further Details
- 技术实现（failover 调度器、退避参数、计量落库）由 plan.md 承载
- 与特性 008（驾驶舱）的关系：计量上报是成本/使用看板的来源
- 默认退避与重试参数需 `/speckit-clarify` 定值

## Clarify 记录（/speckit-clarify，2026-07-08）

### OQ-1 退避实现（plan 原 OQ-1）
- **决策**：引入 `tenacity`（`>=8.3.0`），不手写。
- **依据**：`services/chat-api/requirements.txt` / `pyproject.toml` 已含 tenacity；`llm/providers/azure_gpt_image.py` 已用 tenacity（`retry_base_seconds=1.5` / `retry_max_seconds=30.0` + `_post_with_retry`）。复用既有依赖，非新增。

### OQ-2 退避/重试默认参数（spec 原"需 clarify 定值"）
- **决策**（取既有 azure_gpt_image 实测值，保证与既有行为一致）：
  - 退避基数 `retry_base_seconds = 1.5`，退避上限 `retry_max_seconds = 30.0`
  - 抖动：±10%（tenacity 默认 + jitter）
  - 可重试错误：429 / 5xx / 超时；**不可重试**：401 / 403（立即失败）
  - 最大重试次数默认 3（可配置）
- **影响**：`llm/resilience/retry.py` 直接沿用这组默认值，避免与既有 provider 行为漂移。

### OQ-3 降级链是否作用于多模态/图像（spec 原 OQ-3）
- **决策**：**仅文本模型**。spec Non-Goals 已声明"图像走 azure_gpt_image，本期仅文本模型韧性"；degradation_chain 仅对文本 LLM 调用生效，图像调用走既有 provider 自身重试。

### OQ-4 failover 事件落点（plan 原 OQ-4）
- **决策**：复用 `token_usage_logs` 附加字段（`failover_from` / `failover_to` / `degradation_step`），**不新增独立 collection**。理由：计量与韧性事件同源，合并落库避免双写；驾驶舱（008）查询 token_usage_logs 即可聚合。

