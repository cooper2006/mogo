# Custom Implementation Checklist: 011 Dream Cycle Self-Evolution

**Feature**: `011-dream-cycle-self-evolution`
**Generated**: 2026-10-01
**Source**: spec.md + tasks.md + cross-feature dependencies

> **状态：尚未逐项核对（not yet verified）。**
>
> 本清单生成后未经对照实现勾选，因此**全项为空不代表功能未实现**——011 的
> 实现在 `services/chat-api/app/self_evolution/`（`fragment.py`、`friction.py`、
> `similarity.py`、`scanner.py`、`draft_gen.py`），同目录的 `tasks.md` 19/19 与
> `requirements.md` 16/16 均已勾选。
>
> 这份 96 项清单把实施细节拆得更细，勾选它需要逐项回实现与测试取证，是独立
> 于 011 功能本身的一项治理工作，尚未进行。**在完成核对前，不要把它当作
> 「011 未完成」的证据，也不要批量勾选。**
>
> 对照案例：020 的审计（`docs/020-platform-multi-tenancy-SDD审计报告.md` §11.2）
> 曾判定 T045「勾选不实」——那是**清单已勾但交付物为空**；此处是**交付物已在
> 但清单未勾**。两个方向都会让清单失去可信度，处理方式相同：以可复现的取证为
> 准，不以勾选状态为准。

---

## Phase 1: Module Structure & Data Model

- [ ] T001 创建 `services/chat-api/app/self_evolution/__init__.py` + 子模块骨架
- [ ] T002 实现经验片段数据模型（场景特征向量/动作序列/结果/时间戳/来源会话ID/用户反馈）
- [ ] T002-1 验证经验片段存储集合初始化（集合/表/索引）
- [ ] T002-2 验证字段完整性：`scene_features`、`action_sequence`、`outcome`、`timestamp`、`session_id`、`user_feedback`

## Phase 2: Friction Detection

- [ ] T003 实现 `friction.py`：失败后成功（重试≥1）自动捕获
- [ ] T003-1 验证"工具调用失败→重试成功"场景 → friction 事件触发
- [ ] T003-2 验证"人工纠正/驳回"场景 → friction 事件触发
- [ ] T003-3 验证"用户显式标记不顺"需主动触发，默认不捕获
- [ ] T003-4 验证摩擦事件日志记录（审计字段：event_type、session_id、tool_name、retry_count）

## Phase 3: Similarity Algorithm

- [ ] T004 实现 `similarity.py`：Jaccard 相似度（场景特征向量）
- [ ] T004-1 验证 Jaccard ≥ 0.7 判定为"高相似"
- [ ] T004-2 验证 Jaccard < 0.7 判定为"低相似"
- [ ] T004-3 实现编辑距离（动作序列）
- [ ] T004-4 验证双指标联动：Jaccard + 编辑距离共同判定模式重复
- [ ] T004-5 验证非向量库实现（集合/序列特征，无外部依赖）

## Phase 4: Pattern Scanner (US2)

- [ ] T007 实现 `scanner.py`：周期扫描（复用 `scheduled_tasks`）
- [ ] T007-1 验证调度周期可配置（once/daily/weekly）
- [ ] T007-2 验证扫描发现重复模式 → 生成 Skill 草稿
- [ ] T007-3 验证无重复模式 → 不生成草稿
- [ ] T007-4 验证扫描日志记录（scan_id、pattern_count、draft_count）

## Phase 5: Draft Generation (US2)

- [ ] T008 实现 `draft_gen.py`：Skill 草稿生成
- [ ] T008-1 验证草稿进入特性 004 草稿态（非直接发布）
- [ ] T008-2 验证草稿元数据：触发条件/步骤/预期效果
- [ ] T008-3 验证质量门槛：含可执行测试样例 + 预览运行通过
- [ ] T008-4 验证预览失败 → 不生成草稿（避免污染市场）

## Phase 6: Draft Lifecycle Management

- [ ] T009 实现草稿堆积上限（每租户保留最近 N 份，默认 100）
- [ ] T009-1 验证超限清理最旧草稿
- [ ] T009-2 验证同片段 Jaccard 去重（保留最高置信草稿）
- [ ] T009-3 验证草稿计数统计（当前草稿数/上限）

## Phase 7: Automatic MR Generation (US3)

- [ ] T011 实现 `mr.py`：高置信自动建 MR
- [ ] T011-1 验证置信阈值：Jaccard ≥ 0.7 且样本数 ≥ 5
- [ ] T011-2 验证 MR 目标：当前租户 Skill 草稿目录（004 草稿态）
- [ ] T011-3 验证 MR 内容：Skill 定义 + 测试 + 说明
- [ ] T011-4 验证低置信（Jaccard < 0.7 或样本 < 5）→ 仅留草稿，不建 MR
- [ ] T011-5 验证 MR 不可自动合入（必须人工审阅）

## Phase 8: Draft vs MR Boundary

- [ ] T012 验证草稿与 MR 关系：
  - 草稿 = 全部模式中间态（高/低置信都生成）
  - MR = 仅高置信在草稿基础上生成
  - 二者非同一物

## Phase 9: Low Adoption Deprecation (US4)

- [ ] T014 实现 `deprecation.py`：低采纳检测
- [ ] T014-1 验证淘汰阈值：14 天曝光 ≥ 20 次且采纳率 < 10%
- [ ] T014-2 验证采纳率计算：被复用次数 / 推荐曝光次数
- [ ] T014-3 验证标记 deprecated 后不再推荐
- [ ] T014-4 验证共用 016 `skill_status.marked_low_quality` 标记位（避免双写）

## Phase 10: Deprecation Recovery

- [ ] T015 实现淘汰恢复逻辑
- [ ] T015-1 验证人工恢复 → 重置采纳计数
- [ ] T015-2 验证恢复后重新进入推荐
- [ ] T015-3 验证恢复审计记录

## Phase 11: Cross-Feature Integration

### 与 004 (skillhub-lifecycle)
- [ ] XF004-1 验证草稿进入 004 草稿态
- [ ] XF004-2 验证 004 可反向声明"011 草稿是其上游来源"
- [ ] XF004-3 验证 Skill 生命周期流转：草稿 → 审阅 → 发布（011 不越过审阅）

### 与 002 (session-versioning)
- [ ] XF002-1 验证经验沉淀源来自会话 commit/share
- [ ] XF002-2 验证 session_id 可追溯至 002 会话快照
- [ ] XF002-3 验证数据流对齐：会话 → 摩擦事件 → 经验片段

### 与 010 (dag-orchestration)
- [ ] XF010-1 验证扫描 job 复用 `scheduled_tasks`
- [ ] XF010-2 验证不依赖 010 DAG 引擎（纯调度任务即可）
- [ ] XF010-3 验证 once/daily/weekly 调度支持

### 与 016 (skill-market-hardening)
- [ ] XF016-1 验证共用 `skill_status.marked_low_quality` 标记位
- [ ] XF016-2 验证 011 从"低采纳沉淀侧"标记，016 从"市场运营侧"标记
- [ ] XF016-3 验证避免双写（同一标记位）

## Phase 12: Audit & Observability

- [ ] T017 实现自进化全链路审计
- [ ] T017-1 验证摩擦捕获事件记录（event_type=friction_captured）
- [ ] T017-2 验证草稿生成事件记录（event_type=draft_generated）
- [ ] T017-3 验证 MR 创建事件记录（event_type=mr_created）
- [ ] T017-4 验证淘汰标记事件记录（event_type=skill_deprecated）
- [ ] T017-5 验证恢复事件记录（event_type=skill_restored）
- [ ] T017-6 验证审计事件经 001 system_audit 落点

## Phase 13: Config Management

- [ ] T018 实现阈值/周期可配置
- [ ] T018-1 验证扫描周期配置（scan_interval_hours）
- [ ] T018-2 验证置信阈值配置（jaccard_threshold=0.7, min_samples=5）
- [ ] T018-3 验证淘汰阈值配置（low_adoption_window_days=14, min_exposure=20, rate_threshold=0.10）
- [ ] T018-4 验证草稿堆积上限配置（max_drafts_per_tenant=100）
- [ ] T018-5 验证 shadow_ratio 配置（影子流量比例）

## Phase 14: Documentation

- [ ] T019 写 `quickstart.md` + `contracts/self-evolution.md`
- [ ] T019-1 验证经验片段 schema 文档完整
- [ ] T019-2 验证 MR 契约文档完整
- [ ] T019-3 验证 API/模块使用示例

## Phase 15: Testing

### Unit Tests
- [ ] T006 US1 测试：三类 friction 捕获 + 片段字段完整性
- [ ] T010 US2 测试：模式→草稿 + 非直接发布 + 生成门槛
- [ ] T013 US3 测试：高置信建 MR + 低置信仅草稿
- [ ] T016 US4 测试：低采纳标记 + 人工恢复

### Integration Tests
- [ ] IT001 端到端：摩擦事件 → 经验沉淀 → 模式扫描 → 草稿生成
- [ ] IT002 端到端：高置信模式 → MR 创建 → 人工审阅 → Skill 发布
- [ ] IT003 端到端：低采纳 Skill → 标记淘汰 → 恢复流程

### Edge Case Tests
- [ ] ET001 无摩擦事件场景（空经验库）
- [ ] ET002 单条经验无重复模式
- [ ] ET003 草稿堆积超限清理
- [ ] ET004 同片段多草稿去重
- [ ] ET005 跨租户数据隔离验证
- [ ] ET006 阈值边界值测试（Jaccard=0.7, samples=5, exposure=20, rate=10%）

## Phase 16: Security & Compliance

- [ ] SEC001 验证数据隔离：经验片段按租户隔离，不跨租户共享
- [ ] SEC002 验证审计日志完整性（不可篡改）
- [ ] SEC003 验证配置文件安全（密钥/凭据不提交）
- [ ] SEC004 验证 MR 创建权限（仅授权 Agent 可自动建 MR）

## Success Criteria Verification

- [ ] SC001 摩擦事件 100% 可捕获经验片段
- [ ] SC002 重复模式 100% 生成草稿（非直接发布）
- [ ] SC003 低置信 0 次自动建 MR（仅高置信）
- [ ] SC004 低采纳 Skill 100% 可标记淘汰
- [ ] SC005 自进化全链路 100% 进审计

---

**Checklist Gate**: 全部条目需勾选方可进入 `/speckit-converge` 验收阶段。
**Review Ownership**: 实现人逐项自检 + 评审人抽检。
**Marker Semantics**: `[x]` 表示"功能已实现且测试通过"。
