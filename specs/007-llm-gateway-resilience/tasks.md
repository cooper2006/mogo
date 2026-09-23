# Tasks: LLM Gateway Resilience

**Input**: Design documents from `/specs/007-llm-gateway-resilience/`

**Prerequisites**: plan.md (required), spec.md (required)

**Clarify Decisions (governing tasks, 2026-07-08)**:
- 退避用 **tenacity>=8.3.0**（既有依赖，requirements.txt/pyproject 已含；`azure_gpt_image.py` 已用），非手写。
- 默认参数：退避基数 1.5s / 上限 30s / 抖动 ±10% / 可重试 429+5xx+超时 / 不可重试 401+403 / 最大重试 3（可配）。
- 降级链**仅文本模型**（图像走 `azure_gpt_image` 自身重试）。
- failover/降级/重试事件**落 `token_usage_logs` 附加字段**（`failover_from`/`failover_to`/`degradation_step`），不新增独立 collection。
- 计量复用既有 `token_usage` 管线（`InstrumentedLLMClient` + `TokenUsageDispatcher` + `TokenUsageRepository`），不重做。

**Checklist Gate**: `checklists/requirements.md` 未勾选项构成 `/speckit-implement` 拦截门禁；本任务文件仅规划，不修改 checklist 标记。

**Organization**: 任务按用户故事分组，每组可独立实现与测试；`[P]` 标记可并行任务。

---

## Phase 1: Setup (Module Skeleton)

**Goal**: 在 `llm/` 下搭 resilience 子模块骨架，作为 failover/降级/退避/事件的共同载体。

- [x] T001 创建 `services/chat-api/app/llm/resilience/__init__.py`（导出韧性调度入口）
- [x] T002 创建 `resilience/errors.py`：韧性错误分类（可重试：429/5xx/超时；不可重试：401/403；链耗尽错误）
- [x] T003 创建 `resilience/events.py`：failover/降级/重试事件结构（`failover_from`/`failover_to`/`degradation_step`/`reason`），落 `token_usage_logs` 附加字段
- [x] T004 创建韧性调度器 `resilience/failover.py` 占位（主/备供应商调度接口），与既有 `model_router.py` 的"选择语义"对接（保留 intent/stage/node 优先级）

---

## Phase 2: Foundational (Blocking Prerequisites)

**Goal**: 建立被各故事依赖的基础设施（provider 抽象、重试原语）。

- [x] T005 [P] 抽象 provider 调用统一入口：把 `llm/providers/`（azure_openai/azure_responses/azure_gpt_image/default_openai/qwen）封装为可 failover 的"主/备调用单元"（统一超时/错误分类）
- [x] T006 [P] 实现指数退避原语 `resilience/retry.py`：tenacity（基数 1.5s/上限 30s/±10% 抖动/重试 3 次，均可配）+ 可/不可重试判定 + 401/403 立即失败

---

## Phase 3: User Story 1 (P1) — 主→备供应商 failover

**Goal**: 主供应商失败自动切备，事件可观测，单供应商行为不变。
**独立测试**: 主 500/超时→切备成功；主备均失败→聚合错误；单供应商→行为与现状一致。

- [x] T007 实现 `failover.py` 主/备调度：按配置主/备顺序执行，主失败（可重试类）切备（复用 T005 抽象 + T006 退避）
- [x] T008 failover 事件记录：切换事件落 `token_usage_logs`（供应商/耗时/失败原因/最终命中，复用 T003）
- [x] T009 单供应商回归测试：仅配置一个供应商时 failover 为 no-op，行为与现状 0 破坏（Success 基准）
- [x] T010 failover 集成测试：主失败切备成功 + 主备均失败聚合错误两组 Acceptance

---

## Phase 4: User Story 2 (P1) — 降级链 degradation_chain

**Goal**: 主模型失败逐级降档（高性能→中档→轻量），链耗尽明确报错。
**独立测试**: 主档失败→降下一档成功；逐级失败→链耗尽错误；降档事件可追溯。

- [x] T011 [P] 实现 `resilience/degradation.py` 降级链（仅文本模型，参考既有 `llm/structured_fallback.py` 的降级思路）
- [x] T012 降级链事件：降档前/后模型 + 原因落 `token_usage_logs`（复用 T003 `degradation_step`）
- [x] T013 声明式降级链配置（`config.py` 扩展：主/备/降级档由配置驱动，不硬编码，FR-8）
- [x] T014 降级集成测试：逐级降档成功 + 链耗尽返回明确错误（不静默）两组 Acceptance

---

## Phase 5: User Story 3 (P1) — 指数退避重试

**Goal**: 可重试错误按退避+抖动重试，不可重试立即失败。
**独立测试**: 429→退避重试至成功/上限；401→不重试立即返回；次数/间隔可观测。

- [x] T015 将 T006 退避原语接入 failover/降级调度（429/5xx/超时重试，401/403 直接失败）
- [x] T016 重试次数/间隔日志可观测（Success 基准），默认 3 次可配
- [x] T017 退避单测：429 重试成功 + 401 零重试 + 达上限后失败三组 Acceptance

---

## Phase 6: User Story 4 (P2) — 用量/成本计量上报

**Goal**: 每次调用记录 token 用量 + 估算成本，按维度聚合供 008 驾驶舱消费。
**独立测试**: 调用后记录 TokenUsageRecord；按供应商/模型/租户/智能体聚合；计量落库可查。

- [x] T018 [P] 复用 `token_usage` 管线（`InstrumentedLLMClient` + `TokenUsageDispatcher` + `TokenUsageRepository`）记录每次 LLM 调用的 input/output token + 成本
- [x] T019 成本估算（按 token 单价 × 用量，单价口径与 008 MODEL_PRICES 对齐，FR-5）
- [x] T020 维度聚合（供应商/模型/租户/智能体）查询端点（FR-6），供 008 消费
- [x] T021 计量集成测试：调用记录 + 按维度聚合可查两组 Acceptance

---

## Phase 7: Polish & Cross-Cutting Concerns

- [x] T022 [P] 韧性事件可观测总验证：failover/降级/重试/计量事件 100% 可查（FR-7）
- [x] T023 [P] 配置声明式收尾：供应商/降级链/退避参数全配置驱动（FR-8，含 `resilience/config.py`）
- [x] T024 计量覆盖率自检：LLM 调用计量记录覆盖率 100%（token + 成本，Success 基准）
- [x] T025 写 `quickstart.md`（韧性启用 + 故障注入验证步骤）+ `contracts/resilience.md`（failover/降级/退避/计量 IO 契约）

---

## Dependencies

```text
Phase 1 (骨架/错误分类/事件) → Phase 2 (provider 抽象 + 退避原语)
Phase 2 → US1(T007-010) → US2(T011-014) → US3(T015-017) → US4(T018-021)
US1-4 → Phase 7 (Polish)
关键依赖: T005/T006 被 US1/US2/US3 复用；T003 事件结构被 US1/US2/US3/US4 共用；T018 复用既有 token_usage
```

## Parallel Opportunities
- T005/T006（Phase 2）互不依赖，可并行
- 各 US 内 [P] 任务（T011、T018）可并行
- US1（failover）完成后可并行推进 US2（降级）/US3（退避），二者共用 T006 退避原语

## MVP Scope
- **最小可交付 = Phase 1 + Phase 2 + US1**（T001–T010）：主/备 failover 跑通 + 事件可观测 + 单供应商回归 0 破坏。
- 增量交付：US2（降级链）→ US3（退避）→ US4（计量）。

## Implementation Strategy
- 先 MVP（US1 failover 跑通），再 US2 降级、US3 退避，最后 US4 计量
- 每故事完成即独立可测（Acceptance Scenarios 即测试基准）
- 退避/事件参数严格沿用既有 `azure_gpt_image` 值（1.5s/30s/±10%/3 次），避免行为漂移
- 计量不重做，复用既有 `token_usage` 管线

## Notes
- 本 tasks.md 为 `/speckit-tasks` 产出，含 007 的 clarify 决策（tenacity 复用、默认参数、仅文本模型、事件落 token_usage_logs）。
- 实现需先通过 `checklists/requirements.md` 门禁；CHK009（failover 字段口径）需与 008 spec 双向对齐。
- 未改 services 源码；本文件仅在 `specs/007-llm-gateway-resilience/` 下。
