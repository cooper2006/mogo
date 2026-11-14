# Contract: LLM Gateway Resilience (007)

**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md) | [tasks.md](../tasks.md)

本契约定义 LLM 网关韧性的对外接口：failover 调度、降级链、退避重试、韧性事件。实现见 `services/chat-api/app/llm/resilience/`。

---

## 1. 组件

| 模块 | 职责 |
|---|---|
| `errors` | 错误分类：可重试（429/5xx/408/timeout/连接）vs 不可重试（401/403） |
| `retry` | tenacity 指数退避 + 抖动（默认 1.5s/30s/±10%/3 次） |
| `failover` | `ResilientLLMClient` 主→备供应商调度 |
| `degradation` | 模型档位降级链（高→中→轻） |
| `events` | 韧性事件落 `token_usage_logs` 附加字段 |
| `providers` | 从声明式配置构建 provider 列表 |

---

## 2. 错误分类契约

```
可重试：HTTP 408/409/425/429/500/502/503/504、asyncio.TimeoutError、ConnectionError/OSError
不可重试：HTTP 401、403
未知异常：按可重试处理（fail-open on retry）
```

| 异常类 | 语义 |
|---|---|
| `RetryableLLMError` | 瞬时失败：退避重试 / 切备 |
| `NonRetryableLLMError` | 永久失败：立即抛出，**不重试、不 failover** |
| `AllProvidersFailedError` | 全部 provider 失败，聚合各失败原因 |

---

## 3. failover 契约（ResilientLLMClient）

```python
ResilientLLMClient(
    providers=[ProviderEntry(name, factory, retry_policy), ...],
    on_event=callable,          # 接收韧性事件 dict
)
```

行为：
- 按 providers 顺序尝试；**可重试失败 → 切下一个 provider** 并发 `failover` 事件
- **不可重试失败 → 立即抛出**（不切备）
- 全部失败 → `AllProvidersFailedError`，`.failures` 含每个 provider 的原因
- **单 provider = 严格 no-op**（行为与现状一致，FR-9）
- 流式：仅在**首块之前**失败才切备（已出 token 则不再切，避免重复输出）
- `.last_result: FailoverResult`（provider/attempts/failed_providers/log_fields）

---

## 4. 退避契约（RetryPolicy）

```python
RetryPolicy(base_seconds=1.5, max_seconds=30.0, max_attempts=3, jitter_seconds=0.15)
```

沿用既有 `azure_gpt_image` 的参数，避免行为漂移。`retry_with_backoff(op, policy, on_retry)`：
- 可重试 → 退避重试至成功或耗尽
- 不可重试 → **立即抛出**（零等待）
- 耗尽 → 重抛最后错误

---

## 5. 降级链契约（DegradationChain）

```python
chain = build_chain(["high","mid","light"], models={"high":"gpt-5.4"})
output, result = await run_with_degradation(chain, caller, on_event=...)
```

- `caller(step) -> Any` 抛可重试错误 → **降下一档**并发 `degradation` 事件
- 不可重试错误 → 立即中止
- **链耗尽 → `DegradationError`**（含每档失败原因，绝不静默返回空，FR-2）
- `DegradationResult`：tier/model/step/degraded/log_fields

---

## 6. 韧性事件契约（落 token_usage_logs 附加字段）

不新增 collection，事件作为**附加字段**合并进既有用量日志：

| 字段 | 含义 |
|---|---|
| `resilience_event` | `failover` \| `degradation` \| `retry` |
| `failover_from` / `failover_to` | 切换前/后 provider |
| `degradation_step` | 命中的降级档序号（1-based） |
| `degradation_reason` | 枚举：`429` \| `5xx` \| `timeout` \| `manual` |
| `attempt` | 尝试序号 |

---

## 7. 声明式配置（app/config/resilience.yaml）

```yaml
providers:                # 有序：首个为主，其余为备（可省略 → 单 provider）
  - {name: primary, kind: default, model: gpt-5.2}
  - {name: backup,  kind: azure,   model: gpt-5.2}
retry:
  base_seconds: 1.5
  max_seconds: 30.0
  max_attempts: 3
  jitter_seconds: 0.15
```

**缺省行为**：配置缺失或未声明 providers → **回退单 provider = 现状行为**（FR-9）。

---

## 8. 范围界定

- **仅文本 LLM 调用**；图像生成保持 `azure_gpt_image` 自身重试（clarify OQ-3）
- 节点级重试由 010 承载，**包裹** 007 的模型级重试（不重复退避，010 FR-5）
