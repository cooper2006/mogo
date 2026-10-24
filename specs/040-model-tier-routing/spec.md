# Feature Specification: 模型分层路由（复杂度评估 → 轻量/主力/旗舰三档）

**Feature Branch**: `040-model-tier-routing`

**Created**: 2026-10-23

**Status**: Draft

**Input**: User description: "把 LLM 调用按任务复杂度路由到轻量/主力/旗舰三档模型——简单任务走轻量（成本↓80%）、复杂推理走旗舰、主模型超时或异常时自动切备用；与 007 故障降级链分工：路由管'选谁最划算'，降级管'谁挂了谁顶'"

> **设计来源**：本规约落地《docs/MOGO-AgentOS整合方案.md》§4.9（模型分层路由，对应文章成本治理三抓手②，见整合方案 §2.4）。整合方案基线：31 个 SDD 特性（specs/001–031）+ 代码级核实（2026-10-23）。
>
> **性质说明**：**全新特性，代码尚未开工**——`ModelRouter` 现无任何复杂度评估逻辑、`model_routing.yaml` 配置文件缺失；本文件为 spec → plan → tasks 先行，后续按 tasks.md 实现。

## 定位（一句话）

在既有 `ModelRouter` 静态优先级链之后新增一层**按任务复杂度选档**的路由：评估器基于可计算特征（长度/工具数/多轮/阶段意图/显式声明）把请求落入 **light（轻量）/ mid（主力）/ high（旗舰）** 三档之一，档位经 `model_routing.yaml` 的 `tiers` 映射（租户可覆盖）落到 031 已配置的具体模型；评估异常或映射缺失时安全回退默认档位并告警，与 007 降级链**串行**协作（先选档，调用失败再降级）。

## 背景事实（代码级核实，2026-10-23）

| 事实 | 证据 |
| --- | --- |
| ModelRouter 为静态优先级映射，无任何复杂度评估逻辑 | `services/chat-api/app/llm/model_router.py:20-115`（explicit > task_override > by_node > by_stage > by_intent > env > fallback） |
| 路由配置文件缺失，路由实际落 env 兜底 | `services/chat-api/app/config/` 仅有 `resilience.yaml`；`model_routing.yaml` 不存在 → `_load_config()` 返回 `{}` → 落 `env:*` / `config_fallback` |
| 唯一调用方为 LLM 工厂，且已有 `model_routed` 埋点 | `services/chat-api/app/llm/factory.py`（`get_llm_client()` → `get_model_router().resolve(...)` + `log_trace(event="model_routed")`） |
| 007 的 high/mid/light 是**故障降级链**（上一档失败才下移），不是路由 | `services/chat-api/app/llm/resilience/degradation.py:21` `DEFAULT_DEGRADATION_CHAIN=("high","mid","light")` |
| 007 韧性事件以附加字段落 `token_usage_logs`，不新增 collection | `services/chat-api/app/llm/resilience/events.py`（`as_log_fields()` 模式） |

## 已定决策（2026-10-23）

| # | 决策点 | 结论 | 落点 |
| --- | --- | --- | --- |
| 1 | 复杂度评估算法 | **规则法**（可计算特征的阈值/加权评分），**不用 LLM 自评**——控制不确定性与额外调用成本；规则阈值可在 yaml 调整 | `app/llm/complexity.py` 纯函数 |
| 2 | 档位数与命名 | **三档：light（轻量）/ mid（主力）/ high（旗舰）**；档位词与 007 降级链 `("high","mid","light")` 对齐，使降级链可直接作用于路由结果 | `app/llm/model_router.py` |
| 3 | 映射配置形态 | **`model_routing.yaml`**：`tiers` 段定义三档→模型（取值 = 031 已配置模型 ID），`tenants.<tenant_id>.tiers` 段做租户覆盖；**首期不做 admin-web 配置页**——先例：007 的降级链同样由 `resilience.yaml` 承载、无 UI；文件 mtime 热加载复用 `ModelRouter._load_config` 既有机制 | `app/config/model_routing.yaml` |
| 4 | 与 007 的串行边界 | **路由失败 ≠ 降级触发条件**：040 只决定"选哪档的模型"；所选档位模型调用失败（429/5xx/超时）才由 007 降级链沿链下移。040 的"失败"仅指评估器异常/映射缺失（落默认档位 + 告警），不进入 007 的错误分类 | `model_router.py` 与 `resilience/degradation.py` 边界 |
| 5 | 兜底策略 | 评估器异常或 `tiers` 映射缺失 → **落默认档位 mid**；mid 也未映射 → 既有 `env:*` / `config_fallback`；全程记录告警，**不静默失败** | `model_router.py` + `log_print` / `log_trace` |
| 6 | 静态映射先行 | 随本特性补建 `model_routing.yaml`，把既有优先级链的静态映射段（`by_node`/`by_stage`/`by_intent`/`models`/`fallback_model`/`enabled`）以注释默认值落地，修复配置缺失现状 | `app/config/model_routing.yaml` |
| 7 | 历史档位表现 | **首期不作为评估输入**（需 007 计量数据回流，属二期）；首期特征全部可从调用上下文直接计算 | `app/llm/complexity.py` |
| 8 | 优先级链兼容 | 复杂度评估插入在既有链的 `by_intent` 之后、`env` 之前：`explicit > task_override > by_node > by_stage > by_intent > **tier** > env > fallback`；`explicit` 与 `USE_QWEN` 旁路行为不变 | `model_router.py:30-87` |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 请求按复杂度落入轻量/主力/旗舰档位（Priority: P1）

一次对话/Agent 调用进入 chat-api 时，复杂度评估器基于可计算特征给出档位：简单问答落 light、常规任务落 mid、复杂推理/编码落 high；评估为**纯函数**，单测覆盖边界（空输入/极短/极长/工具数/多轮/显式声明）。

**Why this priority**: 这是特性核心价值——成本治理三抓手之一（整合方案 §2.4），"简单任务走轻量（成本↓80%）"是成本下降的主要来源；没有评估器，分层路由无从谈起。

**Independent Test**: `services/chat-api/tests/llm/test_model_tier_routing.py` 对评估函数逐项断言：单轮短问答无工具 → light；多轮长上下文多工具 → high；显式声明 → 尊重声明；输入缺省/异常 → mid + 告警不抛错。

**Acceptance Scenarios**:

1. **Given** 单轮短消息且本轮无工具，**When** 评估，**Then** 落 light。
2. **Given** 多轮长上下文且本轮工具数 ≥ 阈值，**When** 评估，**Then** 落 high。
3. **Given** `output_spec` 显式声明 `complexity=high`，**When** 评估，**Then** 尊重显式声明落 high（显式优先于规则评分）。
4. **Given** 评估输入缺省或评估器抛异常，**When** 评估，**Then** 落默认档位 mid 并记录告警，请求链路不中断。

---

### User Story 2 - 三档路由与档位映射配置（Priority: P1）

档位经 `model_routing.yaml` 的 `tiers` 段映射到 031 已配置的具体模型；映射支持按租户覆盖；映射缺失或目标模型未配置时安全回退（默认档位 → env/config_fallback）并告警，不静默失败。

**Why this priority**: 没有档位→模型映射，评估出的档位无法变成真实调用；映射是租户按自己模型账单调配的成本杠杆（"档位与模型配置的映射租户可配"）。

**Independent Test**: 构造含 `tiers` 段的 yaml，断言 `resolve()` 返回对应模型且 `source=tier:<tier>`；删 `tiers` 段后断言回退默认档位且日志有告警；配置 `tenants.<tid>.tiers` 覆盖后断言该租户命中覆盖值。

**Acceptance Scenarios**:

1. **Given** `tiers.light` 指向某轻量模型 ID，**When** 评估为 light 的请求经 `resolve`，**Then** 返回该模型且 `source` 标记 `tier:light`。
2. **Given** 配置了 `tenants.<tenant_id>.tiers` 覆盖段，**When** 该租户的请求，**Then** 命中覆盖映射而非全局 `tiers`。
3. **Given** `tiers` 段缺失或某档未配置模型，**When** 请求，**Then** 落默认档位（mid）映射；mid 也未配置时落既有 `env:*` / `config_fallback`，且记录告警（不静默失败）。
4. **Given** `USE_QWEN` 单模型部署，**When** 请求，**Then** 行为与现状一致（`provider_default:qwen`），不进评估器、不分层。

---

### User Story 3 - 补建 model_routing.yaml 静态映射先落地（Priority: P2）

新建 `app/config/model_routing.yaml`，把 `ModelRouter` 既有优先级链的静态映射配置载体（`by_node`/`by_stage`/`by_intent`/`models`/`fallback_model`/`enabled`）以注释默认值落地，修复配置文件缺失现状。

**Why this priority**: 配置缺失导致优先级链形同虚设（永远落 env 兜底）；先补文件让静态映射可用，是分层路由的载体前提。优先级低于 US1/US2，因为它不改变"选谁"的智能程度，只恢复既有设计意图。

**Independent Test**: 放置含 `by_stage` 的 yaml，断言对应 stage 请求命中 `by_stage`（`source=by_stage`）；删除文件后 `resolve` 回到 `env:*` / `config_fallback`（既有行为回归）。

**Acceptance Scenarios**:

1. **Given** yaml 含 `by_stage: {coding: <model>}`，**When** coding 阶段请求，**Then** 命中该模型（`source=by_stage`）。
2. **Given** yaml 含 `enabled: false`，**When** 请求，**Then** 落 `settings.OPENAI_MODEL`（`source=disabled_fallback`，既有行为）。
3. **Given** 文件不存在，**When** 请求，**Then** 行为与现状一致（`env:*` / `config_fallback`），不报错、不中断。

---

### User Story 4 - 路由决策可观测（Priority: P2）

每次路由决策（档位、特征摘要、命中模型、source）落 `log_trace`，并在 `token_usage_logs` 以附加字段记录 `tier`，使 008 驾驶舱可按档位统计调用量与成本。

**Why this priority**: 不可观测的分层路由无法验证成本收益，也无法喂给 008/035。优先级 P2，因为 US1–US3 已构成可用的 MVP 路由链路。

**Independent Test**: mock 一次调用，断言 `log_trace` 的 `model_routed` 事件含 `tier` 与特征摘要；断言 usage log 行含 `tier` 附加字段（不新增 collection）；008 侧按 `tier` 分组聚合做契约级验证。

**Acceptance Scenarios**:

1. **Given** 一次分层路由调用完成，**When** 查 trace，**Then** `model_routed` 事件含 `tier` 与特征摘要（长度/工具数/多轮等）。
2. **Given** 计量上报发生，**Then** `token_usage_logs` 附加字段含 `tier`（light/mid/high），复用 007 附加字段模式、不新增 collection。
3. **Given** 008 聚合查询，**Then** 可按 `tier` 分组统计调用量与估算成本。

---

### Edge Cases

- **评估器抛异常**（特征缺失/类型错误）：MUST 被 try/except 包裹，落默认档位 mid + 告警，请求链路不中断（不静默失败）。
- **档位映射指向未在 031 配置的模型**：回退默认档位（mid）→ 再落 `env:*` / `config_fallback`，并告警；不把未知模型 ID 透传给 provider。
- **`explicit_model` 显式传入**：优先级最高，不走复杂度评估（保持既有 `explicit` 语义）。
- **`configured_model` 直连路径**（`output_spec`/请求上下文已带配置模型）：不经 `ModelRouter`，行为不变（`factory.py` 既有分支）。
- **`USE_QWEN` 单模型**：直接返回 `provider_default:qwen`，不进评估器（既有早返回）。
- **超长输入**（超过长度阈值）：规则评分落 high；**空输入**：按最短特征处理（落 light），不崩溃、不阻断。
- **租户覆盖指向的模型被 031 下线/删除**：回退默认档位 + 告警。
- **yaml 损坏（语法错误）**：`_load_config` 既有 try/except 吞掉返回 `{}`，落 env 兜底 + 告警（既有行为保持，不新增失败模式）。
- **降级后的档位与路由档位不一致**：007 降级沿 `("high","mid","light")` 下移与 040 路由结果档位词一致，usage log 同时记 `tier`（路由档位）与 `degradation_step`（降级档位），二者不互相覆盖。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 提供任务复杂度评估**纯函数模块**（输入为调用上下文特征，输出为三档之一），无 IO、可独立单测。
- **FR-002**: 首期评估特征 MUST 至少覆盖：请求长度（字符数）、可用工具数、是否多轮、阶段/意图、显式复杂度声明（`output_spec.complexity`）；历史档位表现 MUST NOT 作为首期输入（留二期）。
- **FR-003**: 评估算法 MUST 为规则法（阈值/加权评分），MUST NOT 调用 LLM 自评复杂度（控制不确定性与成本）。
- **FR-004**: 档位体系 MUST 为三档：`light`（轻量）/ `mid`（主力）/ `high`（旗舰），命名 MUST 与 007 降级链档位词对齐。
- **FR-005**: 档位→模型映射 MUST 由 `model_routing.yaml` 的 `tiers` 段声明，取值 MUST 引用 031 已配置模型；MUST 支持按租户覆盖（`tenants.<tenant_id>.tiers`）。
- **FR-006**: 档位映射缺失或目标模型未配置时，路由 MUST 安全回退（默认档位 mid；mid 也未配置时落既有 `env:*` / `config_fallback`）并记录告警，MUST NOT 静默失败。
- **FR-007**: `ModelRouter.resolve` MUST 保持既有优先级链兼容：`explicit > task_override > by_node > by_stage > by_intent > tier > env > fallback`；`USE_QWEN` 早返回与 `explicit` 最高优先语义 MUST 不变。
- **FR-008**: 系统 MUST 新建 `app/config/model_routing.yaml`，承载静态映射段（`by_node`/`by_stage`/`by_intent`/`models`/`fallback_model`/`enabled`）与档位映射段（`tiers`/`tenants`），默认值以注释给出。
- **FR-009**: 路由决策 MUST 可观测：`log_trace` 的 `model_routed` 事件 MUST 增补 `tier` 与特征摘要；`token_usage_logs` MUST 以附加字段记录 `tier`（复用 007 `as_log_fields()` 模式，不新增 collection）。
- **FR-010**: 040 与 007 MUST 串行协作：040 选档 → 调用失败 → 007 降级链接管沿链下移；040 的"失败"（评估异常/配置缺失）MUST NOT 作为 007 降级触发条件，007 既有降级链与触发条件 MUST 保持不变。
- **FR-011**: `configured_model` 直连路径与 `USE_QWEN` 路径 MUST 保持现状（不进评估器、不分层）。
- **FR-012**: 评估器异常 MUST 被捕获并落默认档位 + 告警，请求链路 MUST NOT 中断。

### Key Entities

- **TaskComplexityFeatures**: `{prompt_chars, tool_count, multi_turn, stage, intent, declared_complexity}`——首期可计算特征输入（plan.md 给出完整清单与阈值）。
- **ModelTier**: `light | mid | high` 三档枚举（产品名：轻量/主力/旗舰）。
- **TierMapping**: `{tiers: {light: model, mid: model, high: model}, tenants: {<tenant_id>: {tiers: {...}}}}`——档位→模型映射（yaml，租户可覆盖）。
- **RoutingDecision**: `{model, tier, source, features_summary}`——路由决策记录；`source` 在既有取值（`explicit`/`by_stage`/`env:*`/`config_fallback` 等）基础上新增 `tier:<tier>`。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 评估函数边界单测全覆盖（空/短/长/多工具/多轮/显式声明/异常），档位判定与规则文档一致。
- **SC-002**: 同一请求改换特征可落入不同档位（短问答 → light、编码多轮 → high），档位分布符合预期。
- **SC-003**: 档位映射缺失/评估异常时 100% 安全回退且告警可查，0 静默失败。
- **SC-004**: 007 既有韧性测试套件（`tests/llm/test_resilience.py`、`test_resilience_metering.py`、`test_resilience_wiring.py`）全绿，降级链行为 0 回退。
- **SC-005**: `ModelRouter` 既有优先级链回归 0 破坏（`explicit`/`by_stage`/`by_intent`/`env:*`/`config_fallback`/`disabled_fallback` 语义不变）。
- **SC-006**: 调用链可按 `tier` 统计调用量与估算成本（`log_trace` 事件 + `token_usage_logs` 附加字段双落地）。

## Assumptions

- 首期采用规则法评估；LLM 自评复杂度留二期（需先验证不确定性与成本）。
- 档位词与 007 降级链对齐（`high`/`mid`/`light`），降级链可对任一路由档位生效，无需转换层。
- 模型单价沿用 007 `pricing.py` 与既有估算成本链路，040 不重复实现计价。
- 映射配置形态与 007 `resilience.yaml` 一致（部署级配置文件 + 租户分段覆盖，无 admin-web UI；租户日常"选模型"已由 031 模型配置页覆盖）。
- 评估特征全部来自调用上下文（请求上下文 / `output_spec` / 消息体），不引入外部服务。
- 历史档位表现需 007 计量数据回流后二期接入，首期不做（决策 7）。

## 跨特性关系（被依赖方视角，双向声明）

- **与 007（llm-gateway-resilience）**：**分工**——路由管"选谁最划算"，降级管"谁挂了谁顶"；**串行**：040 先选档，所选档位调用失败由 007 降级链沿 `("high","mid","light")` 下移（`resilience/degradation.py:21`）。007 的降级链、触发条件与事件字段（`degradation_step`/`degradation_reason`）MUST 保持不变；040 的失败（评估异常/映射缺失）不是 007 的降级触发条件。档位词对齐使降级链可直接作用于路由结果，无需档位转换。
- **与 031（model-provider-discover）**：040 的 `tiers` 映射取值 MUST 引用 031 管理的模型配置（`tiers.light/mid/high` 的值 = 031 已配置模型 ID）；031 的模型发现与配置管理是映射取值的来源，040 不重复管理模型生命周期。
- **与 008（ops-dashboard）**：040 落地的 `tier` 附加字段与 `model_routed` trace 事件，是 008 驾驶舱"按档位统计调用量与成本"的数据来源；008 侧新增 tier 维度属 008 的扩展，040 只保证数据落地（FR-009）。
- **与 035（成本归集补维，规划中）**：040 的档位计量是 035 按模型维度归集的数据来源之一；035 未立项前，档位数据先经 008 既有看板消费。

## 判定口径补充（2026-10-24，/speckit-checklist 回填）

> 回填依据：2026-10-24 代码级核查确认本特性**首期未实现**——`services/chat-api/app/llm/complexity.py` 不存在、`services/chat-api/app/config/model_routing.yaml` 不存在（`_load_config()` 走 `FileNotFoundError` 返回 `{}`）、`ModelRouter.resolve()` 无 tier 级、`services/chat-api/app/llm/factory.py` 无 tier 埋点、`services/admin-api/` 无任何档位映射路由。以下 R 条为**可执行需求口径**（常量、字段名、判定顺序、状态机、边界行为），不是已存在的实现描述；括号中的落点文件为建议落点。

- **R-1 评估输入契约与缺省语义**：`TaskComplexityFeatures = {prompt_chars: int, tool_count: int, multi_turn: int, stage: str, intent: str, declared_complexity: str, features_supplied: bool}`；纯函数 `evaluate_tier(features, thresholds) -> ModelTier`（无 IO、不读配置）。取值来源：`stage`/`intent` 用 `resolve()` 既有形参；`declared_complexity` 用 `output_spec["complexity"]`；`prompt_chars`/`tool_count`/`multi_turn` **由调用方显式传入**——`ModelRouter.resolve()` 与 `get_llm_client()` 各新增三个关键字参数 `prompt_chars: int = 0`、`tool_count: int = 0`、`multi_turn: int = 0`，未传时按 0 处理且 `features_supplied=False`（`services/chat-api/app/llm/model_router.py`、`factory.py`、`complexity.py`）。
- **R-2 `tiers` 取值标识与 client 构造路径**：`tiers` 取值 = **031 模型实例 ID**（`admin_model_instances._id` 的 24 位小写 hex 字符串），**不是** provider 的 `model_name`。`ModelSelection` 新增字段 `model_config_id: str = ""`：命中档位时 `source=f"tier:{tier}"`、`model_config_id` = 实例 ID，`model` 填 `""`（不伪造——同步 `resolve()` 不查库，拿不到 `model_name`），真实模型名由 `InstrumentedLLMClient` 从 `provider_meta["model_name"]` 回填到 usage log，trace 里以 `model_config_id` 标识。`get_llm_client()` 见 `model_config_id` 非空即走 `build_llm_client_from_config`（或 async 场景的 `get_llm_client_by_model_id`），**禁止**把 24 位 ObjectId 当 `model_name` 传给 `DefaultOpenAIClient`（否则 provider 400）。
- **R-3 `tenant_id` 来源与档位查找顺序**：`tenant_id` 取 `output_spec["tenant_id"]` → `output_spec["tenantId"]` → `"default"`（与 `services/chat-api/app/token_usage` 的 `resolve_tenant_id` 同序；`get_llm_client()` 已把请求上下文 merge 进 `output_spec`，无需给 `resolve()` 加形参）。档位查找状态机：`tenants.<tid>.tiers.<tier>` 命中即用 → 否则 `tiers.<tier>` → 否则按 R-7 回退默认档位 `mid` 再查一次 → 仍未命中则落既有 `env:*` / `config_fallback`。
- **R-4 `tiering.thresholds` 段与缺省常量**：`tiering.thresholds` **属 040 交付物**，随 `model_routing.yaml` 一并落地（FR-008 的段清单据此补一项）。缺省常量在 `complexity.py` 定义为 `DEFAULT_TIERING_THRESHOLDS`：`prompt_chars_high=4000`、`tool_count_high=8`、`multi_turn_high=4`、`high_stages=("coding",)`、`high_intents=("coding",)`；yaml 提供该段时**逐键浅合并覆盖**（缺键用常量，不整体替换）。评分常量：`TIER_SCORE_HIGH=2`、`TIER_SCORE_MID=1`（每命中一项高分特征计 1 分，`score>=2 → high`、`score==1 → mid`、`score==0 → light`）。
- **R-5 告警 code 闭集与落点**：告警统一 `log_print(f"[llm.tier_routing] {code} ...", flush=True)` + `log_trace(trace_id=..., scope="llm.model_router", event="tier_routing_fallback", code=..., tier=..., source=...)`；code 闭集 6 个：`features_absent`、`evaluator_error`、`tiers_missing`、`tier_absent`、`model_config_missing`、`yaml_invalid`（`yaml_invalid` 复用 `_load_config` 既有 try/except，只加 code 不改行为）。告警**不写** `token_usage_logs`（token 计量与路由链路解耦，不新增 collection）；SC-003 的"告警可查"判据 = trace 事件可按 `code` 过滤。
- **R-6 空输入与特征缺省的区分**：`features_supplied=False`（调用方完全未提供上下文特征）→ 落 `mid` + 告警 `features_absent`；`features_supplied=True` 且 `prompt_chars==0 && tool_count==0 && multi_turn==0`（确有输入但为空/极短）→ score=0 → `light`。二者由 `features_supplied` 显式区分，消除 Edge Cases"空输入落 light"与 AC4"缺省落 mid"的冲突。
- **R-7 判定全序（优先级从高到低）**：① `USE_QWEN` → `provider_default:qwen`（不进评估器，`model_router.py:46-47` 既有早返回）② `explicit_model` → `explicit` ③ `configured_model` 存在 → 不进 `resolve()`（`factory.py:77-89` 既有分支，判据见 R-13）④ `output_spec["complexity"]` ∈ {`light`,`mid`,`high`} → 直接采用 ⑤ 规则评分（R-4）⑥ 异常/缺省 → `mid`（R-6）。`declared_complexity` 非法值（非三档、大小写混杂、含空白）→ 静默忽略并按规则评分，trace 记 `declared_complexity_ignored`，**不抛错**；不读 `output_spec["task_config"]["complexity"]` 等别名。
- **R-8 `source` 闭集与回退记法**：`source` 只新增三个值 `tier:light` / `tier:mid` / `tier:high`（**不新增** `tier_fallback` 之类新形态，避免 008/审计按前缀解析档位时值膨胀）。回退不改取值形态：tiers 缺失但 mid 命中 → `source="tier:mid"`，并在 trace 追加 `tier_fallback_from=<评估档位>`；mid 亦未命中而落 `env:*` / `config_fallback` / `disabled_fallback` → `source` 保持既有取值，**不写** `tier:*`。另：`model_routed` 事件现仅在 `output_spec` 非空时发出（`factory.py:100`），040 需把该条件放宽为"只要进入 `resolve()` 命中 tier 级就发"（无上下文调用点也要有 trace），否则 FR-009 覆盖不全。
- **R-9 `tier` 与 `tier_declared` 的记法**：`tier` = **实际服务档位**（light/mid/high）；`tier_declared` = 评估器原始结果，**仅当与 `tier` 不一致且非空**时写入。未分层路径（`configured_model` 旁路、`USE_QWEN`、`env:*`/`config_fallback`）`tier` 为 `""`，**不伪造** `mid`（否则 008 档位分布虚高）。理由：008 按档位统计调用量与成本，必须记实际档位。
- **R-10 `tier` 在 `token_usage_logs` 的落点**：`TokenUsageRecord` 新增两个**顶层字段** `tier: str = ""`、`tier_declared: str = ""`（与 `model_name` 同级，`services/chat-api/app/token_usage/models.py`），**不放进** `resilience_events`——该 dict 由 `instrumented_client.py` 的 `resilience_extras` 从 `provider_meta` 过滤 `failover_from`/`failover_to`/`degradation_step` 三键生成，混入 tier 会破坏 007 的字段语义。写入点：`InstrumentedLLMClient` 构造 `TokenUsageRecord` 处，取值 `str(output_spec.get("model_tier") or "")` / `str(output_spec.get("model_tier_declared") or "")`；`get_llm_client()` 在 `resolve()` 之后把这两个键写回 `output_spec`（传的是同一 merged dict）。`tier` 与 `degradation_step` 并存不互相覆盖（Edge Cases 要求）。
- **R-11 008 按档位聚合的消费路径**：走 `attribute_cost(rows, dimension="tier", dimension_of=lambda r: r.get("tier") or "")`（`services/admin-api/app/api/dashboard_metrics.py:297`，未分配落 `未分配` 桶、不伪造）。`services/chat-api/app/llm/resilience/metering.py` 的 `aggregate_usage` 维度白名单**首期不扩** tier：传 `dimension="tier"` 会被静默归一为 `model`——此为已知限制，若后续要走 metering 路径需显式加白名单 + 单测，不属 040 范围。
- **R-12 031 校验时点与手段**：`resolve()` **保持同步纯函数、不做 DB 校验**（无法 await）。它只做形态校验：`tiers` 取值非空且匹配 `^[0-9a-f]{24}$`，否则视为映射缺失（走 R-7 回退，不尝试 DB）。真伪校验（实例存在 + 属该 `tenant_id` + `status=="active"` + capability 含 `chat`）下沉到 client 构造层：`get_llm_client_by_model_id(model_config_id, tenant_id=...)` / `build_llm_client_from_config` 返回 None 或抛 `ModelConfigError` → factory 捕获 → 回退默认档位 `mid` 映射 → 再回退 `env:*`/`config_fallback` + 告警 `model_config_missing`。首期**不加缓存**（每调用一次查询，031 侧已有 `priority`/`health_status` 语义，不引入新缓存层）；`model_config_missing`（031 侧查无）与 `tiers_missing`（yaml 侧缺失）在告警 code 上区分。
- **R-13 旁路顺序写死**：`get_llm_client()` 的顺序不可变——先取 `output_spec["configured_model"]`，无则取 `get_configured_model_context()`，非空即直连 `build_llm_client_from_config` 并 **return**（现行 `factory.py:77-89`，在 `resolve()` 之前）；随后 `resolve()` 内第一句为 `USE_QWEN` 早返回。040 只允许在 `by_intent` 之后、`env` 之前插入 tier 级，不改这两处顺序与位置。"不进评估器"的判据 = 不调用 `evaluate_tier`、不读 `tiers`/`tenants` 段、usage log 的 `tier` 为空串。
- **R-14 静态映射段与 `tiers` 的共存语义**：决策 #8 的优先级**不变**——`by_node`/`by_stage`/`by_intent` 命中即返回，不再评估档位。为此补一条可观测口径：静态段命中时 `model_routed` 事件记 `tier=""` 且 `tier_skipped_reason="static_mapping_hit"`，使"因静态映射覆盖而未分层"在 trace 中可见（否则租户无法判断分层是否生效）。若租户要分层优先，运维动作 = 删除/注释对应静态段条目；本期**不提供**优先级开关（与 Non-Goals"不做 admin-web 档位映射配置页"一致）。
- **R-15 `prompt_chars` 度量口径**：`prompt_chars = len(最近一轮 user 消息文本) + len(系统提示文本)`，**不含**历史消息、工具 schema、响应内容；单位 = Unicode 字符数（`len(str)`，非字节、非 token）。无系统提示只计 user 部分；无 user 消息（如 `stage="compose"` 的内部调用）记 0。阈值比较一律用 `>=`（`prompt_chars >= 4000` 记 1 分），边界值含等号。
- **R-16 `multi_turn` 计数口径**：`multi_turn` = 当前会话历史中 **user + assistant 消息条数**（`>= 4` 记 1 分）；不是"轮次×2"、不按 token、不截断（只计条数，O(1)）。无 `session_id`/无会话上下文（平台内部单轮调用、`stage` 为 `admin_*` 等）记 `0`。

**验收证据**：本次核查了 `services/chat-api/app/llm/model_router.py`（全文，确认无 tier 级、`_load_config` 热加载与 `enabled`/`explicit`/`USE_QWEN` 现状）、`services/chat-api/app/llm/factory.py:63-115`（`configured_model` 分支在 `resolve()` 之前、`model_routed` 事件仅在 `output_spec` 非空时发出）、`services/chat-api/app/llm/configured_models.py:95-116/378-400`（031 模型实例 `_id` 与 async DB 查询）、`services/chat-api/app/token_usage/models.py`、`services/chat-api/app/llm/instrumented_client.py:150-220`、`services/chat-api/app/llm/resilience/{degradation,events,metering}.py`、`services/chat-api/app/infrastructure/request_context.py`、`services/chat-api/app/config/`（仅 `resilience.yaml`，`model_routing.yaml` 缺失）、`services/admin-api/app/api/routes/models.py`、`services/admin-api/app/api/dashboard_metrics.py:297`。测试：**该特性尚无实现与测试**（`services/chat-api/app/llm/complexity.py`、`services/chat-api/app/config/model_routing.yaml`、`services/chat-api/tests/llm/test_model_tier_routing.py` 均不存在，`grep ModelRouter services/chat-api/tests/` 零命中），未跑任何用例，回填为需求口径澄清。

- **R-17 分层生效入口（同步 / 异步双入口）**：031 的模型实例解析（`services/chat-api/app/llm/configured_models.py::get_llm_client_by_model_id`）是 `async`，而 `ModelRouter.resolve()` 是同步纯函数。因此：
  - 新增 `async def aget_llm_client(...)`（`services/chat-api/app/llm/factory.py`）作为**档位真正生效的入口**：`resolve()` → 命中 `model_config_id` → `await get_llm_client_by_model_id(...)`（该函数返回 `wrap_resilient(primary, backups)`，primary 已内含 `InstrumentedLLMClient`，即 007 韧性与计量一并生效）→ `_record_tier()` 写回 `model_tier`/`model_tier_declared` → `model_routed` trace。
  - 异步调用点（`async def` 内的 `get_llm_client(...)`）应迁移到 `aget_llm_client(...)`；首期至少迁移 `services/chat-api/app/context_engine/compactor.py::compact_messages` 作为端到端样本。
  - 迁移不改变任何既有行为：`aget_llm_client` 在非档位路径（静态映射/`use_qwen`/`explicit`/`configured_model`）回落同步 `get_llm_client`，优先级链与 R-13/R-14 完全一致。
- **R-18 同步入口的回退语义（诚实降级，不伪造）**：同步 `get_llm_client()` 在 `resolve()` 命中 `model_config_id` 后**无法** `await` 031 解析，处理方式固定为：发 `log_print("[llm.tier_routing] model_config_missing ...")` + `log_trace(event="tier_routing_fallback", code="model_config_missing")`，随后用 `resolve(..., skip_tiering=True)` 重新解析并走静态链（`models`/`env:*`/`config_fallback`）。该回退**不修改** R-7 的判定全序，`skip_tiering` 仅为本回退的内部开关、不对外暴露；回退后 `tier=""`（不写 `mid`），保证"未分层"在计量与 trace 中可见。同步调用点不会因为档位配置而被错误打上档位标签。

## Non-Goals

- 不用 LLM 自评复杂度（首期规则法，二期再评估）。
- 不改 007 降级链的语义、档位词与触发条件。
- 不做在线学习/自动调参（规则阈值首期人工设定、yaml 可配）。
- 不做 per-request 成本硬限流（配额归 001 门禁层）。
- 不做多模态/图像模型分层（与 007 clarify OQ-3 对齐：仅文本模型）。
- 不新增 LLM 供应商接入（作用于既有 providers）。
- 不做 admin-web 档位映射配置页（首期 yaml 承载，先例：007 `resilience.yaml`）。

## Further Details

- 技术实现（评估特征清单与阈值、yaml 结构、可观测接线）由 plan.md 承载。
- 历史档位表现作为评估输入的二期方案需 007 计量回流数据就绪后另行澄清。
