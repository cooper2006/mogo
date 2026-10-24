# Tasks: 资产发布管控增强（比例灰度 + 影子发布）（033-canary-rollout）

**Input**: Design documents from `/specs/033-canary-rollout/`

**Prerequisites**: plan.md (required), spec.md (required)

**性质**: **全新特性**。实现与验收于 2026-10-23 完成（由并行会话落地实现，本会话按 SDD 门禁流程复核：`checklists/requirements.md` 15/15 达标 + spec 回填 R-1~R-14 + 测试验收通过后统一勾选）。

**验收证据**: `services/admin-api/tests/test_canary_ratio.py` 19 passed；`services/chat-api/tests/dsh_runtime/test_canary_shadow.py` 9 passed；`SkillCanaryConfigPage.vue` 经 `@vue/compiler-sfc` 编译通过。

**Tests**: admin-api pytest（`tests/test_canary_ratio.py` 新增契约测试 + 016 既有 canary 用例回归）；chat-api 影子分流契约测试；前端 `@vue/compiler-sfc` 单文件编译校验。

**Organization**: Phase 0 研究与澄清 → Phase 1 设计 → Phase 2 实现 → Phase 3 验证与接线；T001 起连续编号，`[P]` 标记可并行任务，`[USx]` 标记所属用户故事。

---

## Phase 0: 研究与澄清

- [x] T001 [US1] 澄清 tenants 与 ratio 叠加语义与分流粘滞口径：确定哈希维度（`tenant_id` + `user_id`）、取模基数与比例近似容差，回写 spec 已定决策表第 2/3 条
- [x] T002 [US2] 核实 chat-api Skill 调用入口的身份上下文与分流挂点：确认 `services/chat-api/app/dsh_runtime/profile/skills/resolver.py` 与 `services/chat-api/app/dsh_runtime/turn_runner.py` 中 `tenant_id`/`user_id` 可得性，选定影子双跑的唯一挂载文件（避免多入口重复实现）
- [x] T003 [US1] 确认 016 `Rollout` 持久化扩展的兼容性：`skill_rollouts` 旧行（无 `traffic_ratio`/`ladder`/`shadow_enabled` 字段）经 `_row_to_rollout` 读取时的默认值（ratio=1.0、shadow=false），保证既有按租户灰度不回退
- [x] T004 [US2] 确认影子执行隔离边界：影子调用发起层、异常/超时吞并点、`skill_shadow_runs` 写入路径（只写 + 基础聚合），以及"影子结果绝不进入用户响应"的代码层保证点

---

## Phase 1: 设计

- [x] T005 [US1] 设计 `Rollout` 数据模型扩展：`traffic_ratio`/`ladder`/`current_step`/`ladder_history`/`shadow_enabled` 字段定义、默认值、`_row_to_rollout`/`_rollout_to_row` 兼容改造点；确认 `stable_version` 提供方（创建方传入或从 `organization_skill_releases` 推导）
- [x] T006 [US1] 设计阶梯推进器：推进条件（当前档样本 ≥ `min_samples` 且异常率 ≤ `threshold`）、推进动作（更新 `current_step`/`traffic_ratio`、写 `ladder_history`）、到 100% 置 `PROMOTED`、手动推进入口；与既有 `CanaryRollbackScanner` 循环的并入方式（同一循环评估 vs 独立扫描器，以简为准）
- [x] T007 [US1] 设计确定性分流纯函数：`(tenant_id, user_id)` 哈希取模 + `target_tenants` 叠加判定；输入输出契约与可单测性（无 IO、无状态）
- [x] T008 [US2] 设计影子分流点：命中判定（未命中 ratio → 双跑）→ 双跑执行 → `skill_shadow_runs` 落库 → 异常吞并隔离；与用户响应路径的解耦保证（影子分支任何失败不影响主分支返回）
- [x] T009 [US4] 设计路由与前端契约：`skill_canary.py` 创建/查询扩展参数（`traffic_ratio`/`ladder`/`shadow`）与查询返回（当前档位/推进历史/影子统计）；admin-web 灰度配置页信息架构（配置表单 + 进度 + 统计 + 回滚）

---

## Phase 2: 实现

- [x] T010 [US1] `services/admin-api/app/services/skill_market/canary.py`：`Rollout` 增加 `traffic_ratio`/`ladder`/`current_step`/`ladder_history`/`shadow_enabled` 字段与旧行兼容默认值（FR-001）
- [x] T011 [P] [US1] 阶梯推进器：`advance_ladder` + 推进条件评估（样本 ≥ `min_samples` 且异常率 ≤ `threshold`；样本不足停档；到 100% 置 `PROMOTED`；档位与历史落库）（FR-004/FR-005/FR-011）
- [x] T012 [P] [US1] 分流纯函数：`resolve_assignment`（`(tenant_id, user_id)` 哈希粘滞 + tenants 叠加判定；ratio 非法值拒绝）（FR-002/FR-003）
- [x] T013 [P] [US2] chat-api 影子分流点：命中判定 → 双跑执行 → `skill_shadow_runs` 落库 → 异常/超时吞并隔离；影子结果不返回、不计入 `call_count`/`error_count`（FR-006/FR-007/FR-008）
- [x] T014 [US3] `services/admin-api/app/api/routes/skill_canary.py` 路由扩展：创建带 `traffic_ratio`/`ladder`/`shadow` 参数；查询返回当前档位/推进历史/影子统计；手动回滚路由与语义原样保留（FR-009/FR-010/FR-012）
- [x] T015 [US1] 扫描器接线：阶梯推进评估并入 `CanaryRollbackScanner` 5 分钟循环（或按 T006 结论独立扫描器），lifespan 启动方式对齐既有模式
- [x] T016 [US4] admin-web 灰度配置页：`src/api/skillCanary.ts` API 客户端 + `src/views/skills/SkillCanaryConfigPage.vue`（阶梯/影子配置表单、进度与影子统计展示、一键回滚按钮；文案走 `t()` 中文 key 回退）（FR-013）

---

## Phase 3: 验证与接线

- [x] T017 [US1] 契约测试：阶梯推进——样本不足停在当前档；达标推进 1%→10%→50%→100%；到 100% 稳定置 `PROMOTED`；推进历史可查；手动推进可用
- [x] T018 [US2] 契约测试：影子双跑——用户结果 100% 来自稳定版；`skill_shadow_runs` 有记录；影子执行失败不触发回滚且不影响用户请求
- [x] T019 [US1] 契约测试：分流确定性（同一用户多次分配一致）与大样本比例近似；`target_tenants` 与 `traffic_ratio` 叠加语义
- [x] T020 [US3] 回归契约测试：016 既有按租户灰度 + 自动回滚（20%/20）+ 手动一键回滚用例零回归；比例维度下回滚后 ratio 归零、状态 `rolled_back`、`stable_version` 指向上一次已发布稳定版本
- [x] T021 [US1] 兼容测试：无 `traffic_ratio` 的存量 `skill_rollouts` 行读取默认 100%，既有按租户灰度行为不回退
- [x] T022 验收：按 SC-001~SC-006 逐条执行（含 1%→100% 全链路推进 + 异常注入自动回滚 + 影子双跑不污染）；`@vue/compiler-sfc` 校验 `SkillCanaryConfigPage.vue` 编译通过

---

## Dependencies & Execution Order

- Phase 0（T001-T004）是前提：T002 的挂点未定不前置于 Phase 1 的影子设计（T008）；T003 的兼容口径是 T005/T010 的输入。
- Phase 1 内部：T005/T007 可并行；T006 依赖 T005 模型；T008 依赖 T002/T004 结论；T009 依赖 T005-T008 的契约。
- Phase 2 内部：T010 是 T011/T012/T014 的字段基础（先行）；T011/T012/T013 互相独立可并行（`[P]`）；T014 依赖 T010/T011/T013；T015 依赖 T011；T016 依赖 T009/T014 路由契约。
- Phase 3（T017-T022）依赖 Phase 2 完成；T020（016 回归）与 T021（存量兼容）是"不改 016 语义"决策的证伪关卡；T022 收尾验收。
- 用户故事可独立验证顺序：US1（阶梯灰度，MVP）→ US2（影子）→ US3（回滚保留，实为回归主线）→ US4（配置页）。

## Notes

- 016 既有函数（`evaluate_canary` / `apply_rollback` / `CanaryRollbackScanner` / `POST /{skill_id}/rollback`）**原样复用不改**——本特性的全部增量是 `Rollout` 维度扩展、推进器、分流函数、影子分流点、路由参数与配置页。
- 影子双跑成本（双倍 LLM 调用）由租户显式开启影子时承担，默认关闭；影子统计只回答"候选版在真实流量下表现如何"，不做深度比对。
- `skill_shadow_runs` 只写 + 基础聚合查询（调用数/成功率/耗时），不建二级索引以外的复杂查询路径（YAGNI）。
- 与 024 的边界在实现中自然成立：024 改 nginx/compose 层，本特性只改 admin-api/chat-api 应用层，无共同文件。
- 与 032 的边界：032 改 `skill_lifecycle.publish()`（发布前），本特性改灰度分流（发布后），两特性的改动文件无交集，可并行落地。
