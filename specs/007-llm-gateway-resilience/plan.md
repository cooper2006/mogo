# Implementation Plan: LLM Gateway Resilience

**Branch**: `007-llm-gateway-resilience` | **Date**: 2026-07-08 | **Spec**: [spec.md](./spec.md)

**Input**: 缺口新特性。把规格技术化到既有 `llm/` 模块：failover 调度 + 降级链 + 指数退避 + 计量复用既有 `token_usage` 管线。

## Summary

在 `llm/model_router.py` 的 ModelRouter 之上引入**韧性调度层**：主/备供应商 failover（基于 providers）、degradation_chain 逐级降档、指数退避重试（区分可重试/不可重试错误），计量复用既有 `token_usage`（InstrumentedLLMClient + TokenUsageDispatcher + TokenUsageRepository）不重做。改动集中在 `llm/` 子模块，影响面可控（规划文档 §清单 2 明确"改动集中在 llm/model_router.py + providers 模块"）。

## Technical Context

**Language/Version**: Python 3.13（chat-api 既有栈）

**Primary Dependencies**: 既有 providers（azure_openai / azure_responses / azure_gpt_image / default_openai / qwen）+ 既有 token_usage 管线；新增 `tenacity`（指数退避，需 confirm 是否可用）或手写退避

**Storage**: 复用 token_usage_logs（计量）+ 新增 `llm_resilience_events`（failover/降级/重试事件，可选）

**Testing**: pytest（llm 既有测试 + failover/退避/计量单测 + 故障注入集成测试）

**Target Platform**: 自托管 Docker Compose

**Project Type**: 既有模块扩展（llm 韧性调度层）

## 现有实现事实（contract 依据）

- `llm/model_router.py`：`ModelRouter.resolve` 现有语义为"多供应商选择"（explicit > task_override > by_node > by_stage > by_intent > env > models > config_fallback），**无 failover/降级/退避**
- `llm/instrumented_client.py`：`InstrumentedLLMClient.ainvoke/astream/ainvoke_structured` 已做调用包装 + `consume_invocation_record`（计量钩子）
- `llm/providers/`：各 provider 客户端（failover 的"主/备"实现单元）
- `token_usage/`：`TokenUsageRecord` 模型 + `TokenUsageDispatcher`（异步队列 push）+ `TokenUsageRepository`（insert/mark_push_result）+ `sanitize.py`（payload 脱敏/截断）
- `llm/structured_fallback.py`：既有结构化输出降级（可作为 degradation_chain 的参考实现）

## Constitution Check

| 原则 | 结果 |
|---|---|
| I. Specification-First | 通过 |
| II. Production Readiness | 通过：failover/降级/退避是生产可用性直接收益 |
| III. Security | 通过：计量 payload 复用既有 sanitize 脱敏 |
| IV. i18n | 通过 |
| V. Observability | 通过：事件日志 + 计量可查 |

## Project Structure

```text
services/chat-api/app/
├── llm/
│   ├── model_router.py        # 既有：保留选择语义
│   ├── resilience/            # 新增子模块
│   │   ├── __init__.py
│   │   ├── failover.py        # 主/备供应商调度
│   │   ├── degradation.py     # 降级链（参考 structured_fallback）
│   │   ├── retry.py           # 指数退避 + 抖动 + 可/不可重试判定
│   │   ├── errors.py          # 韧性错误分类
│   │   └── events.py          # failover/降级/重试事件
│   └── providers/             # 既有：主/备实现单元
└── token_usage/               # 既有：计量管线复用
```

## Open Questions（已 clarify 消解）
- OQ-1 退避实现：**用 `tenacity>=8.3.0`（既有依赖，requirements.txt/pyproject 已含；azure_gpt_image.py 已用）**，非手写。
- OQ-2 默认参数：**退避基数 1.5s / 上限 30s / 抖动 ±10% / 可重试 429+5xx+超时 / 不可重试 401+403 / 最大重试 3（可配）**——沿用 azure_gpt_image 既有值，避免行为漂移。
- OQ-3 降级链范围：**仅文本模型**（图像走 azure_gpt_image 自身重试，见 spec Non-Goals）。
- OQ-4 事件落点：**复用 `token_usage_logs` 附加字段（failover_from/failover_to/degradation_step），不新增独立 collection**；008 驾驶舱直接聚合该表。

## 下一步
OQ 已 clarify 消解。`/speckit-checklist`（007 补需求质量门禁）→ `/speckit-tasks` → `/speckit-analyze` → `/speckit-implement` → `/speckit-converge`。
