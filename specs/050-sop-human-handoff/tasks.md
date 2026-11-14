# Tasks: SOP 转人工节点（050-sop-human-handoff）

**Input**: Design documents from `/specs/050-sop-human-handoff/`

**Prerequisites**: plan.md (required), spec.md (required)

**性质**: **全新特性，代码尚未开工**（2026-11-09 立项）——全部任务未勾选；OQ-1~OQ-4 clarify 完成前不进入 Phase 2。

**Tests**: `services/chat-api/tests/orchestration/` pytest（新增三测试文件；既有测试零修改全绿）。

**Organization**: Phase 0 澄清 → Phase 1 设计 → Phase 2 实现（按用户故事）→ Phase 3 验证与接线；T001 起连续编号。

---

## Phase 0: 研究与澄清

- [x] T001 建立 spec/plan/tasks/checklist 四件套（`specs/050-sop-human-handoff/`，本文件）
- [x] T002 `/speckit-clarify` 消解 OQ-1~OQ-4：超时默认时长与范围、IM 主动推送渠道边界、`needs_review` 处置入口、终态运行保留期；决策回填 spec「待澄清」节
- [x] T003 核实 `ApprovalRuntime` 票据 TTL 与挂起时长的匹配（现票据 5min TTL 口径是否适用于长时挂起——若不适配，设计"待办长效 + 决策时即时发票据"的两段式，回填 spec 决策 #1）
- [x] T004 核实 `scheduled_tasks` 恢复范式（`tests/scheduled_tasks/test_scheduler_recovery.py`、scheduler 租约实现）与 027 门面新集合注册方式，确定 run_store 恢复与双后端落点

## Phase 1: 设计

- [x] T005 设计 `run_store.py` 契约：OrchestrationRun 状态机、RunCheckpoint 结构、定义版本快照内嵌形态、恢复扫描租约协议
- [x] T006 设计 `human_approval.py` 契约：ApprovalNodeConfig 字段、挂起/决策/超时签名（runner 注入，transport-agnostic）、与 ApprovalRuntime 的票据衔接（含 T003 结论）
- [x] T007 设计 loader 形状校验：`approver`/`on_reject` 存在性 fail-closed（与 044 `_validate_044_shapes` 同风格）；节点类型常量落点（不改 VALID_MODES）
- [x] T008 设计待办与决策 API：`orchestration_runs.py` 端点清单（查询/待办/决策/取消/改派）、鉴权与租户隔离、错误码（025 口径）
- [x] T009 设计契约文档增量：010 `contracts/orchestration.md` 审批节点 YAML 形态 + 运行状态机语义
- [x] T010 Constitution Check 复核（plan.md 门禁）：fail-closed 全覆盖、既有六模式零改动、无新依赖

## Phase 2: 实现

### US1 + US2 - 审批节点与运行持久化（P1，MVP）

- [x] T011 [P] `orchestration/run_store.py`（新增）：运行仓库 + checkpoint + 状态机 + 恢复扫描（租约）；经 027 门面双后端
- [x] T012 [P] `orchestration/human_approval.py`（新增）：挂起执行器 + 决策回调（批准续跑/驳回分支/默认终止）+ 超时 fail-closed
- [x] T013 `orchestration/loader.py` + `graph.py`：审批节点形状校验 + 节点类型常量（T007）
- [x] T014 `orchestration/dispatch.py` + `engine.py`：checkpoint 钩子 + 含审批节点运行经 run_store 驱动；无审批节点路径行为不变
- [x] T015 `api/endpoints/orchestration_runs.py`（新增）：T008 端点 + 站内待办数据面 + 审计事件（挂起/批准/驳回/超时/改派/取消）
- [x] T016 通知接线：013 `render_reply` 渲染待办/结果通知；应答式触达回落（OQ-2 口径）

### US3 - 异常 fail-closed（P1）

- [x] T017 超时判定器（恢复扫描驱动，不依赖进程内定时器）+ 无效审批人改派 `needs_review` 路径 + 快照写失败 fail-closed

### US4 - 画布与契约（P2）

- [x] T018 [P] user-web 039 画布：human_approval 节点卡片 + 属性面板（审批人/超时/驳回分支）+ 中英 i18n；画布 ↔ YAML 往返含新字段。审批人属性面板已落地为「本租户部门树 + end_users 候选」单选选择器（`ApproverPicker.vue`，复用项目成员选择器数据层 `listProjectDepartments` / `listProjectMemberCandidates`，支持按部门筛选与关键字搜索），替代原自由文本 user_id 输入框；写入值仍为 `approver` user_id 字符串，与 YAML 序列化及 loader 存在性校验向后兼容（2026-11-10 实现）。
- [x] T019 [P] 010 `contracts/orchestration.md`：审批节点 YAML 形态 + 状态机语义（示例可被 loader 加载）

## Phase 3: 验证与接线

- [x] T020 [P] `tests/orchestration/test_human_approval.py`（新增）：挂起/批准续跑/驳回分支与默认终止/超时/自审拒绝/重复票据拒绝/无效审批人
- [x] T021 [P] `tests/orchestration/test_run_store.py`（新增）：checkpoint 完整性/定义版本锁定/双后端口径/状态机迁移
- [x] T022 [P] `tests/orchestration/test_run_recovery.py`（新增）：重启恢复续跑/已完成节点零重跑（调用计数）/并发恢复租约/崩溃节点 needs_review
- [x] T023 回归门禁：`tests/orchestration/` 既有测试**零修改**全绿；不含审批节点的工作流行为不变
- [x] T024 E2E：双审批节点合同审查形态工作流（挂起→批准→再挂起→批准→完成）+ 驳回/超时路径；审计链还原决策序列
- [x] T025 前端验证：SFC 编译 + vue-tsc 0 错误 + 画布往返手工验收
  - 已通过：`npx vue-tsc --noEmit` 0 错误；两个改动的 .vue（NodePropertyPanel / OrchestrationCanvasPage）经 `@vue/compiler-sfc` 解析+编译通过；转换层（canvasSchema）画布↔YAML 往返脚本校验字段无损（approver/prompt/on_reject/timeout 均回读）。
  - 未执行：浏览器交互式"拖入节点→导出→再导入"人工验收（本会话无法操作浏览器）；建议按 US4 Acceptance Scenario 1 在开发环境补一次人工点击验收。
- [x] T026 文档接线：010/001/002/013/039 spec 跨特性关系补记双向声明；`docs/MOGO-StaffDeck整合方案.md` §4.1 标注立项状态；INDEX 勾选状态更新
- [x] T027 生产接线检查：`services/chat-api/scripts/check_production_wiring.py` 通过（新模块有生产调用方，非 hollow）

---

## Dependencies & Execution Order

- Phase 0：T002（clarify）是 Phase 2 的门禁；T003 结论决定 T006/T012 票据衔接方式；T004 是 T011 输入。
- Phase 1：T005–T009 为 Phase 2 契约；T010 门禁先于 Phase 2。
- Phase 2：T011/T012 可并行；T013 依赖 T007；T014 依赖 T011/T012；T015 依赖 T005/T008；T017 依赖 T011；T018/T019 可并行且依赖 T013。
- Phase 3：T020–T022 可并行；T023 回归门禁先于 T024–T027。
- **批次依赖**：052 的异步执行与人工接管消费 T011 运行持久化与 T012 审批节点——**本特性必须先于 052 落地**。
- Checkpoint：Phase 2 US1+US2 完 = 可挂起可恢复的审批工作流（MVP）；Phase 3 完 = 异常全 fail-closed + 画布契约齐备 + 回归全绿。

## Notes

- 审批是节点类型不是文档模式：`VALID_MODES` 不扩展，首期仅 graph 模式的图可嵌入审批节点（其它模式声明→加载期 fail-closed，见 R-9 / plan Structure Decision）。
- 票据 TTL 与长时挂起的匹配是最大实现风险（T003）：若 `ApprovalRuntime` 票据短 TTL 不适配，采用"待办长效 + 决策时即时发票据"两段式，不改 ApprovalRuntime 本体语义。
- 超时判定由恢复扫描驱动而非进程内定时器——挂起运行不占协程，进程重启不丢超时判定。
- 不拷贝 StaffDeck（AGPL-3.0）任何代码；设计借鉴已在整合方案 §6 声明。

## 代审附注（2026-11-10，reviewer agent 复核发现，已核实并消解）

以下 4 项为 050 需求质量代审时发现的「文档/契约 ↔ 实现」不一致，已于 2026-11-10 复核并消解（本轮仅改文档、不动运行时代码）；判定口径由 spec「判定口径补充」R 条在需求层精确化。原始 4 条全文保留供追溯，逐条附处置结论：

1. `plan.md` Structure Decision 称「任何模式可嵌审批节点」，与契约 §6 / R-9「仅 graph 支持」冲突；`_validate_050_shapes` 缺相应校验。
   - 处置：文案已修正（plan.md:91 / tasks.md:77 改为「首期仅 graph」）；实现侧无需改动。R-9 中「实现侧须在 `_validate_050_shapes` 补该限制校验」仍未兑现——补它会把拒绝点从 start 提前到 load，属改运行时行为，本轮不做；功能由 human_approval.py:302-305 的 RunDriver.start fail-closed 兜底，留作后续。
2. 状态机遗漏 `failed` 状态，且把 `needs_review` 误列为终态。
   - 处置：状态机文案已修正（spec.md:128 与 010 契约 §6 L150 统一为「非终态/终态」两分）；实现侧无需改动（run_store.py:38-39 的 TERMINAL_STATES / ACTIVE_STATES 已正确）。
3. 决策 #1「挂起时发票据」与两段式（决策时即时签发 5min 票据）冲突；**R-2 已在需求层精确化**，实现与契约文案需同步。
   - 处置：spec.md / plan.md 旧一段式票据表述已全文改为两段式口径；实现侧无需改动（human_approval.py:120-143 挂起不 issue、:356-375 决策时签发并即时消费、TICKET_TTL=300）。R-1~R-15 原文未改。
4. 契约称票据「不依赖进程内存」不准确：`ApprovalRuntime` 实为进程内字典，靠单次请求闭环；应改为如实描述或补持久化。
   - 处置：契约 §6 L164-165 已改为如实描述（票据存 ApprovalRuntime 进程内字典、单次决策请求内闭环、不依赖跨进程票据持久化）；实现侧无需改动，不补持久化（plan.md:76 标注 approval_runtime.py 零改动）。