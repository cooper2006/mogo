# Tasks: 评测门禁（032-eval-gate）

**Input**: Design documents from `/specs/032-eval-gate/`

**Prerequisites**: plan.md (required), spec.md (required)

**性质**: **全新特性，代码尚未开工**——本清单全部任务未勾选（`- [ ]`），按 Phase 顺序正向推进。

**Tests**: admin-api pytest（`tests/test_eval_gate.py`）；前端 `@vue/compiler-sfc` 单文件编译校验（替代全量 vue-tsc/vite build）。

**Organization**: Phase 0 研究与澄清 → Phase 1 设计 → Phase 2 实现 → Phase 3 验证与接线；T001 起连续编号，`[P]` 标记可并行任务，`[USx]` 标记所属用户故事。

---

## Phase 0: 研究与澄清

- [x] T001 [US1] 澄清「幻觉率」代理指标口径：确认引用支撑率的引用信号来源（`services/chat-api/app/knowledge/citations/citation_resolver.py` 的引用解析机制）与拒答正确率的拒答信号来源（`services/chat-api/app/knowledge/agents/knowledge_qa_agent.py` 的拒答机制），形成决策记录回写 spec 已定决策表第 1 条
- [x] T002 [US2] 确认 admin-api → chat-api 评测调用契约：核实 `services/admin-api/app/core/config.py` 的 `backend_base_url` / `backend_service_token` 与 chat-api 模型网关端点（`services/chat-api/app/api/endpoints/dsh_model_gateway.py`）的请求/响应结构、鉴权方式与服务 token 传递头
- [x] T003 [US2] 确认审计落点：核实 `services/admin-api/app/governance/layers/audit.py` 的 `gate_events` 写入方式（直接 insert 复用集合、不走六层链），确认 `event_type` 扩展字段与既有文档结构的兼容性
- [x] T004 [US2] 确认 007 韧性复用面：核实 `services/chat-api/app/llm/resilience/retry.py` 的重试/退避/超时分类在评测调用路径上的生效方式（chat-api 侧网关负责重试，admin-api 侧只设调用超时），明确两侧职责边界

---

## Phase 1: 设计

- [x] T005 [US1] 设计测试集数据模型与 API 契约：`skill_eval_cases` 集合字段（`tenant_id`/`skill_id`/`agent_tag`/`input`/`expectations`/`expected_refs`/`expect_refusal`/`created_at`）、`(tenant_id, skill_id)` 隔离索引、CRUD 路由请求/响应结构
- [x] T006 [US2] 设计评测执行器：逐用例经 chat-api 网关调用、007 韧性隔离（admin-api 侧不自行重试）、整体超时默认 300s、单次用例上限默认 50、超时/失败分类与取消语义
- [x] T007 [US3] 设计阈值策略模型：`skill_eval_policies` 集合字段、默认值（`min_cases=5` 对齐 011 `DEFAULT_MIN_SAMPLES`、三项指标默认阈值、`max_cases=50`、`timeout_seconds=300`）、fail-closed 默认与"门禁不可关闭"的约束表达
- [x] T008 [US2] 设计 `publish()` 挂卡点：`services/admin-api/app/services/skill_lifecycle.py` 的 `publish()` 内**版本唯一性检查之后、insert release 之前**调用门禁；定义 `EvalGateBlocked` 异常类型（携带指标明细）与路由层 4xx 映射（`app/api/routes/skill_lifecycle.py` except 分支扩展）

---

## Phase 2: 实现

- [x] T009 [US2] 新建 `services/admin-api/app/services/eval_gate/` 模块骨架：`__init__.py`（导出 + `ensure_indexes`）+ `models.py`（三集合常量与字段契约）
- [x] T010 [P] [US1] 测试集 CRUD：`test_sets.py` 服务 + `skill_eval.py` 路由（创建/查询/更新/删除，`(tenant_id, skill_id)` 隔离，用例上限校验 FR-002）
- [x] T011 [P] [US2] 三指标规则判定器 `judges.py`：引用支撑率（`expected_refs` 非空用例中输出含引用来源的比例）、拒答正确率（`expect_refusal` 用例中正确拒答的比例）、任务成功率（非拒答用例通过期望要点匹配的比例）；等于阈值通过（FR-005）
- [x] T012 [P] [US2] 评测执行器 `executor.py`：经 `backend_base_url` + `backend_service_token` 调 chat-api 网关（urllib + `asyncio.to_thread`），调用超时与失败分类，`dry_run` 标记；评测记录只存判定摘要不存完整输出（FR-009/FR-011）
- [x] T013 [P] [US3] 阈值策略 `policies.py`：租户覆盖 + 默认 fail-closed 值；查询/更新 API；门禁恒启用的约束（FR-006）
- [x] T014 [US2] 门禁编排 `gate.py` + `skill_lifecycle.publish()` 挂卡：样本不足/无测试集/指标不达标/执行失败均抛 `EvalGateBlocked`（含指标明细）；阻断与放行落 `gate_events`（`event_type=eval_gate.blocked|passed`，含 skill_id/版本/三指标/阈值）（FR-003/FR-007/FR-008）
- [x] T015 [P] [US3] 前端 `apps/admin-web/src/api/skillEval.ts`：试运行评测触发 + 最近评测报告查询 + 测试集 CRUD 客户端（首期测试集管理 UI 不做，API 先行）
- [x] T016 [US3] `apps/admin-web/src/views/skills/SkillPublishDialog.vue` 增加评测报告展示：阻断时高亮未达标指标与阈值对照；提供「试运行评测」入口；文案走 `t()` 中文 key 回退（FR-012）

---

## Phase 3: 验证与接线

- [x] T017 [US2] 单测：判定器三指标与边界（等于阈值通过、拒答类不计入任务成功率分母、空期望引用不参与支撑率分母）
- [x] T018 [US2] 单测：门禁阻断端到端（低于阈值 → `publish()` 返回 4xx → `organization_skill_releases` 无新记录 → `gate_events` 有 `eval_gate.blocked` 事件及指标明细）
- [x] T019 [US2] 单测：fail-closed 三路径（无测试集 / 样本不足 <5 / LLM 超时不可用）全部阻断，无静默放行
- [x] T020 [US2] 单测：全达标 → `publish()` 成功生成 release + `eval_gate.passed` 审计；dry-run 不产生发布、不落阻断审计
- [x] T021 [US2] 接线：admin-api `main.py` 挂载 `skill_eval` 路由 + `eval_gate.ensure_indexes`（对齐既有 `ensure_indexes`  lifespan 模式）
- [x] T022 验收：按 SC-001~SC-006 逐条执行（核心：构造低于阈值 Skill 发布被阻断且审计可查）；`@vue/compiler-sfc` 校验 `SkillPublishDialog.vue` 编译通过

---

## Dependencies & Execution Order

- Phase 0（T001-T004）是前提：T001 的指标口径与 T002 的调用契约未定，不前置于 Phase 1 设计。
- Phase 1 内部：T005/T007 可并行；T006 依赖 T002 契约结论；T008 依赖 T005/T007 的数据模型。
- Phase 2 内部：T010/T011/T012/T013 互相独立可并行（`[P]`）；T014 依赖 T010-T013 全部就绪；T015/T016 依赖 T010/T012 定稿的 API 契约。
- Phase 3（T017-T022）依赖 Phase 2 完成；T021/T022 为收尾接线与验收。
- 用户故事可独立验证顺序：US1（测试集）→ US2（门禁）→ US3（策略与报告）；US2 是 MVP 核心，但其验收依赖 US1 的测试集能力先就绪。

## Notes

- 评测记录（`skill_eval_runs.case_results`）只存判定摘要与理由，不存完整 LLM 输出——避免评测库成为业务数据副本（Constitution III）。
- admin-api 出站 HTTP 沿用 `urllib.request` + `asyncio.to_thread` 既有范式（参照 `services/admin-api/app/services/skill_package_proxy.py`），不引入 httpx 客户端。
- 前端测试集管理 UI 首期不做（Non-Goal）：仅 API + 发布对话框报告展示；测试集维护走 API，UI 留给后续特性。
- 门禁不可整体关闭（FR-006）：避免"临时关关"演变为长期失效；租户只能调阈值松紧。
- 与 016 的数据边界：本特性不写 `skill_quality_metrics` 日桶（那是运行时滚动聚合），只新增 `skill_eval_runs`；036 可信评级立项时以 `skill_eval_runs` 为数据源。
