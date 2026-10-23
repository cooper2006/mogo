# Tasks: 模型分层路由（040-model-tier-routing）

**Input**: Design documents from `/specs/040-model-tier-routing/`

**Prerequisites**: plan.md (required), spec.md (required)

**性质**: **全新特性，代码尚未开工**——本清单为 spec → plan → tasks 先行流程的产物，所有任务均未开始（`- [ ]`）。

**Tests**: chat-api `tests/llm/test_model_tier_routing.py`（新增）；007 既有 `test_resilience.py` / `test_resilience_metering.py` / `test_resilience_wiring.py` 回归。

**Organization**: 任务按 Phase 组织（Phase 0 研究与澄清 → Phase 1 设计 → Phase 2 实现 → Phase 3 验证与接线），T001 起连续编号，全部未勾选。`[P]` 标记可并行任务，`[USn]` 标记所属 User Story。

---

## Phase 0: 研究与澄清

- [ ] T001 建立 spec/plan/tasks 三件套（`specs/040-model-tier-routing/`，本文件）
- [ ] T002 [P] 代码级核实现状并记录证据：`services/chat-api/app/llm/model_router.py:20-115` 优先级链与 `_load_config` 热加载机制；`services/chat-api/app/config/` 仅 `resilience.yaml`；`services/chat-api/app/llm/factory.py` 中 `resolve()` 唯一调用点与 `model_routed` 埋点
- [ ] T003 [P] 澄清并固化复杂度评估特征清单与初始阈值（长度/工具数/多轮/阶段意图/显式声明五项；历史档位表现确认二期不接），与整合方案 §2.4 成本口径对齐（简单任务走轻量）
- [ ] T004 [P] 确认档位命名与 007 降级链档位词对齐（`high`/`mid`/`light`，`services/chat-api/app/llm/resilience/degradation.py:21`）及"路由失败≠降级触发条件"的串行边界写法
- [ ] T005 [P] 确认 031 已配置模型中可作 `tiers` 映射目标的模型标识口径（`tiers` 段取值 = 031 模型配置 ID，引用不复制）

**Checkpoint**: 现状证据、特征清单、档位词、串行边界、映射取值来源五件事全部有书面结论

---

## Phase 1: 设计

- [ ] T006 设计 `app/config/model_routing.yaml` 结构：静态映射段（`by_node`/`by_stage`/`by_intent`/`models`/`fallback_model`/`enabled`）+ 档位映射段（`tiers` + `tenants.<tenant_id>.tiers` 覆盖）+ `tiering.thresholds` 阈值段，全部以注释默认值给出
- [ ] T007 设计复杂度评估纯函数签名与特征输入契约（`TaskComplexityFeatures`：`prompt_chars`/`tool_count`/`multi_turn`/`stage`/`intent`/`declared_complexity` → `ModelTier`），明确异常路径返回默认档位 `mid`
- [ ] T008 设计可观测字段：`log_trace` `model_routed` 事件增 `tier` 与特征摘要；`token_usage_logs` 附加字段 `tier`（复用 `services/chat-api/app/llm/resilience/events.py` 的 `as_log_fields()` 模式，不新增 collection）
- [ ] T009 设计安全回退与告警路径：默认档位 mid → `tiers` 缺失/单档缺失回退 → `env:*` / `config_fallback`；告警落点（`log_print` + trace），确认 `USE_QWEN` 与 `configured_model` 旁路不进评估器

**Checkpoint**: yaml 结构、评估函数契约、可观测字段、回退链四份设计有书面结论，可进入实现

---

## Phase 2: 实现

- [ ] T010 [P] 新建 `services/chat-api/app/config/model_routing.yaml`：静态映射段 + `tiers`/`tenants` 档位映射段 + `tiering.thresholds` 段，注释默认值（含档位产品名"轻量/主力/旗舰"中英对照）
- [ ] T011 [P] [US1] 新建 `services/chat-api/app/llm/complexity.py`：特征提取 + 规则评分纯函数（无 IO、无 LLM 调用），异常路径落默认档位 `mid` 并告警
- [ ] T012 [US1][US2] 修改 `services/chat-api/app/llm/model_router.py`：`resolve()` 在 `by_intent` 之后、`env` 之前插入 tier 一级——特征提取 → 规则评分 → `tiers`（含 `tenants` 覆盖）解析 → `source=tier:<tier>`；保持 `explicit`/`task_override`/`by_node`/`by_stage`/`by_intent`/`env`/`fallback` 链与 `USE_QWEN` 早返回语义不变
- [ ] T013 [P] [US4] 修改 `services/chat-api/app/llm/factory.py`：`model_routed` `log_trace` 事件增补 `tier` 与特征摘要字段
- [ ] T014 [P] [US4] 计量接线：usage log 附加字段落 `tier`（复用 `events.py` 附加字段模式；与 `degradation_step` 并存不互相覆盖）
- [ ] T015 [P] [US1][US2] 新建 `services/chat-api/tests/llm/test_model_tier_routing.py`：评估函数边界（空/短/长/多工具/多轮/显式声明/异常→mid+告警）+ 档位映射命中与租户覆盖 + 回退链（tiers 缺失→mid→env→config_fallback）
- [ ] T016 [P] 回归：`tests/llm/test_resilience.py` / `test_resilience_metering.py` / `test_resilience_wiring.py` 全绿（007 降级链行为 0 回退）；ModelRouter 既有优先级链（`explicit`/`by_stage`/`by_intent`/`env:*`/`config_fallback`/`disabled_fallback`）回归 0 破坏

**Checkpoint**: US1/US2/US4 代码就绪，评估、映射、可观测、回归四类测试可跑

---

## Phase 3: 验证与接线

- [ ] T017 [US1][US2] E2E 验证：同一请求改换复杂度特征落入不同档位（单测覆盖 + 本地手工验证短问答→light、编码多轮→high），断言档位分布符合规则文档
- [ ] T018 [US2] 安全回退验证：删 `tiers` 段/评估器注入异常，断言 100% 落默认档位或既有兜底且告警可查，0 静默失败
- [ ] T019 [US4] 可观测接线验证：`log_trace` 事件与 `token_usage_logs` 附加字段均含 `tier`；与 008 侧确认"按档位统计调用量与成本"的聚合口径（数据来源就绪，008 维度扩展归 008）
- [ ] T020 [P] 文档与配置收尾：yaml 注释与 spec 决策表口径一致（档位词、阈值、回退链）；确认未新增任何依赖、未改动 007 文件、未创建 checklists/ 与 quickstart.md、未更新 `specs/INDEX.md`

**Checkpoint**: 四个 User Story 全部独立可证伪；FR-001–FR-012 逐条有着落

---

## Dependencies & Execution Order

- Phase 0 五条澄清（T002–T005）是 Phase 1 设计的前置；T001 可先行。
- Phase 1 内部：T006（yaml 结构）依赖 T003/T004 结论；T007/T008/T009 可并行设计。
- Phase 2 内部：T011（评估函数）是 T012（router 接线）的前置；T010/T013/T014/T015 可并行；T016 回归依赖 T012/T014 完成。
- Phase 3 依赖 Phase 2 全部完成；T017–T019 按序验证，T020 收尾。

## Notes

- 评估器 MUST 为纯函数：不读配置、不发请求——配置（阈值）由调用方（`model_router`）传入，保证可单测、无隐藏依赖。
- tier 一级插入位置（`by_intent` 之后、`env` 之前）是兼容性关键：显式 override 与节点/阶段/意图映射优先于智能选档，租户既有静态配置行为不变。
- `USE_QWEN` 与 `configured_model` 两条旁路路径 MUST 保持现状——单模型部署与已显式配置模型的场景不分层（FR-011）。
- 告警文案用中文 key 口径，与 `log_print` 既有格式一致；不落 prompt 内容与凭证（Constitution III）。
- 本特性不创建 `checklists/`、不创建 `quickstart.md`、不更新 `specs/INDEX.md`（由规约撰写范围约束）。
