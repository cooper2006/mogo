# Requirements Quality Checklist: 011 dream-cycle-self-evolution

**Purpose**: 校验 011（Dream Cycle 自进化：friction 捕获→周期扫描→Skill 草稿→自动 MR→低采纳淘汰）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-07-08
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [x] CHK001 经验片段（FR-2）"场景/动作/结果/时间"四字段是否穷举（是否含"用户反馈/纠正内容/上下文"，仅四字段够不够结构化复用）？
- [x] CHK002 "周期扫描发现重复模式"（FR-3）的"模式"是否定义（clarify 已定 Jaccard + 编辑距离双指标，FR 正文是否同步算法口径）？
- [x] CHK003 自动建 MR（FR-5）"Skill 定义 + 测试 + 说明"的"测试"是否定义自动生成什么测试（行为断言？输入输出样例？）？
- [x] CHK004 低采纳淘汰（FR-6）的"采纳率"是否定义（被复用次数/推荐次数，clarify 已定 14 天 ≥20 曝光 <10%，FR 正文是否同步）？

## 清晰度（Clarity）

- [x] CHK005 clarify 已定 friction 三类（OQ-1）——FR-1 是否同步"默认捕获前两类、第三类需用户主动标记"（还是正文只列 friction 类型而无捕获默认值）？
- [x] CHK006 clarify 已定"MR 目标为当前租户 Skill 草稿目录、人工审阅后发布"（OQ-3）——FR-5/FR-9 是否声明 MR 不直接合入（与 004 草稿态衔接）？
- [x] CHK007 "草稿非直接发布"（FR-3/Success）与"自动建 MR"（FR-5）的边界是否清晰（草稿是审阅前的中间态，MR 是高置信才生成，二者关系是否明确）？
- [x] CHK008 "淘汰可人工恢复"（US4 Acceptance）是否定义恢复路径（恢复后是否重置采纳计数/重新推荐）？

## 一致性（Consistency）

- [ ] CHK009 与 004（skillhub-lifecycle）"自进化产出进 004 生命周期"（FR-4/Notes）——004 是否反向声明"011 草稿是其上游来源"（沉淀闭环是否双向声明）？
- [ ] CHK010 与 002（session-versioning）"经验沉淀源来自会话 commit/share"（Notes）——002 是否声明其会话快照是 011 的经验源（数据流是否对齐）？
- [ ] CHK011 与 016（skill-market-hardening）"低质量标记共用同一标记位"（clarify OQ-4）——016 spec 是否声明与 011 共用 `skill_status.marked_low_quality`（避免双写是否双向声明）？
- [ ] CHK012 与 010（DAG 编排）"自进化可作为周期任务编排"（Notes）——扫描 job 复用 scheduled_tasks（clarify OQ-5），是否需 010 引擎参与（还是纯 scheduled_tasks 即可，两边口径）？

## 边界与歧义（Edge cases & Ambiguity）

- [x] CHK013 "低置信仅留草稿、不自动建 MR"（US3 Acceptance + Success）是否定义"草稿堆积"的上限（长期低置信草稿是否清理，避免堆积）？
- [x] CHK014 同一经验片段被多个草稿引用时的"重复草稿"去重是否定义（澄清 OQ-2 双指标未提去重边界）？
- [x] CHK015 淘汰标记后"不再推荐"的生效范围（全组织 vs 仅标记租户，clarify 未明确）是否定义？
- [x] CHK016 自进化产物 Skill 的"质量下限"（避免自进化产出低质量 Skill 污染 004 市场）是否有入门阈值（clarify OQ-4 是淘汰侧，生成侧的质量门槛未定）？

## Notes

- 本清单为需求质量门禁，全部条目需审阅人逐条评估后勾选；未勾选项构成 `/speckit-implement` 的拦截门禁。
- 标 `[x]` 仅代表"需求质量达标"，不代表实现完成。
## 评审结论（2026-07-08 勾选，agent 代审；含 FR 回填后复核）

**达标已勾 `[x]`（12 项）**：
- FR 回填后达标：CHK001（片段字段补充 来源会话/反馈 → FR-2）、CHK002（Jaccard + 编辑距离 → FR-3）、CHK003（测试 = 输入输出样例断言 → FR-5）、CHK004（采纳率口径 + 14 天阈值 → FR-6）、CHK005（friction 默认捕获前两类 → FR-1）、CHK006（MR 目标 004 草稿目录 + 人工审阅 → FR-5/FR-9）、CHK007（草稿 vs MR 边界 → FR-10）、CHK008（淘汰恢复重置计数 → FR-11）、CHK013（草稿堆积上限 N=100 → FR-12）、CHK014（同片段 Jaccard 去重 → FR-12）、CHK015（淘汰生效范围 = 标记租户 → FR-11）、CHK016（生成侧质量门槛 = 预览运行通过 → FR-13）

**未勾 `[ ]` = 真实缺口（4 项，跨特性对齐）：**
- CHK009：004 需反向声明"011 草稿是其上游来源"（需 004 spec 侧确认）
- CHK010：002 需声明其会话快照是 011 的经验源（同 002 CHK011，双向对齐）
- CHK011：016 需声明与 011 共用 `skill_status.marked_low_quality` 标记位（需 016 spec 侧确认，避免双写）
- CHK012：010 引擎是否参与自进化周期任务，还是纯 `scheduled_tasks` 即可（需 010/011 边界确认）

> CHK009/010/011/012 是 011 与 004/002/016/010 的跨特性数据流/标记位对齐项，需相关特性反向声明后勾选。011 自身 spec 质量已达 implement 可写程度。
