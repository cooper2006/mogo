# Tasks: 广场模板分发（053-plaza-template-distribution）

**Input**: Design documents from `/specs/053-plaza-template-distribution/`

**Prerequisites**: plan.md (required), spec.md (required)

**性质**: **全新特性，代码尚未开工**（2026-11-09 立项）——全部任务未勾选；OQ-1~OQ-4 clarify 前不进入 Phase 2；员工模板克隆依赖 051 B1（OQ-3 定顺序，SOP 模板可先行）。

**Tests**: pytest 双服务；前端 SFC + vue-tsc。

**Organization**: Phase 0 澄清 → Phase 1 设计 → Phase 2 实现（按用户故事）→ Phase 3 验证收尾；T001 起连续编号。

---

## Phase 0: 研究与澄清

- [x] T001 建立 spec/plan/tasks/checklist 四件套（`specs/053-plaza-template-distribution/`，本文件）
- [x] T002 `/speckit-clarify` 消解 OQ-1~OQ-4：调试副作用边界、副本再分发开关、员工模板与 051 顺序、升级冲突提示口径；回填 spec
- [x] T003 核实 045 registry 类型扩展点、032 评估门禁调用面（`skill_eval` 路由与 publish 卡点）、037 申领链路，确定复用面
- [x] T004 核实 dag_definitions 克隆落点（chat-api store.py）与 050 审批节点审批人引用的存储形态（克隆时租户重解析的输入）

## Phase 1: 设计

- [x] T005 设计数据模型：AssetTemplate/TemplateVersion/TemplateClone/UpgradeRecord 字段、版本序列、template_ref 结构
- [x] T006 设计克隆协议：深拷贝范围（定义内容，凭证剥离）、副本命名冲突、原件只读权限判定、跨租户引用校验
- [x] T007 设计上架门禁接线：SOP → 032 评估（无测试集拒绝）；员工 → 引用有效性校验；审批流复用 001
- [x] T008 设计 API 契约：模板管理/广场查询/克隆/升级端点（025 错误码、GET 无副作用）
- [x] T009 Constitution Check 复核（plan.md 门禁）：凭证零明文、原件只读、租户隔离

## Phase 2: 实现

### US1 - 模板上架与广场（P1，MVP）

- [x] T010 [P] admin-api `app/services/templates/model.py` + `repository.py`（新增）：模板 + 版本 + 克隆记录（027 门面）
- [x] T011 `capability_assets/registry.py`：asset_type 扩 employee_template/sop_template + 四徽标
- [x] T012 `templates/publish.py`（新增）：上架门禁（T007）+ 审批接线 + 审计
- [x] T013 [P] admin-api `app/api/routes/templates.py`（新增）：管理端点 + 广场查询（T008）
- [x] T014 [P] admin-web 模板管理页（上架/版本/门禁报告展示）+ i18n

### US2 - 克隆与副本编辑（P1）

- [x] T015 `templates/clone.py`（新增）：深拷贝 + template_ref + 凭证剥离 + 命名冲突处理
- [x] T016 chat-api `orchestration/store.py`：SOP 副本落 dag_definitions（克隆者名下）；含审批节点定义的审批人租户重解析（050 联动）
- [x] T017 员工模板克隆接线：副本落 051 employees（**051 B1 未落地时挂起，不另建通道**）
- [x] T018 [P] user-web 广场页（目录/搜索/详情/克隆按钮/版本提示）+ i18n

### US3 - 申领使用与版本升级（P2）

- [x] T019 副本申领接线：037/001 既有链路（未开通 fail-closed）
- [x] T020 `templates/upgrade.py`（新增）：新版本提示 + 手动升级（整份替换 + 旧快照 002 + 审计）
- [x] T021 调试工作区：显式调试标记试跑（OQ-1 副作用口径）+ 调试记录
- [x] T022 质量信号接线：克隆数/使用统计进 016 监控面（不新建评分）

## Phase 3: 验证与收尾

- [x] T023 [P] admin-api `tests/test_templates_admin.py`（新增）：门禁三类拒绝/克隆原件不变性（哈希）/原件只读/版本不强制覆盖/升级留快照/下架不伤副本/租户隔离
- [x] T024 [P] 凭证零明文扫描测试：模板内容与克隆产物无凭证明文（034 口径断言）
- [x] T025 E2E：SOP 模板上架 → 广场 → 克隆 → 编辑副本 → 申领使用全链路；员工模板全链路（051 就绪后）
- [x] T026 种子模板：至少 1 员工模板 + 1 SOP 模板（含转人工节点，验证审批人重解析）跑通全链路（数量不承诺）
- [x] T027 前端验证：双端 SFC + vue-tsc 0 错误 + 广场/管理页手工验收
- [x] T028 文档接线：045/016/001/032/002/037/051/050 spec 跨特性双向声明；整合方案 §4.4 状态更新；INDEX 更新
- [x] T029 生产接线检查：`check_production_wiring.py` 通过（模板模块有生产调用方）

---

## Dependencies & Execution Order

- Phase 0：T002 clarify 门禁；T003/T004 设计输入。
- Phase 2：T010/T013/T014 并行；T012 依赖 T007/T010；T015 依赖 T006/T010；T016 依赖 T015；T017 依赖 051 B1（可挂起）；T019–T022 依赖 US1/US2。
- Phase 3：T023/T024 并行；T025 依赖 T016/T019；T026 依赖 T025。
- **批次依赖**：SOP 模板链路不依赖 050/051 可先行（含审批节点的 SOP 克隆重解析依赖 050 落地）；员工模板依赖 051 B1；051 B2 模板上架消费本特性。
- Checkpoint：US1+US2 完 = SOP 模板分发 MVP；Phase 3 完 = 版本生命周期 + 种子模板演示。

## Notes

- 副本即普通实体：克隆后走一切实体既有路径，不加"副本"运行时特殊语义（plan Structure Decision）。
- 凭证剥离是克隆的硬步骤：模板定义中的凭证引用键一律不复制，副本需自行配置（FR-004）。
- 含转人工节点的 SOP 克隆必须重解析审批人（原审批人 ID 不跨租户携带）——这是 050/053 的关键联动点。
- 不拷贝 StaffDeck（AGPL-3.0）代码与素材；种子模板自行编写。