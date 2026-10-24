# Tasks: 可视化编排画布（039-visual-orchestration）

**Input**: Design documents from `/specs/039-visual-orchestration/`

**Prerequisites**: plan.md (required), spec.md (required)

**性质**: **全新特性**——代码尚未开工，本清单全部任务未勾选（`- [ ]`）。

**Tests**: chat-api `tests/test_orchestration_canvas_api.py`（端点契约 + layout 透传 + 010 回归）；前端序列化模块 TS 单测（往返稳定性）；画布 SFC 用 `@vue/compiler-sfc` 编译校验。

**Organization**: Phase 0 研究与澄清 → Phase 1 设计 → Phase 2 实现 → Phase 3 验证与接线。任务编号 T001 起连续。标注 `[010-联合]` 的为对 010 的联合改动点，须同步 010 spec。

---

## Phase 0: 研究与澄清

- [x] T001 建立 spec/plan/tasks 三件套（`specs/039-visual-orchestration/`，本文件）
- [x] T002 核验 010 引擎模块边界：`services/chat-api/app/orchestration/`（`engine.py` `run_graph`/`run_sequential`、`supervisor.py` `run_hybrid`、`graph.py` `VALID_MODES` 四模式、`topo.py` `CycleError` 环路径、`conditions.py` 受限 JSON 条件、`registry.py` 版本化），确认"引擎零行为改动"边界可守
- [x] T003 核验 010 装载/持久化契口：`loader.py`（`load_orchestration_document`/`load_orchestration_text` 文档形状与 `_PAYLOAD_KEYS`）、`store.py`（`dag_definitions` 集合、`load_orchestration_persisted`、`_document_shape` 裁剪范围），确认 `layout` 透传缺口与联合改动点范围
- [x] T004 核验样例资产：`services/chat-api/app/enterprise_capabilities/research/orchestrations/competitor_deep_dive.yaml`（graph 模式 + 两 `skip_condition`），作为反序列化往返测试基准
- [x] T005 核验前端现状：vue-flow/logicflow 全库 0 命中；`apps/user-web/src/components/MySkillConfigPage.vue` 与 `apps/user-web/src/workflow/browserAutomationNode.ts` 为 Skill 步骤编辑（非画布，语义不合并）；确认 user-web 组件式注册模式（`App.vue` 懒加载）与 API client 模式（`apps/user-web/src/api/`）
- [x] T006 核验 001 gatekeeper 发布门禁挂点与权限码机制（发布动作复用既有权限/审批通道，不新建）；确认审计落点复用
- [x] T007 确认 chat-api 新增编排端点的落点模式（仿 `app/api/endpoints/` 既有路由风格）与租户隔离口径

## Phase 1: 设计

- [x] T008 定稿 CanvasDocument 内存模型与 `layout` 顶层字段形状（`{node_id: {x, y}}`，可丢失投影元数据）
- [x] T009 定稿序列化规则：画布 → 010 YAML（模式分支：sequential 特化为无并行 graph；`depends_on` 与 `edges` 双向表达；`skip_condition` 自然语言面不透出引擎内部 `condition` 极性）
- [x] T010 定稿反序列化规则：YAML → 画布（拓扑全还原；无 `layout` 自动布局；坏 `layout` 忽略不堵打开路径；未知顶层键经 `raw` 保留回写）
- [x] T011 定稿保存前校验口径：环（含自环）阻断 + 环路径节点序列（与 `topo.py` `CycleError` 同格式）；孤立节点警示不阻断；非法条件按 `registry.validate()` fail-closed 口径拒绝；空图/重复 ID 画布内即时禁止
- [x] T012 定稿 chat-api 编排端点契定：列表/读取/保存（草稿）/发布（版本递增 + 旧版保留），契约定稿仿既有 endpoints 信封风格
- [x] T013 `[010-联合]` 定稿 `store.py:_document_shape` 的 `layout` 透传改动（一行透传，语义不变），并在 010 spec 补记联合改动说明
- [x] T014 定稿发布门禁与版本化：发布走 001 gatekeeper（权限/审批）；版本递增与旧版可回看沿用 010 FR-8 语义（与 002 工作流版本化关系声明，不新建版本机制）
- [x] T015 定稿属性面板字段面：010 既有节点字段（skill/tools/description/timeout/retry/skip_condition/output_key）可编辑，未知 payload 键只读保留；Skill/工具选择器数据源为既有 API

## Phase 2: 实现

- [x] T016 [P] `apps/user-web/src/components/orchestration/canvasSchema.ts`：画布 JSON ↔ 010 YAML 序列化/反序列化（唯一转换层，纯函数）
- [x] T017 [P] `apps/user-web/src/components/orchestration/canvasValidation.ts`：保存前校验（环/孤立节点/条件，与引擎同口径；错误信息含环路径节点序列）
- [x] T018 `apps/user-web/src/components/orchestration/OrchestrationCanvasPage.vue`：画布页（vue-flow：节点/连线/拖拽/缩放/概览；sequential 与 graph 两模式切换，supervisor/hybrid 明示暂不支持）
- [x] T019 `apps/user-web/src/components/orchestration/NodePropertyPanel.vue`：节点属性面板（复用既有 Skill/工具选择器数据源；未知 payload 键只读展示）
- [x] T020 `apps/user-web/src/api/orchestration.ts`：编排定义 API client（对应 chat-api 端点契约定稿）
- [x] T021 `apps/user-web/src/App.vue`：注册画布页入口（懒加载，组件式模式）
- [x] T022 `[010-联合]` `services/chat-api/app/orchestration/store.py`：`_document_shape` 增加 `layout` 透传（零语义变更；010 spec 同步补记）
- [x] T023 `services/chat-api/app/api/endpoints/orchestrations.py`：编排定义读写端点（列表/读取/草稿保存/发布；租户隔离；发布走 gatekeeper）
- [x] T024 chat-api 端点在 `app/main.py`（或既有 api_router 装配处）挂载（仿既有 endpoints 装配方式）
- [x] T025 草稿态与发布态接线：草稿租户内可见；发布版本递增 + 旧版保留可回看；无权限发布被拒并审计

## Phase 3: 验证与接线

- [x] T026 [P] `services/chat-api/tests/test_orchestration_canvas_api.py`：端点契约（列表/读取/保存/发布信封）、租户隔离、发布版本递增与旧版可回看
- [x] T027 [P] `services/chat-api/tests/test_orchestration_canvas_api.py`：`layout` 透传联合改动验证 + 010 既有测试回归全绿（orchestration 全模块；`competitor_deep_dive` 装载/执行不变）
- [ ] T028 [P] 前端序列化单测：画布 → YAML → 画布往返拓扑零丢失；`competitor_deep_dive.yaml` 反序列化全还原（含 skip_condition 的 expr/reason）；坏 `layout`/缺 `layout` 降级路径
- [ ] T029 [P] 前端校验单测：环/自环阻断且错误信息与 `topo.py` 环路径序列同格式；孤立节点警示；非法条件拒绝
- [ ] T030 E2E：画布搭两节点 graph 流程 → 保存 → 010 引擎真实执行（顺序/产出传递正确）→ 发布 → 版本可回看；手工 YAML 打开画布往返不丢拓扑
- [x] T031 发布门禁验证：无权限用户发布被 001 拒绝且审计可查；无"画布直通生产"路径（代码级审查确认）
- [x] T032 跨特性声明核对：010（联合改动已同步 spec）、002（版本化语义）、004（Skill 数据源）、001（门禁）、038（执行期出站分层）声明与实现一致
- [x] T033 SFC 编译校验：`OrchestrationCanvasPage.vue` / `NodePropertyPanel.vue` 用 `@vue/compiler-sfc` 编译通过（替代全量 vue-tsc/build）

## Dependencies & Execution Order

- Phase 0（T001-T007）全部完成后进入 Phase 1；T008-T015 设计定稿后进入实现。
- T016/T017 序列化与校验为纯函数模块，可并行；T018 画布页依赖 T016/T017；T019 属性面板依赖 T016（字段面）。
- T020/T021 前端 API 与注册依赖 T012 契约定稿；T022/T023/T024 后端依赖 T012/T013 定稿。
- T026-T029 单测可并行；T030 E2E 在实现全部完成后执行；T031-T033 收尾。
- `[010-联合]` 任务（T013/T022）为硬约束：改动仅限透传字段与新增端点，任何触及引擎执行语义的方案一律回退重做并先改 010 spec。

## Notes

- 权威定义口径贯穿全程：**YAML 是权威，画布是投影**；序列化模块是唯一转换层，禁止在画布页或端点里散落转换逻辑。
- `layout` 是投影元数据：可丢失、可损坏忽略；不得因布局问题阻断装载/保存/执行。
- supervisor/hybrid 首期不可视化：UI 明示"暂支持 sequential/graph"，不静默降级为 graph。
- 不合并 user-web 既有 Skill 业务步骤编辑（`MySkillConfigPage`）的画布外语义：前者是 Skill 内步骤，后者是编排节点。
- i18n 新文案用中文 key，`t()` 缺翻译时回退中文本身，无需改 locale 文件（沿用 031 口径）。

## 验收状态（2026-10-24 交接复核）

- **已完成并勾选（30 项）**：T001–T027、T031–T033。证据：`services/chat-api/tests/orchestration/test_orchestration_canvas_api.py` 11 passed（端点信封、租户隔离、`layout` 清洗、环 422 与 `topo.CycleError` 同串、空图拒绝、发布权限 fail-closed、版本递增）；`services/chat-api/tests/orchestration/` 全量 91 passed（010 引擎零回归）；`OrchestrationCanvasPage.vue` / `NodePropertyPanel.vue` 经 `@vue/compiler-sfc` 3.4.38 编译通过。
- **未勾选（3 项）**：
  - **T028/T029（前端单测未落地）**：`apps/user-web/tests/` 下**无编排画布相关测试文件**（`ls | grep -i orchestr` 为空），序列化往返与前端校验的单元测试尚未编写；序列化逻辑目前仅经后端 11 项契约测试间接覆盖。
  - **T030（E2E）**：画布搭图 → 保存 → 010 引擎真实执行 → 发布 → 版本回看需真实 Mongo + 引擎运行环境；本机 docker 未运行，留待 staging。
- **联合改动已落地**：`services/chat-api/app/orchestration/store.py` 的 `_document_shape` 已透传 `layout`（唯一引擎侧改动），`engine.py`/`supervisor.py`/`topo.py`/`conditions.py` 零行为变更。
