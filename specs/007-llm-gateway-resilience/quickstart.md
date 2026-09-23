# Quickstart: LLM Gateway Resilience (007)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [contracts/resilience.md](./contracts/resilience.md)

本文件说明如何**启用并验证** LLM 网关韧性。

---

## 1. 前置

- chat-api 服务（`services/chat-api`）
- 依赖 `tenacity>=8.3.0`（已在 `requirements.txt`，无需新增）
- **仅文本 LLM**（图像走 `azure_gpt_image` 自身重试）

---

## 2. 启用 failover（可选）

编辑 `services/chat-api/app/config/resilience.yaml`，声明 provider 顺序：

```yaml
providers:
  - {name: primary, kind: default, model: gpt-5.2}
  - {name: backup,  kind: azure,   model: gpt-5.2}
```

**不配置即保持现状**（单 provider，零行为变化）。

---

## 3. 使用

```python
from app.llm.resilience import (
    ResilientLLMClient, ProviderEntry, RetryPolicy,
    build_chain, run_with_degradation,
)

# failover
client = ResilientLLMClient([
    ProviderEntry("primary", lambda: build_client("gpt-5.2")),
    ProviderEntry("backup",  lambda: build_client("gpt-5.2"), RetryPolicy()),
], on_event=log_event)
resp = await client.ainvoke(messages)

# 降级链
chain = build_chain(["high", "mid", "light"], models={"high": "gpt-5.4"})
output, result = await run_with_degradation(chain, lambda step: call_model(step.model))
if result.degraded:
    ...  # 记录降级到 result.tier
```

---

## 4. 验证清单

| # | 验证项 | 期望 |
|---|---|---|
| 1 | 主供应商 500 | 自动切备成功，发 `failover` 事件 |
| 2 | 主备均失败 | `AllProvidersFailedError`（含各 provider 原因） |
| 3 | 主供应商 401 | **立即抛出，不切备** |
| 4 | 单供应商 | 严格 no-op（调用次数 = 1） |
| 5 | 429 重试 | 退避后成功（默认 3 次） |
| 6 | 降级链逐档 | 高档失败 → 中档成功（`degradation_step=2`） |
| 7 | 降级链耗尽 | `DegradationError`（明确报错，不静默） |

---

## 5. 单元测试（无需 DB/网络）

```bash
cd services/chat-api
PYTHONPATH=. python -m pytest tests/llm/test_resilience.py -o asyncio_mode=auto -q
```

期望：**25 项全部通过**（错误分类、事件字段、failover、单 provider no-op、全失败聚合、401 不 failover、退避重试、降级链、配置解析）。

---

## 6. 事件观测

韧性事件落 `token_usage_logs` 附加字段（`failover_from`/`failover_to`/`degradation_step`/`degradation_reason`），可由 008 运营驾驶舱消费归因。
