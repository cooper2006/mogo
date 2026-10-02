# Tasks: Dream Cycle Self-Evolution (friction → draft → MR → deprecation)

**Input**: Design documents from `/specs/011-dream-cycle-self-evolution/`

**Prerequisites**: plan.md (required), spec.md (required)

**Clarify Decisions (governing tasks, 2026-07-08)**:
- friction 事件 = ①失败后成功（重试≥1）②人工纠正/驳回 ③用户显式标记"不顺"；**默认捕获前两类，第三类需用户主动标记**。
- 模式发现 = **Jaccard（场景特征向量）+ 编辑距离（动作序列）双指标**（首期不引入向量库）。
- 自动建 MR 阈值 = **Jaccard ≥ 0.7 且样本数 ≥ 5**；MR 目标 = **当前租户 Skill 草稿目录（004 草稿态）**，人工审阅后发布。
- 低采纳淘汰 = **持续 14 天曝光 ≥ 20 次且采纳率 < 10%** → deprecated；与 **016 共用 `skill_status.marked_low_quality` 标记位**。
- 扫描复用 **`scheduled_tasks`**（once/daily/weekly），不依赖 010 DAG。
- 生成侧质量门槛 = 必须含可执行测试样例且预览运行通过。

**Checklist Gate**: `checklists/requirements.md` 已 100% 勾选。
（**注意**：需求质量清单的 16/16 与实现清单的判级是两回事 ——
`checklists/implementation.md` 于 2026-10-02 逐项取证，结果是 `[x]` 55 · `[!]` 35 · `[-]` 6，
其「七类待办」需产品/规格拍板后才谈得上进入 `/speckit-converge`。）

**Organization**: 落点 = `chat-api/app/self_evolution/`（新模块）；复用 `scheduled_tasks`、`skills_specs`、004 `skill_lifecycle`。P2 后置。

> ### 实际模块落点（2026-10-02 核对补记 —— 下面任务里的扁平假设是错的）
>
> 本文件与 `checklists/implementation.md` 原先都假设存在一个扁平的
> `app/self_evolution/`，内含 `mr.py`/`deprecation.py`/`audit.py`/`config.py`。
> **实际是两层，且后四个模块不在核心包里**：
>
> | 层 | 路径 | 行数 | 内容 |
> |---|---|---|---|
> | 纯核心 | `services/chat-api/app/self_evolution/` | 704 | `__init__`/`fragment`/`friction`/`similarity`/`scanner`/`draft_gen`（无 DB、无 DSH 运行时） |
> | 集成层 | `services/chat-api/app/services/dream_cycle/` | 652 | `runner`/`friction`/`mr`/`deprecation`/`evolution_audit`（管道、MR、淘汰、审计、配置） |
>
> - `mr.py`、`deprecation.py` → **`app/services/dream_cycle/`**，不是 `app/self_evolution/`
> - **没有** `audit.py`、**没有** `config.py` —— 审计与配置都在
>   `app/services/dream_cycle/evolution_audit.py`（`EvolutionConfig` 就在该文件内）
> - 契约 **不在本 spec 目录下**：T019 的 `contracts/self-evolution.md` 实际位于**仓库根**
>   `contracts/self-evolution.md`（与 007/009/010 的契约同处 repo 级目录）
> - **011 目前无生产接线**：`app/` 下（排除这两层自身）对 `self_evolution`/`dream_cycle`
>   的引用数为 **0**，无 router、无 endpoint、未注册 `scheduled_tasks`。
>   即 T007 的「复用 `scheduled_tasks`」只是写法意图，`scanner.py:5-6` 仅在 docstring 提及。
> - 测试入口：`tests/self_evolution/` + `tests/services/test_dream_{cycle,evolution,audit_config}.py` → 66 passed

---

## Phase 1: Setup (Module Skeleton)

- [x] T001 创建 `services/chat-api/app/self_evolution/__init__.py` + 子模块骨架（friction/scanner/draft_gen/mr/deprecation）
- [x] T002 实现经验片段模型（场景特征向量/动作序列/结果/时间戳/来源会话 ID/用户反馈）+ 存储集合

## Phase 2: Foundational (Blocking Prerequisites)

- [x] T003 [P] 实现 `friction.py`：friction 检测（默认捕获失败后成功 + 人工纠正；用户显式标记需主动触发）
- [x] T004 [P] 实现相似度算法（Jaccard + 编辑距离双指标，首期集合/序列特征，不引入向量库）

## Phase 3: User Story 1 (P1) — friction 捕获经验片段

**Goal**: friction 事件自动捕获为结构化经验片段。
**独立测试**: 失败后成功/人工纠正 → 捕获片段；用户标记 → 捕获；片段字段完整。

- [x] T005 接入 friction 捕获（从会话/工具调用信号提取经验片段，落经验存储）
- [x] T006 US1 测试：三类 friction 捕获 + 片段字段完整性

## Phase 4: User Story 2 (P1) — 周期扫描发现模式

**Goal**: 周期扫描发现重复模式并生成 Skill 草稿。
**独立测试**: 重复模式 → 生成草稿（非直接发布）；扫描周期可配。

- [x] T007 实现 `scanner.py`：周期扫描（复用 `scheduled_tasks`）发现重复模式（Jaccard/编辑距离阈值）
- [x] T008 实现 `draft_gen.py`：Skill 草稿生成（进 004 草稿态，非直接发布）+ 生成侧质量门槛（含可执行测试样例 + 预览运行通过）
- [x] T009 实现草稿堆积上限（每租户保留最近 N 份未发布草稿，默认 100，可配）+ 同片段去重（Jaccard 保留最高置信）
- [x] T010 US2 测试：模式→草稿 + 非直接发布 + 生成门槛

## Phase 5: User Story 3 (P2) — 高置信自动建 MR

**Goal**: 达到置信阈值自动建 MR（不直接合入），低置信仅留草稿。
**独立测试**: Jaccard≥0.7 且样本≥5 → 建 MR；低置信 → 仅草稿。

- [x] T011 实现 `mr.py`：高置信（Jaccard≥0.7 且样本≥5）自动建 MR（Skill 定义 + 测试 + 说明，目标 004 草稿目录，人工审阅后发布）
- [x] T012 实现草稿 vs MR 边界（草稿 = 全部模式中间态；MR = 高置信在草稿基础上生成）
- [x] T013 US3 测试：高置信建 MR + 低置信仅草稿

## Phase 6: User Story 4 (P2) — 低采纳淘汰

**Goal**: 低采纳 Skill 自动标记淘汰，可人工恢复。
**独立测试**: 14 天曝光≥20 且采纳率<10% → deprecated；恢复 → 重置窗口。

- [x] T014 实现 `deprecation.py`：低采纳检测（14 天/≥20 曝光/<10%）+ 标记 deprecated（共用 016 `marked_low_quality` 位）
- [x] T015 实现淘汰生效范围（标记租户内）+ 人工恢复（重置采纳计数 + 重新推荐）
- [x] T016 US4 测试：低采纳标记 + 人工恢复

## Phase 7: Polish & Cross-Cutting Concerns

- [x] T017 [P] 自进化全链路审计：捕获/生成/MR/淘汰事件进审计
- [x] T018 [P] 阈值/周期可配置收尾（扫描周期、置信阈值、淘汰阈值）
- [x] T019 写 `quickstart.md` + `contracts/self-evolution.md`（经验片段 schema + MR 契约）

---

## Dependencies

```text
Phase 1 (骨架/片段模型) → Phase 2 (friction/相似度) → US1 → US2 → US3 → US4 → Polish
关键: T004 相似度被 US2/US3 复用；T008 复用 004 skill_lifecycle 草稿态；T014 与 016 共用标记位
```

## Parallel Opportunities
- T003/T004（Phase 2）可并行
- US3（MR）/US4（淘汰）可在 US2 完成后并行

## MVP Scope
- **最小 = Phase 1 + Phase 2 + US1**（T001–T006）：friction 捕获经验片段，即自进化闭环的输入端可用。
- 增量：US2（扫描+草稿）→ US3（MR）→ US4（淘汰）。

## Notes
- P2 后置，工作量最大；复用 `scheduled_tasks`/`skills_specs`/004 `skill_lifecycle`。
- 与 004（草稿上游）、002（经验源）、016（共用标记位）、010（纯调度）的跨特性关系已在 spec 双向声明。
- 未改 services 源码；本文件仅在 `specs/011-dream-cycle-self-evolution/` 下。
