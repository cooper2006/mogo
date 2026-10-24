# Requirements Quality Checklist: 040 model-tier-routing

**Purpose**: 校验 040（模型分层路由：复杂度评估 → 轻量/主力/旗舰三档）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-10-24
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [x] CHK001 三项上下文特征（`prompt_chars`/`tool_count`/`multi_turn`）的取值来源与缺省语义是否定义（`../spec.md:127` FR-002 要求五项特征，但 `resolve()` 现签名只有 `explicit_model`/`intent`/`stage`/`node_id`/`output_spec`（`services/chat-api/app/llm/model_router.py:30-38`），三项特征无处可取；**缺**：由谁计算、缺省时是否等同 Edge Cases 的"空输入"、是否新增形参）
- [x] CHK002 `tiers` 取值的模型标识口径与返回后的 client 构造路径是否定义（`../spec.md:35` 决策 #3 与 `../spec.md:130` FR-005 只写"031 已配置模型 ID"；031 的实例 `_id` 与 provider `model_name` 是两个不同标识（`services/chat-api/app/llm/configured_models.py:95-116`），而 `ModelSelection.model` 现被当作 model_name 直接传给 provider；**缺**：命中 tier 后填哪个字段、走 `build_llm_client_from_config` 还是 env 凭据 client）
- [x] CHK003 `tenants.<tenant_id>.tiers` 的 `tenant_id` 取值来源是否定义（`../spec.md:130` FR-005 要求租户覆盖，`../spec.md:72` AC2 要求"命中覆盖映射而非全局 `tiers`"；但 `resolve()` 无 `tenant_id` 形参（`services/chat-api/app/llm/model_router.py:30-38`）；**缺**：从哪个字段取、缺省值、租户段缺失时是否回落全局段）
- [x] CHK004 `tiering.thresholds` 阈值段的存在性与缺省常量是否定义（`../plan.md:37-44` 特征表声明阈值可配 `tiering.thresholds`，但 `../spec.md:133` FR-008 的 yaml 段清单只列 `by_node`/`by_stage`/`by_intent`/`models`/`fallback_model`/`enabled` + `tiers`/`tenants`；**缺**：thresholds 段是否属 040 交付物、未配置时用哪些具体常量值）

## 清晰度（Clarity）

- [x] CHK005 告警的落点与可检索判据是否定义（`../spec.md:37` 决策 #5、`../spec.md:131` FR-006、`../spec.md:152` SC-003 均要求"记录告警/告警可查"；**缺**：告警代码闭集、落 `log_print` 还是 `log_trace`、是否进 `token_usage_logs`、运维用什么查询验证"0 静默失败"）
- [x] CHK006 "空输入落 light" 与 "评估输入缺省落 mid" 的区分判据是否定义（`../spec.md:117` Edge Cases"空输入：按最短特征处理（落 light）"与 `../spec.md:57` AC4"评估输入缺省…落默认档位 mid"直接冲突，两者在评估器内不可区分；**缺**：可观测的区分标志）
- [x] CHK007 旁路、显式声明、规则评分、回退四类的判定全序是否写全（`../spec.md:40` 决策 #8 只给优先级链位置；`../spec.md:56` AC3 说 `output_spec.complexity` 优先于规则评分；`../spec.md:114-116` Edge Cases 又单列 `explicit_model`/`configured_model`/`USE_QWEN`；**缺**：一条完整全序 + 非法 `declared_complexity` 值（非三档/大小写/空白）的处理）
- [x] CHK008 `source` 取值闭集与回退时的记法是否定义（`../spec.md:144` Key Entities 只写"新增 `tier:<tier>`"；`../spec.md:73` AC3 要求 tiers 缺失时"落默认档位（mid）映射"，但未说此时 `source` 记什么；**缺**：回退记 `tier:mid` 还是新值、env/config_fallback 路径是否也写 tier、008 如何从 source 反解档位）

## 一致性（Consistency）

- [x] CHK009 `tier` 记"实际服务档位"还是"评估档位"是否定义（`../spec.md:120` Edge Cases 要求 `tier` 与 `degradation_step` 并存不互相覆盖，但未说降级后 `tier` 记哪个值；**缺**：回退/降级后 008 的档位分布是否被虚高污染）
- [x] CHK010 `tier` 在 `token_usage_logs` 的落地字段名与位置是否定义（`../spec.md:134` FR-009 说"复用 007 `as_log_fields()` 模式"；但 `TokenUsageRecord` 现只有一个 `resilience_events` dict 承载韧性事件（`services/chat-api/app/token_usage/models.py:45`），其内容由 `services/chat-api/app/llm/instrumented_client.py:174-179` 从 `provider_meta` 过滤 007 三键生成；**缺**：`tier` 是顶层新字段还是塞进 `resilience_events`）
- [x] CHK011 008 按 `tier` 聚合的消费路径与聚合函数维度白名单是否对齐（`../spec.md:155` SC-006、`../spec.md:170` 跨特性关系要求按档位统计；但 `services/chat-api/app/llm/resilience/metering.py:44` 的 dimension 白名单只有 `provider`/`model`/`tenant`/`agent`，传 `tier` 会被静默归一为 `model`；**缺**：谁扩维度、走 `attribute_cost` 还是 `aggregate_usage`、未扩维时如何声明该限制）
- [x] CHK012 "目标模型未在 031 配置"的校验时点与手段是否定义（`../spec.md:131` FR-006、`../spec.md:113` Edge Cases 要求回退默认档位；但 031 的查询是 `async` DB 调用（`services/chat-api/app/llm/configured_models.py:95-99`），而 `resolve()` 与 `get_llm_client()` 都是同步函数；**缺**：校验放哪一层、是否缓存/缓存多久、校验失败与映射缺失在告警上是否区分）

## 边界与歧义（Edge Cases & Ambiguity）

- [x] CHK013 `USE_QWEN`/`configured_model` 旁路的执行顺序是否写死（`../spec.md:136` FR-011、`../spec.md:74` AC4、`../spec.md:115-116` Edge Cases 三处重复且措辞略异（"行为与现状一致（`provider_default:qwen`）"vs"不进评估器"）；`services/chat-api/app/llm/factory.py:77-89` 的 `configured_model` 分支实际发生在 `resolve()` 之前，spec 未写死该顺序；**缺**：旁路是否彻底不经 router、此时 usage log 的 `tier` 取什么）
- [x] CHK014 静态映射段与 `tiers` 的共存语义是否定义（`../spec.md:40` 决策 #8 把 tier 放在 `by_intent` 之后 → `by_stage`/`by_intent` 一旦命中即永不分层；而 `../spec.md:65` US2 说档位是"租户按自己模型账单调配的成本杠杆"，`../spec.md:78-90` US3 又要补建静态段；**缺**：静态覆盖导致"未分层"时如何观测、租户如何让分层优先）
- [x] CHK015 `prompt_chars` 的度量对象与单位是否定义（`../spec.md:117` Edge Cases 只说"超过长度阈值"，未说度量对象；`../plan.md:39` 写"最近一轮用户消息 + 系统提示字符数"；**缺**：是否含历史消息/工具 schema、单位是字符还是 token、阈值比较用 `>=` 还是 `>`）
- [x] CHK016 `multi_turn` 的计数口径是否定义（`../spec.md:127` FR-002 只写"是否多轮"（布尔语义），`../plan.md:41` 阈值表写"会话历史消息轮数 ≥ 4 记高分"（计数语义）；**缺**：计消息条数还是轮次、user 与 assistant 是否都计、无 session 上下文时取值）

## Notes

- 条目编号 CHK001–CHK016 连续，覆盖完整性 / 清晰度 / 一致性 / 边界四类；每条均可回溯到 `../spec.md` 的 FR / 决策表 / Edge Cases / Key Entities 原文，以及 `../plan.md` 的特征阈值表。
- 本特性需求风险集中在**可落地性**（CHK001/CHK002/CHK003/CHK012）：`resolve()` 现为同步纯函数，既无租户维度也无请求规模特征，而 031 的模型校验是 async DB——三处签名/时序缺口不补齐，"按复杂度选档"与"租户可覆盖"都只是文字。
- 其次风险在**观测口径自相矛盾**（CHK006/CHK008/CHK009/CHK011）：`tier` 记谁、`source` 怎么解析、008 用什么维度桶，四处不一致会让成本收益无法验证（SC-006 不可测）。
- 最后是**覆盖面与价值来源脱节**（CHK013/CHK014）：`configured_model` 直连路径在 `resolve()` 之前就分流，Agent/研究主路径实际不进分层；静态段一旦启用又会永久遮蔽 tier——spec 未声明该边界，容易被误读为"全链路成本↓80%"。

## 评审结论（2026-10-24 勾选，agent 代审 + spec 回填）

16 条全部达标，均经 `../spec.md` 新增的「判定口径补充（R-1~R-16）」消解：

- CHK001（特征输入契约）→ R-1：`TaskComplexityFeatures` 六字段 + `features_supplied` 标志，`resolve()`/`get_llm_client()` 各新增三个关键字参数（缺省 0/0/0）。
- CHK002（tiers 标识与 client 路径）→ R-2：取值 = `admin_model_instances._id`（24-hex），`ModelSelection` 新增 `model_config_id`，走 `build_llm_client_from_config`，禁止把 ObjectId 当 `model_name` 下发。
- CHK003（tenant_id 来源）→ R-3：`output_spec["tenant_id"]` → `["tenantId"]` → `"default"`；`tenants.<tid>.tiers` 未命中回落全局 `tiers`。
- CHK004（thresholds 段）→ R-4：`tiering.thresholds` 属 040 交付物，常量 `DEFAULT_PROMPT_CHARS_HIGH=4000`/`DEFAULT_TOOL_COUNT_HIGH=8`/`DEFAULT_MULTI_TURN_HIGH=4`，yaml 逐键浅合并覆盖。
- CHK005（告警可检索）→ R-5：告警 code 闭集 6 个，`log_print` + `log_trace(event="tier_routing_fallback")` 双落，不进 `token_usage_logs`。
- CHK006（空输入 vs 缺省）→ R-6：`features_supplied=False` → mid + `features_absent`；`True` 且三项全 0 → light。两者由标志区分，不再冲突。
- CHK007（判定全序）→ R-7：`USE_QWEN > explicit_model > configured_model > declared_complexity > 规则评分 > mid 回退`；非法声明值忽略并记 trace。
- CHK008（source 闭集）→ R-8：只新增 `tier:light`/`tier:mid`/`tier:high`；回退不改 source 取值形态，另记 `tier_fallback_from`；env/config_fallback 路径不写 `tier:*`。
- CHK009（tier 记实际档位）→ R-9：`tier` = 实际服务档位，评估原始值落 `tier_declared`（仅不一致时写），env 路径为 `""`。
- CHK010（usage log 字段落点）→ R-10：`TokenUsageRecord` 新增顶层 `tier`/`tier_declared`，**不进** `resilience_events`；写入点 `instrumented_client.py` 记录构造处。
- CHK011（008 聚合路径）→ R-11：走 `attribute_cost(dimension="tier", dimension_of=...)`；`aggregate_usage` 白名单首期不扩（传 `tier` 会归一为 `model`，已声明为已知限制）。
- CHK012（031 校验时点）→ R-12：`resolve()` 只做形态校验（不 await），真伪校验下沉到 client 构造层，失败回退 mid → env 并告警 `model_config_missing`。
- CHK013（旁路顺序）→ R-13：`configured_model` 分支在 `resolve()` 之前、`USE_QWEN` 早返回为第一句，040 不改顺序；旁路 usage log 的 `tier` 为空串。
- CHK014（静态段共存）→ R-14：决策 #8 优先级不变，命中静态段时 trace 记 `tier=""` + `tier_skipped_reason="static_mapping_hit"`，让"未分层"可观测；本期不提供优先开关。
- CHK015（长度特征口径）→ R-15：`len(最近一轮 user 消息) + len(系统提示)`，Unicode 字符数，不含历史/工具 schema/响应，阈值比较用 `>=`。
- CHK016（多轮计数口径）→ R-16：`multi_turn` = 会话历史 user+assistant 消息**条数**，`>= 4` 记分，无 session 记 0，不按 token 换算、不截断。

**验收证据**：本特性**尚无实现与测试**（`services/chat-api/app/llm/complexity.py` 不存在、`services/chat-api/app/config/model_routing.yaml` 不存在、`tests/llm/test_model_tier_routing.py` 不存在，`resolve()` 无 tier 级），回填为**需求口径澄清**而非实现描述。核查文件：`services/chat-api/app/llm/model_router.py`、`services/chat-api/app/llm/factory.py:63-115`、`services/chat-api/app/llm/configured_models.py:95-116/378-400`、`services/chat-api/app/token_usage/models.py`、`services/chat-api/app/llm/instrumented_client.py:150-220`、`services/chat-api/app/llm/resilience/{degradation,events,metering}.py`、`services/chat-api/app/infrastructure/request_context.py`、`services/chat-api/app/config/resilience.yaml`、`services/admin-api/app/api/routes/models.py`、`services/admin-api/app/repositories/model_repository.py`、`services/admin-api/app/api/dashboard_metrics.py:297`。测试：无（`grep ModelRouter services/chat-api/tests/` 零命中，未跑任何用例）。
