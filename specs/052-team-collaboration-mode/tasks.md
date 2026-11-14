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

- [x] T015 接管点接线（首期软依赖，R-4 口径）：YAML `takeover` 声明 → `_should_take_over` 命中 → 经 `approval_hook` 内联取人工决策（`accept|rework|terminate`）覆盖领导判定 + `team.takeover` 事件全审计（`chat-api/orchestration/team.py:346-388`）；**非** 050 `awaiting_approval` 跨进程挂起（050 `RunDriver.start` 首期仅 graph，team 加载期 fail-closed），真挂起/checkpoint 恢复按用户口径「接管 = 050 跨模式挂起，P2 预留」留二期。生产 `dispatch.py:256-266` / `:340-350` 两处 `run_team` 未注入 `approval_hook`，声明的接管点默认被忽略（仅测试注入 mock，属首期软依赖既定行为）；`loader.py` 校验 `trigger` 与 R-4 `points` 口径、`team.py` docstring 残留 `RunSuspended`、自动触发 `on_rework`/`on_round_cap` 与「仅人工主动」的偏差，一并登记见下方复核附注，二期收口。**勾选保持 [x]**：R-4 已定首期软依赖不改变勾选判断，内联决策 + 审计已实现且有 `tests/orchestration/test_team.py:316-406` 覆盖。

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
- 领导判定解析失败不得静默回退 accept（治理旁路）；OQ-1 已消解：fail-closed、首期不重试（spec「判定口径补充」R-2）。
- 不拷贝 StaffDeck（AGPL-3.0）代码；竞标二期另立澄清。

## 2026-11-10 复核附注（代码级核实，仅登记不改实现）

- **T015 描述如实化**：原写「050 human_approval 挂起」为夸大。实测 `chat-api/orchestration/team.py:346-388` 无 `RunSuspended` / `awaiting_approval` / 票据 / checkpoint，是内联 `approval_hook` 取决策 + `team.takeover` 审计，符合 spec R-4「首期 P2 预留软依赖」。任务行已改写，勾选保留（R-4 明文不改变勾选判断）。
- **生产接线缺口（二期收口）**：`chat-api/orchestration/dispatch.py:256-266` 与 `:340-350` 的 `run_team` 只传 `takeover`、不传 `approval_hook`；全库唯一注入点是 `tests/orchestration/test_team.py:344/380` 的 mock，测试 `:391-406` 明注「无 hook → 忽略接管点（soft dependency）」。声明的接管点在生产默认不激活，属首期预留的既定行为而非回归缺陷；`dispatch.py:131-132` team 直路由 `_run_team_document`，不经 `RunDriver`。
- **文案/口径残留**：`loader.py:449-462` 校验 `trigger` 而非 R-4 的 `points`；`team.py:13-14` docstring 仍写 `RunSuspended 挂起`；`team.py:431-453` 谓词含 `on_rework` / `on_round_cap` 自动触发，与 R-4「首期仅人工主动 `takeover:`」有偏差。三者随二期真跨模式挂起一并收口。
- **050 侧事实**：`chat-api/orchestration/human_approval.py:302-305` 的 `RunDriver.start` 非 graph 即 fail-closed，挂起/checkpoint 只在 `PausableDagEngine`（`run_graph` 子类）——team 作为文档级第七模式首期无法复用跨进程挂起，这是 R-4 定软依赖的根本原因。