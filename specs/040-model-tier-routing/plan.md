# Implementation Plan: 模型分层路由（040-model-tier-routing）

**Branch**: `040-model-tier-routing` | **Date**: 2026-10-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/040-model-tier-routing/spec.md`

**Note**: 本计划为**全新特性、代码尚未开工**的 spec → plan → tasks 先行流程（与 031 的"回溯补规格"不同）。冲突时以 spec.md 的 FR 为准。

## Summary

在 `ModelRouter` 既有静态优先级链之后新增一层**按任务复杂度选档**的路由：新建复杂度评估纯函数模块（规则法，输入长度/工具数/多轮/阶段意图/显式声明，输出 light/mid/high 三档），档位经新建的 `app/config/model_routing.yaml`（`tiers` 段 + `tenants` 覆盖段，取值引用 031 已配置模型）落到具体模型；评估异常/映射缺失安全回退默认档位（mid）并告警；路由决策经 `log_trace` 与 `token_usage_logs` 附加字段（复用 007 模式）可观测。与 007 降级链**串行**协作：路由管"选谁最划算"，降级管"谁挂了谁顶"，双方语义互不改动。

## Technical Context

**Language/Version**: Python 3.11+（chat-api，FastAPI + pydantic v2 生态，本特性不新增服务）

**Primary Dependencies**: 既有依赖零新增——`PyYAML`（`model_router.py` 已在用）、标准库（评估纯函数）；不引入 LLM SDK 新调用（规则法）

**Storage**: N/A（评估为纯函数不落库；配置走 `app/config/model_routing.yaml` 文件，mtime 热加载复用 `ModelRouter._load_config` 既有机制）

**Testing**: pytest（chat-api，`tests/llm/test_model_tier_routing.py` 新增；007 既有 `test_resilience*.py` 回归）

**Target Platform**: Docker Compose（chat-api 容器）；自托管 Linux/Docker

**Project Type**: web-service 内部能力扩展（chat-api `llm/` 层），无前端改动

**Performance Goals**: 评估为纯内存计算（微秒级），相对 LLM 调用延迟可忽略；配置热加载按 mtime 缓存，无重复 IO

**Constraints**: MUST 保持既有优先级链兼容（`explicit > task_override > by_node > by_stage > by_intent > tier > env > fallback`）；MUST NOT 改动 007 降级链；档位词 MUST 与 007 对齐（`high`/`mid`/`light`）；不得在 yaml 或日志中落凭证

**Scale/Scope**: 1 个新纯函数模块 + 1 个新配置文件 + 2 处既有文件扩展（`model_router.py` / `factory.py`）+ 1 个计量接线点；无 admin-web 改动

### 复杂度评估特征清单（首期，规则法）

评估输入全部来自调用上下文（`get_request_context()` / `output_spec` / 消息体），**无 IO、无 LLM 调用**：

| 特征 | 来源 | 初始阈值（可配，yaml `tiering.thresholds`） | 方向 |
| --- | --- | --- | --- |
| `prompt_chars` | 最近一轮用户消息 + 系统提示字符数 | ≥ 4000 记高分 | 越长越复杂 |
| `tool_count` | 本轮可用工具数 | ≥ 8 记高分 | 工具越多越复杂 |
| `multi_turn` | 会话历史消息轮数 | ≥ 4 轮记高分 | 多轮更复杂 |
| `stage` / `intent` | 调用上下文（`stage`/`intent` 参数） | `coding` / `research_query_refine` 等记高分；`chat` 记低分 | 阶段语义 |
| `declared_complexity` | `output_spec.complexity`（light/mid/high） | 显式声明**优先于**规则评分 | 人工兜底 |
| 历史档位表现 | `token_usage_logs` 回流 | **首期不接**（二期，决策 7） | — |

**初始规则**（权重与阈值可在 yaml 调整，先规则后调参）：

1. 显式声明 `declared_complexity` 非空 → 直接采用。
2. 否则按阈值打分：每满足一项高分特征计 1 分；`score ≥ 2` → `high`；`score == 1` → `mid`；`score == 0` → `light`。
3. 评估器异常（特征缺失/类型错误/未知 stage 映射）→ 落默认档位 `mid` + 告警（`log_print`），不抛错中断请求。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Specification-First**: ✅ 本 spec/plan/tasks 三件套先行，代码未开工；决策表先行拍板算法/档位/配置形态/串行边界/兜底五件事。
- **II. Enterprise Production Readiness**: ✅ 失败路径显式化（回退 + 告警，不静默）；复用既有配置热加载与 trace 埋点，不引入未验证组件；评估纯函数可完整单测。
- **III. Security and Data Protection**: ✅ 不引入新凭证面（映射取值引用 031 已配置模型，凭证管理不变）；yaml 与 trace 只落模型 ID/档位/特征摘要，不落 prompt 内容与凭证。
- **IV. Cross-Platform and i18n**: ✅ 无前端改动；yaml 注释与日志文案保持中英双语可读（档位产品名"轻量/主力/旗舰"与英文档位词并列）。
- **V. Observability and Simplicity**: ✅ 复用 `log_trace` + `token_usage_logs` 附加字段（007 既有模式，不新增 collection）；复杂度评估为单文件纯函数模块，无新架构分，符合 YAGNI。

## Project Structure

### Documentation (this feature)

```text
specs/040-model-tier-routing/
├── spec.md              # 特性规约（FR/SC/决策表）
├── plan.md              # 本文件
└── tasks.md             # 任务清单（全新特性，全部未勾选）
```

### Source Code (repository root)

```text
services/chat-api/
├── app/llm/complexity.py               # 【新增】复杂度评估纯函数（特征提取 + 规则阈值，无 IO）
├── app/llm/model_router.py             # 【复用/修改】resolve() 插入 tier 一级（by_intent 之后、env 之前），
│                                       #   保持既有优先级链兼容；新增 tier 映射解析与 source=tier:<tier>
├── app/llm/factory.py                  # 【复用/修改】model_routed log_trace 事件增 tier 与特征摘要
├── app/llm/resilience/events.py        # 【复用】附加字段模式（as_log_fields）——tier 字段追加到此模式，不改 007 语义
├── app/llm/resilience/metering.py      # 【复用】按维度聚合（008 消费档位统计的既有库函数）
├── app/config/model_routing.yaml       # 【新增】静态映射段（by_node/by_stage/by_intent/models/fallback_model/enabled）
│                                       #   + 档位映射段（tiers/tenants 覆盖）+ tiering 阈值段，注释默认值
└── tests/llm/test_model_tier_routing.py  # 【新增】评估函数边界 + 档位映射 + 回退告警 + 优先级链回归
```

**Structure Decision**: 完全复用 chat-api 既有 `llm/` 布局与配置目录约定（`resilience.yaml` 先例），不新增子项目、不新增依赖、不做 admin-web 页面（首期配置走 yaml，与 007 同形态）。档位映射引用 031 已配置模型，不重复建设模型管理。

## Complexity Tracking

> 无 constitution 违规，无需复杂度论证。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | — | — |
