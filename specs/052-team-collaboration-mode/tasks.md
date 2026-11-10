# Tasks: 团队协作模式（052-team-collaboration-mode）

**Input**: Design documents from `/specs/052-team-collaboration-mode/`

**Prerequisites**: plan.md (required), spec.md (required)；**050 已落地**（硬依赖：run_store + human_approval）

**性质**: **全新特性，代码尚未开工**（2026-11-09 立项）——全部任务未勾选；OQ-1~OQ-4 clarify 与 050 落地双门禁。

**Tests**: `services/chat-api/tests/orchestration/` pytest（新增 test_team.py；既有六模式测试零修改全绿）。

**Organization**: Phase 0 澄清 → Phase 1 设计 → Phase 2 实现 → Phase 3 验证与接线；T001 起连续编号。

---

## Phase 0: 研究与澄清

- [x] T001 建立 spec/plan/tasks/checklist 四件套（`specs/052-team-collaboration-mode/`，本文件）
- [x] T002 确认 050 已落地（run_store checkpoint/恢复 + human_approval 挂起/决策可用），核实其快照结构可承载 TeamRunState/黑板
- [x] T003 `/speckit-clarify` 消解 OQ-1~OQ-4：领导判定 JSON schema 与解析失败语义、重指派上限默认值、接管触发条件、黑板尺寸上限；回填 spec
- [x] T004 核实 supervisor.py 拆解/聚合语义与 044 dispatch 路由扩展点，确定 team 复用面与独立口径边界

## Phase 1: 设计

- [x] T005 设计 team.py 契约：TeamPlan/BlackboardEntry/ReviewVerdict/TeamRunState 字段与执行签名（runner 注入）
- [x] T006 设计验收循环状态机：accept/rework 迁移、轮次计数、重指派计数、达上限 fail-closed、接管冻结语义
- [x] T007 设计 loader/dispatch 扩展：team 形状校验（members 存在性/轮次钳制/接管点）、payload 新键、文档级与节点级路由（044 wrap_node_runner 口径）
- [x] T008 设计契约文档增量：010 contracts/orchestration.md 七模式表 + team YAML 形态（示例可加载）
- [x] T009 Constitution Check 复核（plan.md 门禁）：无死循环、既有六模式零改动、无新集合

## Phase 2: 实现

### US1 - 拆解指派 + 黑板（P1，MVP）

- [x] T010 [P] `orchestration/team.py`（新增）：领导拆解 → TeamPlan 校验 → 成员执行（max_concurrency 约束）→ 黑板写入（作者/版本）
- [x] T011 `graph.py` + `loader.py` + `dispatch.py`：VALID_MODES 七模式 + team 形状校验 + 路由（T007）
- [x] T012 成员 employee_id 软依赖接线：051 已落地则注入，否则忽略记事件（FR-010）

### US2 - 验收循环（P1）

- [x] T013 验收循环：ReviewVerdict 解析（OQ-1 schema，fail-closed）+ rework 意见传递 + 轮次钳制 + 达上限团队失败
- [x] T014 单成员失败处理：失败传播 + 重指派（上限内）+ 失败阈值判定（OQ-2 口径）

### US3 - 人工接管（P2）

- [x] T015 接管点接线：触发条件命中 → 050 human_approval 挂起 → 人工决策覆盖领导判定 + 审计

### US4 - 契约（P2）

- [x] T016 [P] 010 contracts/orchestration.md：七模式表 + team YAML 形态与黑板/验收语义

## Phase 3: 验证与接线

- [x] T017 [P] `tests/orchestration/test_team.py`（新增）：拆解指派/黑板版本与命名空间/验收 accept-rework/轮次钳制/达上限 fail-closed/单成员失败与重指派/领导失败/分派非法
- [x] T018 [P] 接管与恢复测试：接管挂起-决策-覆盖审计；重启后团队运行恢复（050 语义）；team 子节点原子性（044 R-16）
- [x] T019 回归门禁：既有六模式测试**零修改**全绿；`git diff` 断言 engine/supervisor/round_robin/debate 无行为改动
- [x] T020 E2E：完整团队工作流（拆解→双成员→黑板→rework 一轮→accept）+ 契约示例可执行
- [x] T021 文档接线：010/044/050/051 spec 跨特性双向声明；整合方案 §4.3 状态更新；INDEX 更新
- [x] T022 生产接线检查：`check_production_wiring.py` 通过（team 有生产调用方或契约示例消费路径声明）

---

## Dependencies & Execution Order

- **外部门禁**：050 落地（T002）+ OQ clarify（T003）先于 Phase 2。
- Phase 2：T010/T011 并行后合流；T013 依赖 T010；T015 依赖 T013 + 050；T016 可并行。
- Phase 3：T017/T018 并行；T019 回归门禁先于 T020–T022。
- **批次顺序**：050 → 052（硬依赖）；051 软依赖不阻塞；053 与本特性无依赖可并行。
- Checkpoint：US1+US2 完 = 有验收闭环的团队执行（MVP）；Phase 3 完 = 接管/恢复/契约齐备。

## Notes

- 验收轮次与重指派次数是两个独立上限，均 fail-closed——不得合并为单一计数器（语义不同：验收针对产出质量，重指派针对成员失败）。
- 黑板键含作者前缀做命名空间隔离，跨成员同键不覆盖（Edge Cases 口径）。
- 领导判定解析失败不得静默回退 accept（治理旁路）；OQ-1 定 fail-closed 或有限重试。
- 不拷贝 StaffDeck（AGPL-3.0）代码；竞标二期另立澄清。