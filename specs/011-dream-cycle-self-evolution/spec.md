# Feature Specification: Dream Cycle Self-Evolution

**Feature Branch**: `011-dream-cycle-self-evolution`

**Created**: 2026-07-08

**Status**: Draft

**Input**: 补齐规划文档清单 7（P2，后置，"Agent 越用越聪明"）"Dream Cycle 自进化"：三层 ①经验沉淀（friction 触发）②周期扫描自动发现重复模式生成 Skill 草稿 + 自动建 MR ③低采纳率自动淘汰。与特性 004（SkillHub 沉淀闭环"会话→经验→Skill"）互补。

## User Scenarios & Testing *(mandatory)*

用户故事按优先级排列，每个独立可交付、可测试。

### User Story 1 (P1) — 经验沉淀（friction 触发）

Agent 执行中遇到 friction（重试、纠错、失败后成功、人工介入）时自动捕获经验片段（friction → lesson）；经验片段结构化存储，可被后续复用。

**Acceptance Scenarios:**
- 工具调用失败后成功 → 捕获经验（"该场景下应先 X 再 Y"）
- 人工纠正后 → 捕获纠正经验
- 经验片段 → 落库，含场景/动作/结果/时间

### User Story 2 (P1) — 周期扫描发现重复模式 → Skill 草稿

周期扫描（scheduled job）分析经验片段，发现重复模式后自动生成 Skill 草稿；草稿带元数据（触发条件/步骤/预期效果），不直接发布。

**Acceptance Scenarios:**
- 相似经验重复 N 次 → 生成 Skill 草稿（非直接上架）
- 草稿 → 进 Skill 生命周期（特性 004 草稿态），可人工审阅后发布
- 无重复模式 → 不生成草稿

### User Story 3 (P2) — 自动建 MR（草稿→代码变更）

生成的 Skill 草稿可自动创建 MR/PR（含草稿内容 + 测试 + 说明），供人工审阅合入。

**Acceptance Scenarios:**
- 草稿达到置信阈值 → 自动建 MR
- MR → 含 Skill 定义 + 触发测试
- 人工审阅合入 → Skill 生效
- 低置信 → 不自动建 MR，仅留草稿

### User Story 4 (P2) — 低采纳率自动淘汰

Skill 采纳率（被实际复用次数/推荐次数）低于阈值且长期 → 自动标记淘汰/下线，避免低质量 Skill 污染市场。

**Acceptance Scenarios:**
- Skill 长期低采纳 → 标记 deprecated
- 标记后 → 不再推荐，可人工恢复
- 淘汰事件 → 审计记录

### Notes / Assumptions
- 本特性补齐规划文档清单 7（P2 后置，工作量最大），属缺口新特性
- 现状：仓库无通用自进化（grep 无 learnings/dream/jaccard；"learning" 命中集中在 browser/engine/workflow_cache，属浏览器工作流缓存，非框架层）
- 与特性 004（skillhub-lifecycle）的关系：自进化产出 Skill 草稿进 004 生命周期；004 已声明"会话→经验→Skill 沉淀闭环"为后续范围，本特性即该闭环引擎
- 与特性 002（session-versioning）的关系：经验沉淀源来自会话（commit/share）
- 与特性 010（DAG 编排）的关系：自进化本身可作为周期任务编排
- 置信阈值、扫描周期、淘汰阈值需 clarify
- 属 P2 后置，优先级低于 001/007/008/009/010

## Functional Requirements

- FR-1: friction 事件（重试/纠错/失败后成功/人工介入）自动捕获经验片段
- FR-2: 经验片段结构化存储（场景/动作/结果/时间）
- FR-3: 周期扫描发现重复模式，生成 Skill 草稿（非直接发布）
- FR-4: 草稿进特性 004 Skill 生命周期（草稿态，可审阅后发布）
- FR-5: 达到置信阈值自动建 MR（Skill 定义 + 测试 + 说明）
- FR-6: 低采纳率 Skill 自动标记淘汰/下线
- FR-7: 自进化事件（捕获/生成/MR/淘汰）进审计
- FR-8: 扫描周期、置信阈值、淘汰阈值可配置
- FR-9: 自动建 MR 前必须可人工审阅（不直接合入）

## Non-Goals
- 不实现 Skill 自动合入（必须人工审阅）
- 不实现跨租户经验共享（数据隔离）
- 不实现 Skill 效果 A/B 打分（属 004 市场强化后续）
- 不改变现有 Skill 发布契约（仅在其上游加自进化）
- 不实现通用记忆系统（Memory 粒度属规划文档清单 13）

## Success Criteria
- friction 事件 100% 可捕获经验片段
- 重复模式 100% 生成草稿（非直接发布）
- 低置信 0 次自动建 MR（仅高置信）
- 低采纳 Skill 100% 可标记淘汰
- 自进化全链路 100% 进审计

## Further Details
- 技术实现（friction 检测、模式发现、草稿生成、MR 创建）由 plan.md 承载
- 与特性 004/002/010 的关系已述
- 阈值与周期需 clarify；P2 后置，落地节奏由路线图定
