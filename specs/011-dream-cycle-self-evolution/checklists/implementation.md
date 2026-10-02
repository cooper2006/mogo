# Custom Implementation Checklist: 011 Dream Cycle Self-Evolution

**Feature**: `011-dream-cycle-self-evolution`
**Generated**: 2026-10-01
**Source**: spec.md + tasks.md + cross-feature dependencies
**Verified**: 2026-10-02 — 逐项回实现与测试取证（见文末「核对方法与结论」）
**Verdict**: `[x]` 55 · `[!]` 35 · `[-]` 6（共 96；判级口径见本节末「勾选口径」）

> ## 核对结论摘要
>
> **这份清单是按「想象中的模块布局」写的，与真实实现的结构不一致** —— 这是核对时最重要的发现，
> 也是它迟迟没被勾选的真实原因：照着清单找文件会找不到，于是谁也不敢勾。
>
> **1. 清单里的模块名多数不存在。** 清单通篇假设一个扁平的 `app/self_evolution/` 包，包含
> `friction.py` / `similarity.py` / `scanner.py` / `draft_gen.py` / `mr.py` / `deprecation.py`
> / `audit.py` / `config.py`。实际是**两层**：
>
> | 层 | 路径 | 行数 | 性质 |
> |---|---|---|---|
> | 纯核心 | `services/chat-api/app/self_evolution/` | 704 | `__init__` / `fragment` / `friction` / `similarity` / `scanner` / `draft_gen`：无 DB、无 DSH 运行时依赖 |
> | 集成层 | `services/chat-api/app/services/dream_cycle/` | 652 | `runner` / `friction` / `mr` / `deprecation` / `evolution_audit`：管道、MR、淘汰、审计、配置 |
>
> `mr.py`、`deprecation.py`、`audit.py`、`config.py` **不在** `app/self_evolution/` 下 ——
> MR 与淘汰在 `app/services/dream_cycle/`（`mr.py`、`deprecation.py`），审计 + 配置合并进
> 单个 `evolution_audit.py`（`EvolutionConfig` 就在这个文件里，没有独立 `config.py`）。
>
> **2. `contracts/` 不在 spec 目录下。** 清单 T019 与 `tasks.md` 的语境让人以为契约在
> `specs/011-dream-cycle-self-evolution/contracts/`；实际在**仓库根** `contracts/self-evolution.md`
> （与 007/009/010 的契约同处一个 repo 级 `contracts/` 目录）。测试
> `tests/services/test_dream_audit_config.py:89 test_quickstart_and_contract_exist` 断言的也正是
> 这个根级路径（`repo_root / "contracts" / "self-evolution.md"`）。
>
> **3. `requirements.md` 在 `checklists/` 下，不在 spec 根。** 路径是
> `specs/011-dream-cycle-self-evolution/checklists/requirements.md`（16/16 已勾）。
>
> **4. 011 没有任何生产接线。** 全仓 `app/`（排除这两层自身与测试）对
> `self_evolution` / `dream_cycle` 的引用数为 **0** —— 没有 router、没有 endpoint、没有
> `scheduled_tasks` 注册、`main.py` 不 import。两层目前**只能从测试触达**，是库而非在线功能。
> 这不是本次核对发现的缺陷，但它决定了下面很多项的判级（**代码与测试齐备 ≠ 生产在跑**）。
>
> **5. 术语不一致（需产品/规格拍板，非实现缺陷）。** 清单 T017 要求的事件名是
> `friction_captured` / `draft_generated` / `mr_created` / `skill_deprecated` / `skill_restored`；
> 实现用的是 `capture` / `generate` / `mr` / `deprecate` / `restore`
> （`evolution_audit.py:20 AUDIT_EVENT_TYPES`，契约文档同步为该值）。两套命名并存会误导审计查询。
> 同理清单 T003 的「失败后成功」在集成层文献里叫 `retry`，核心层叫 `failed_then_succeeded`。
>
> **勾选口径**：下表 `[x]` = 「实现 + 测试双证已核对」；`[!]` = **有实现但证据不足或与清单描述不符**；
> `[-]` = **清单条目不成立**（模块/命名/路径不存在，或该项本就不是 011 的职责）。
> **`[!]` 与 `[-]` 都是待办**，不是「已通过」。逐项判级见下。

---

## Phase 1: Module Structure & Data Model

- [x] T001 创建 `services/chat-api/app/self_evolution/__init__.py` + 子模块骨架
      （`__init__.py:1-65` 导出 22 个公开名；骨架 = `fragment`/`friction`/`similarity`/`scanner`/`draft_gen`）
- [x] T002 实现经验片段数据模型
      （`fragment.py:27-55 ExperienceFragment`：`scene`/`actions`/`result`/`friction_kind`/`created_at`/`source_session`/`feedback`/`tenant_id`/`fragment_id`）
- [!] T002-1 验证经验片段存储集合初始化（集合/表/索引）
      —— **集合与索引不存在**。核心层 `FragmentStore`（`fragment.py:58-88`）是纯内存 list；
      集成层 `FrictionStore`（`services/dream_cycle/friction.py:104-114`）同样是内存 list，其 docstring 自承
      「the Mongo-backed implementation plugs in here」。**无 `main_id` 分区、无索引、无 TTL**。
      对「库能力交付」而言可接受，但清单把「集合/表/索引」列为验收项，故不能勾。
- [x] T002-2 验证字段完整性
      （`fragment.py:44-55 as_document()`；测试 `test_fragment_as_document_includes_source_session_and_feedback`）
      —— **注意字段名映射**：清单写 `scene_features`/`action_sequence`/`timestamp`/`session_id`/`user_feedback`，
      实现是 `scene`/`actions`/`created_at`/`source_session`/`feedback`。语义一一对应，命名不同。

## Phase 2: Friction Detection

- [x] T003 实现 `friction.py`：失败后成功（重试≥1）自动捕获
      （`friction.py:95-105`；`retries = max(0, int(attempts) - 1) if succeeded else 0`）
- [x] T003-1 「工具调用失败→重试成功」→ friction 触发
      （`test_failed_then_succeeded_after_retry_is_captured`：`attempts=3, succeeded=True` → `retries == 2`；
      `test_success_without_retry_is_not_friction`：`attempts=1` → `None`）
- [x] T003-2 「人工纠正/驳回」→ friction 触发
      （`test_human_correction_is_captured`；`friction.py:83-93`，`HUMAN_CORRECTION` 在 `AUTO_CAPTURED` 内）
- [x] T003-3 「用户显式标记不顺」需主动触发，默认不捕获
      （`test_explicit_mark_requires_user_action`：不传 `explicit_mark` 时为 `None`；
      `friction.py:29-30 AUTO_CAPTURED` 明确排除 `EXPLICIT_MARK`；`test_auto_captured_set_matches_clarify` 钉住集合）
- [-] T003-4 摩擦事件日志记录（审计字段 `event_type`、`session_id`、`tool_name`、`retry_count`）
      —— **该四字段组合不存在**。`FrictionSignal`（`friction.py:33-48`）字段是
      `kind`/`scene`/`actions`/`result`/`retries`/`feedback`/`source_session`/`tenant_id`；
      审计走 `record_evolution_event(event_type="capture", actor, payload)`，无 `tool_name`/`retry_count` 顶层字段。
      「工具 + 重试次数」这一组合在**集成层**的 `FrictionFragment`（`retry`/`fallback`/`timeout` 三类 +
      `tool`/`stage`/`prompt_preview`/`outcome`）里，但那不是「摩擦事件日志」的审计落点。
      需先明确：审计字段是本节这套，还是 T017 那套。

## Phase 3: Similarity Algorithm

- [x] T004 实现 `similarity.py`：Jaccard（场景特征）
      （`similarity.py:20-33`；token 归一化 trim + lower）
- [x] T004-1 Jaccard ≥ 0.7 判「高相似」
      （`similarity.py:76-84 is_high_confidence`，`DEFAULT_JACCARD_THRESHOLD = 0.7`；`test_is_high_confidence_thresholds`）
- [x] T004-2 Jaccard < 0.7 判「低相似」
      （`test_is_high_confidence_thresholds` 负例；`scanner.py:81-83 ScanResult.draft_only`）
- [x] T004-3 实现编辑距离（动作序列）
      （`similarity.py:36-58 edit_distance`，标准 Levenshtein DP；`test_edit_distance_substitution`、`test_edit_distance_insertion_deletion`）
- [!] T004-4 双指标**联动**：Jaccard + 编辑距离共同判定模式重复
      —— **两者都实现了，但没有一处「共同判定」**。`edit_distance` 只被
      `similarity.py:61-68 normalized_edit_similarity` 消费，而 `normalized_edit_similarity`
      **全仓无人调用**（`scanner.py` 只用 Jaccard，见 `:98-113`）。即编辑距离目前是**死代码**。
      清单要求的是联合判定，实现是「编辑距离已备好但未接入」。需拍板：接入判定，或明确降为辅助指标并记录。
- [x] T004-5 非向量库实现（集合/序列特征，无外部依赖）
      （`similarity.py:1-9` docstring 自述 "Two metrics, no vector store"；`__init__.py:10-11` 自述
      「dependency-light core ... unit-testable without the DSH runtime or a database」）

## Phase 4: Pattern Scanner (US2)

- [!] T007 实现 `scanner.py`：周期扫描（**复用 `scheduled_tasks`**）
      —— 发现逻辑齐备（`scanner.py:86-118 scan_fragments`），但**「复用 `scheduled_tasks`」不成立**：
      `scheduled_tasks` 在 `app/api/endpoints/scheduled_tasks.py`、`app/scheduled_tasks/`、`app/main.py:121/136/163`
      出现，而 `scanner.py` **只在自己的 docstring 里提到它**（`:5-6`），无任何 import 或注册。
      周期触发（`ScanConfig.frequency`）是**配置字段**，没有人按它调度。
- [x] T007-1 调度周期可配置（once/daily/weekly）
      （`scanner.py:26 SCHEDULE_FREQUENCIES = ("once", "daily", "weekly")`、`:66-68 __post_init__` 抛 `ValueError`；
      `test_scan_config_rejects_bad_frequency`。**注意**：可配置 ≠ 被调度，见 T007）
- [x] T007-2 扫描发现重复模式 → 生成 Skill 草稿
      （`scan_fragments` → `generate_draft`；`test_scan_clusters_and_marks_high_confidence` +
      `test_generate_draft_is_never_published_directly`）
- [x] T007-3 无重复模式 → 不生成草稿
      （`test_scan_below_min_samples_is_draft_only`；`scanner.py:130-131 draft_only`；
      `test_generate_draft_from_empty_cluster_returns_none`：空簇 `representative is None` → `None`）
- [!] T007-4 扫描日志记录（`scan_id`、`pattern_count`、`draft_count`）
      —— `scanner.py:162-172 scan_summary` 返回 `frequency`/`clusterCount`/`mrEligibleCount`/
      `draftOnlyCount`/`jaccardThreshold`/`minSamples`。**无 `scan_id`、无 `draft_count`**，
      且 `scan_summary` 只被 `test_scan_summary_shape` 调用，**未接入审计**（T017 没有 scan 事件）。

## Phase 5: Draft Generation (US2)

- [x] T008 实现 `draft_gen.py`：Skill 草稿生成
      （`draft_gen.py:109-146 generate_draft`）
- [x] T008-1 草稿进入 004 草稿态（非直接发布）
      （`draft_gen.py:19 DRAFT_STATUS = "draft"`、`:60-63 is_draft`；`test_generate_draft_is_never_published_directly`）
- [x] T008-2 草稿元数据：触发条件/步骤/预期效果
      （`draft_gen.py:40-78 SkillDraft`：`scene`=触发条件、`actions`=步骤、`description`=预期效果；
      `:65-78 as_dict()` 用 camelCase 输出）
- [x] T008-3 质量门槛：含可执行测试样例 + 预览运行通过
      （`draft_gen.py:98-106 quality_gate` 查 `test_samples`；`:141-145 preview_runner` 不通过则 `None`；
      `test_generate_draft_requires_test_samples`、`test_generate_draft_preview_pass_marks_flag`）
- [x] T008-4 预览失败 → 不生成草稿（避免污染市场）
      （`draft_gen.py:143-145`；`test_generate_draft_rejected_when_preview_fails`）

## Phase 6: Draft Lifecycle Management

- [x] T009 实现草稿堆积上限（每租户最近 N 份，默认 100）
      （`scanner.py:30 DEFAULT_DRAFT_BACKLOG_LIMIT = 100`；`:121-136 should_generate_draft`）
- [!] T009-1 超限清理**最旧**草稿
      —— **没有清理逻辑**。`should_generate_draft` 在 `existing_drafts >= limit` 时返回 `False`，
      也就是**抑制新建**，不是删最旧的。清单要的是 LRU 淘汰。功能上避免无限增长，
      但语义不同（"拒新的" vs "删旧的"），且 `existing_drafts` 是**调用方传入的整数**，无人统计。
- [x] T009-2 同片段 Jaccard 去重（保留最高置信草稿）
      （`scanner.py:139-159 dedupe_drafts`，按 `(similarity, sample_count)` 降序、命中即丢；
      `test_dedupe_drafts_keeps_highest_confidence`：low(0.5) + high(0.95) → 只留 high）
- [!] T009-3 草稿计数统计（当前草稿数/上限）
      —— `ScanConfig.draft_backlog_limit` 可读，`scan_summary` 有 `draftOnlyCount`，
      但**没有「当前草稿数」的持久统计**（`existing_drafts` 由调用方自备，见 T009-1）。
      且**按租户（per tenant）不成立**：`should_generate_draft` 与 `ScanConfig` 都没有租户维度。

## Phase 7: Automatic MR Generation (US3)

- [x] T011 实现 `services/dream_cycle/mr.py`：高置信自动建 MR
      （`mr.py:107-120 generate_improvement_mr`；注意路径不是 `app/self_evolution/mr.py`）
- [x] T011-1 置信阈值：Jaccard ≥ 0.7 且样本数 ≥ 5
      （`mr.py:15-16`、`:30-32 is_high_confidence`；`test_high_confidence_generates_mr`）
- [x] T011-2 MR 目标：当前租户 Skill 草稿目录（004 草稿态）
      （`mr.py:18 DRAFT_DIR = "specs/004-skillhub-lifecycle/drafts"`、`:51 target_dir`。
      **注意**：常量是**仓库路径**而非租户目录，"当前租户"维度不体现在这里）
- [x] T011-3 MR 内容：Skill 定义 + 测试 + 说明
      （`mr.py:57-65 as_document()` 输出 `key`/`label`/`jaccard`/`samples`/`target_dir`/`requires_human_review`。
      **注意**：这是**候选元数据**，不是 Skill 定义 + 测试 + 说明的实体内容 —— 后者在
      `draft_gen.py:65-78 as_dict()`。两者尚未串联）
- [x] T011-4 低置信（Jaccard < 0.7 或样本 < 5）→ 仅留草稿，不建 MR
      （`mr.py:112-114` 返回 `None`；`mr.py:102-103` 走 `Draft`；`test_low_confidence_draft_only`、`test_t013_us3_high_vs_low`）
- [x] T011-5 MR 不可自动合入（必须人工审阅）
      （`mr.py:64 "requires_human_review": True`；`:7` docstring「awaiting human review before publish」）

## Phase 8: Draft vs MR Boundary

- [x] T012 验证草稿与 MR 关系
      草稿 = 全部模式中间态（高/低置信都生成）→ `mr.py:102` 高置信也 append 一个 `status="draft->mr"` 的 Draft；
      MR = 仅高置信在草稿基础上生成 → `mr.py:93-101`；二者非同一物 → 不同 dataclass（`Draft` vs `ImprovementMR`）。
      测试 `test_draft_vs_mr_boundary`。

## Phase 9: Low Adoption Deprecation (US4)

- [x] T014 实现 `services/dream_cycle/deprecation.py`：低采纳检测
      （`deprecation.py:40-49 detect_low_adoption`；路径不是 `app/self_evolution/deprecation.py`）
- [x] T014-1 淘汰阈值：14 天曝光 ≥ 20 次且采纳率 < 10%
      （`deprecation.py:16-18`；`:45-49` 三个条件；`test_low_adoption_detection`）
- [x] T014-2 采纳率计算：被复用次数 / 推荐曝光次数
      （`deprecation.py:33-37 adoption_rate`，`adopted / exposure`，`exposure <= 0` → `None`（不算低采纳））
- [!] T014-3 标记 deprecated 后不再推荐
      —— **未实现**。`mark_deprecated`（`:52-69`）只产出一条记录 + 置位；
      `AdoptionStore.restore`（`:107-120`）的返回值里有 `"recommendation": "re-enabled"`，
      但**没有任何推荐路径读取这个位**（无推荐模块、无消费方）。`is_deprecated` 只是数据。
- [x] T014-4 共用 016 `skill_status.marked_low_quality` 标记位（避免双写）
      （`deprecation.py:20 LOW_QUALITY_FLAG = "marked_low_quality"`；`:61`、`:104`、`:118` 三处同一常量；
      `test_deprecation_flow_marks_and_shares_flag`）

## Phase 10: Deprecation Recovery

- [x] T015 实现淘汰恢复逻辑
      （`deprecation.py:107-120 AdoptionStore.restore`）
- [x] T015-1 人工恢复 → 重置采纳计数
      （`deprecation.py:109-112` 把 `exposure`/`adopted` 归零；`test_manual_restore_resets_and_reenables`）
- [!] T015-2 恢复后重新进入推荐
      —— 与 T014-3 同一问题：`restore` 返回 `"recommendation": "re-enabled"` 这个**字符串**，
      但没有推荐路径存在，该断言无法被任何行为证伪。
- [-] T015-3 恢复审计记录
      —— 审计事件类型里有 `restore`（`evolution_audit.py:20`、`:94-95 audit_restore`，`test_full_chain_events` 覆盖），
      但**没有任何代码在 `AdoptionStore.restore` 时调用它** —— `audit_restore` 只被测试调用。
      即「恢复」与「审计」是两段未连接的实现，故该项按「未接线」记为不成立。

## Phase 11: Cross-Feature Integration

### 与 004 (skillhub-lifecycle)
- [x] XF004-1 验证草稿进入 004 草稿态
      （`DRAFT_STATUS = "draft"`；`mr.py:18 target_dir` 指向 `specs/004-skillhub-lifecycle/drafts`）
- [!] XF004-2 验证 004 可反向声明「011 草稿是其上游来源」
      —— 011 侧有 `SkillDraft.source_fragment_ids`（`draft_gen.py:51`）与 `generated_by = "dream_cycle"`
      （`:54`），但 **004 侧无任何反向声明**（全仓无消费方）。单向标记，非双向可追溯。
- [-] XF004-3 验证 Skill 生命周期流转：草稿 → 审阅 → 发布（011 不越过审阅）
      —— 011 侧只到「生成草稿」为止（`DRAFT_STATUS` + `requires_human_review`），
      **审阅/发布流转属于 004 的职责**，011 侧无该流程可验。作为 011 的条目不成立。

### 与 002 (session-versioning)
- [!] XF002-1 验证经验沉淀源来自会话 commit/share
      —— `FrictionSignal.source_session`（`friction.py:43`）与 `ExperienceFragment.source_session`
      （`fragment.py:36`）字段存在，但没有**任何**从 002 的 commit/share 事件读取并喂入的代码。
      字段齐备、来源未接。
- [!] XF002-2 验证 `session_id` 可追溯至 002 会话快照
      —— 同上：字段在，追溯的**查询/关联逻辑不在**（无 join、无快照读取）。
- [!] XF002-3 验证数据流对齐：会话 → 摩擦事件 → 经验片段
      —— 「摩擦事件 → 经验片段」在核心层可验（`FrictionSignal` → `ExperienceFragment`，
      但**也没有函数做这个转换**：`detect_friction` 返回 `FrictionSignal`，无人转成 `ExperienceFragment`）；
      「会话 → 摩擦事件」这一段完全未接。三段里只有一段成立。

### 与 010 (dag-orchestration)
- [!] XF010-1 验证扫描 job 复用 `scheduled_tasks` —— 同 T007：无 import、无注册。
- [x] XF010-2 验证不依赖 010 DAG 引擎（纯调度任务即可）
      （`self_evolution/__init__.py:10-11` 明确「dependency-light core ... without the DSH runtime or a database」；
      全仓无 DAG 引擎 import）
- [x] XF010-3 验证 once/daily/weekly 调度支持 —— 同 T007-1（**配置**层面支持，非实际调度）

### 与 016 (skill-market-hardening)
- [x] XF016-1 验证共用 `skill_status.marked_low_quality` 标记位 —— 同 T014-4
- [!] XF016-2 验证 011 从「低采纳沉淀侧」标记，016 从「市场运营侧」标记
      —— 011 侧标记在（`deprecation.py`），**016 侧无对应标记代码**（全仓 `marked_low_quality`
      仅 4 处，全在 `deprecation.py`）。
- [!] XF016-3 验证避免双写（同一标记位）
      —— 「同一常量」成立（`LOW_QUALITY_FLAG` 单一来源），但**两侧消费方只有一侧存在**，
      「避免双写」目前是空条件的成立。

## Phase 12: Audit & Observability

- [!] T017 实现自进化全链路审计
      —— 机制齐备（`evolution_audit.py:52-75 record_evolution_event` + `:78-95` 五个 `audit_*` 包装），
      但**五个包装全部只被测试调用，无生产者接线**（见「结论摘要 4」）。
      且「全链路」不成立：扫描（T007-4）与恢复（T015-3）都不产生事件。
- [!] T017-1 摩擦捕获事件记录（`event_type=friction_captured`）
      —— 事件名实为 **`capture`**（`evolution_audit.py:20`），非清单写的 `friction_captured`。
      `audit_capture` 存在（`:78-79`）、`test_capture_audit_event` 覆盖，但无生产者调用。
- [!] T017-2 草稿生成事件记录（`event_type=draft_generated`）
      —— 事件名实为 **`generate`**（`:82-83 audit_generate`），非 `draft_generated`；无生产者调用。
- [!] T017-3 MR 创建事件记录（`event_type=mr_created`）
      —— 事件名实为 **`mr`**（`:86-87 audit_mr`），非 `mr_created`；无生产者调用。
- [!] T017-4 淘汰标记事件记录（`event_type=skill_deprecated`）
      —— 事件名实为 **`deprecate`**（`:90-91 audit_deprecate`），非 `skill_deprecated`；无生产者调用。
- [!] T017-5 恢复事件记录（`event_type=skill_restored`）
      —— 事件名实为 **`restore`**（`:94-95 audit_restore`），非 `skill_restored`；无生产者调用。
- [-] T017-6 验证审计事件经 001 `system_audit` 落点
      —— 实现接受**注入式 `audit_sink`**（`:18 AuditSink = Callable[..., Any]`），
      **没有**任何指向 001 `system_audit` 的接线；测试用的是 `collecting_sink`。
      对库设计而言注入是优点，但清单要求的是「经 001 落点」，未做到。

## Phase 13: Config Management

- [!] T018 实现阈值/周期可配置
      —— `EvolutionConfig`（`evolution_audit.py:27-49`）齐备且**集中**，但它是**独立于核心层的第二份常量**：
      核心层另有 `similarity.DEFAULT_JACCARD_THRESHOLD`/`DEFAULT_MIN_SAMPLES`、
      `scanner.DEFAULT_SCAN_FREQUENCY`/`DEFAULT_DRAFT_BACKLOG_LIMIT`、
      `deprecation.LOW_ADOPTION_*`、`mr.DEFAULT_JACCARD_THRESHOLD`/`DEFAULT_MIN_SAMPLES`。
      **两套数值目前一致，但需要手工同步**（`mr.py:15-16` 与 `deprecation.py:16-18` 各写了一遍）。
      这是真实的漂移风险，非缺陷但需记录。
- [x] T018-1 扫描周期配置（`scan_interval_hours`）（`evolution_audit.py:30`；`test_scan_period_configurable`）
- [x] T018-2 置信阈值配置（`jaccard_threshold=0.7`, `min_samples=5`）（`:31-32`、`:38-39 confidence_gate`；`test_confidence_gate_configurable`）
- [x] T018-3 淘汰阈值配置（`low_adoption_window_days=14`, `min_exposure=20`, `rate=0.10`）（`:33-35`、`:41-49`；`test_low_adoption_gate_configurable`）
- [-] T018-4 验证草稿堆积上限配置（`max_drafts_per_tenant=100`）
      —— 上限在**核心层** `scanner.DEFAULT_DRAFT_BACKLOG_LIMIT = 100`，**不在 `EvolutionConfig` 里**；
      且清单的 `max_drafts_per_tenant` 这个名字全仓不存在，`per_tenant` 维度也不存在（见 T009-3）。
- [!] T018-5 验证 `shadow_ratio` 配置（影子流量比例）
      —— `EvolutionConfig.shadow_ratio = 0.1`（`:36`）与 `runner.DEFAULT_SHRADOW_RATIO = 0.1`
      （`runner.py:20`，**注意这个常量的拼写错误 `SHRADOW`**）是两份。runner 接受注入的
      `shadow_ratio` 参数（`:139`）并 clamp 到 `[0,1]`（`:112`），但**不读 `EvolutionConfig`**。
      两处都在、未打通。

## Phase 14: Documentation

- [x] T019 写 `quickstart.md` + `contracts/self-evolution.md`
      （`specs/011-dream-cycle-self-evolution/quickstart.md`；契约在**仓库根** `contracts/self-evolution.md`，61 行。
      由 `test_quickstart_and_contract_exist` 断言存在 + 含 5 个关键词）
- [x] T019-1 验证经验片段 schema 文档完整
      （`contracts/self-evolution.md:6-20` 表格列全 7 字段 + 截断 120 说明 + 提取函数签名）
- [x] T019-2 验证 MR 契约文档完整
      （`contracts/self-evolution.md:30-35`：`as_document()` 输出、`None` 语义、`requires_human_review` 恒 True）
- [x] T019-3 验证 API/模块使用示例
      （`quickstart.md` 5 个小节均有可运行代码：dream cycle / friction / MR / deprecation / config）

## Phase 15: Testing

### Unit Tests
- [x] T006 US1 测试：三类 friction 捕获 + 片段字段完整性
      （`test_self_evolution.py:28-76` 七个用例；字段完整性 `test_fragment_as_document_includes_source_session_and_feedback`）
- [x] T010 US2 测试：模式→草稿 + 非直接发布 + 生成门槛
      （`:166-286` 十一个用例，含 `test_generate_draft_*` 四例）
- [x] T013 US3 测试：高置信建 MR + 低置信仅草稿
      （`test_dream_evolution.py:71-113`：`test_high_confidence_generates_mr`、
      `test_low_confidence_draft_only`、`test_draft_vs_mr_boundary`、`test_t013_us3_high_vs_low`）
- [x] T016 US4 测试：低采纳标记 + 人工恢复
      （`:115-177` 五个用例，含 `test_t016_us4_low_adoption_and_restore`）

### Integration Tests
- [!] IT001 端到端：摩擦事件 → 经验沉淀 → 模式扫描 → 草稿生成
      —— **四段里只有后两段被串起来**（`scan_fragments` → `generate_draft`）。
      `detect_friction`（核心层 `FrictionSignal`）→ `ExperienceFragment` 的转换函数**不存在**；
      `FrictionSignal` 与 `ExperienceFragment` 是两个不互通的 dataclass。
      现有测试是同文件内的单元测试，非跨模块 e2e。
- [!] IT002 端到端：高置信模式 → MR 创建 → 人工审阅 → Skill 发布
      —— 「高置信 → MR」有（`test_high_confidence_generates_mr`）；「人工审阅 → 发布」属 004，
      011 侧无实现（同 XF004-3）。跨模块 e2e 不存在。
- [!] IT003 端到端：低采纳 Skill → 标记淘汰 → 恢复流程
      —— 三段都在同一文件内被串起（`test_t016_us4_low_adoption_and_restore`），
      但这仍是单模块单元测试；且「不再推荐」无消费方（见 T014-3）。

### Edge Case Tests
- [x] ET001 无摩擦事件场景（空经验库）
      （`test_generate_draft_from_empty_cluster_returns_none`；`scan_fragments([])` 返回空 `ScanResult`）
- [x] ET002 单条经验无重复模式
      （`test_scan_below_min_samples_is_draft_only`：单元素簇 `similarity = 1.0` 但 `sample_count = 1 < 5` → draft_only）
- [!] ET003 草稿堆积超限清理
      —— `test_should_generate_draft_respects_backlog_limit` 测的是**拒绝新建**，不是「清理」（见 T009-1）。
      按清单语义（清理）无测试且无实现。
- [x] ET004 同片段多草稿去重
      （`test_dedupe_drafts_keeps_highest_confidence`）
- [!] ET005 跨租户数据隔离验证
      —— **只有核心层内存 store 的过滤测试**（`test_fragment_store_scopes_by_tenant`，`fragment.py:76-79`）。
      无 DB/集合层隔离验证（无集合，见 T002-1）；`AdoptionStore.counters`（`deprecation.py:76`）
      是**全局 dict，按 `skill_key` 而非租户分区** —— 跨租户存在串号风险。
- [!] ET006 阈值边界值测试（Jaccard=0.7, samples=5, exposure=20, rate=10%）
      —— 只有 Jaccard/samples 的边界（`test_is_high_confidence_thresholds`）。
      **淘汰侧边界缺失**：`deprecation.py:43-49` 用 `<` 与 `>=`，critical 的
      `exposure == 20` / `rate == 0.10` / `window == 14` 三个恰好在边界上的取值**无测试**。

## Phase 16: Security & Compliance

- [!] SEC001 验证数据隔离：经验片段按租户隔离，不跨租户共享
      —— 同 ET005。核心层内存过滤有测试；`tenant_id` 默认值 **`"default"`**
      （`fragment.py:38`、`friction.py:44/62`）在缺省时会把不同租户的数据混进同一分区。
- [-] SEC002 验证审计日志完整性（不可篡改）
      —— 011 只产出事件 dict 交给注入的 sink（`evolution_audit.py:69-75`），
      **不存储、不签名、不防篡改**；防篡改属 001 的职责。作为 011 条目不成立。
- [x] SEC003 验证配置文件安全（密钥/凭据不提交）
      （`EvolutionConfig` 全为数值阈值，无凭据；仓库级 `scripts/check_open_source_hygiene.py` 守此约束且现为 exit 0）
- [!] SEC004 验证 MR 创建权限（仅授权 Agent 可自动建 MR）
      —— `mr.py` 的 `generate_improvement_mr` 是**纯函数**，无调用方身份、无权限校验、
      无 RBAC 检查；`build_candidate` 也不校验来源。权限层不存在。

## Success Criteria Verification

- [!] SC001 摩擦事件 100% 可捕获经验片段
      —— `detect_friction` 覆盖三类且测试充分，但「摩擦事件 → 经验片段」的转换**不存在**（见 IT001）；
      按字面「可捕获」成立，「转为片段」不成立。
- [!] SC002 重复模式 100% 生成草稿（非直接发布）
      —— `should_generate_draft` 在**达到堆积上限后返回 False**（`scanner.py:134-135`），
      所以「100%」不成立（有意如此，上限即目的）。且按租户维度不存在（T009-3）。
- [x] SC003 低置信 0 次自动建 MR（仅高置信）
      （`mr.py:112-114` 非高置信返回 `None`；`test_low_confidence_draft_only`、`test_t013_us3_high_vs_low`）
- [!] SC004 低采纳 Skill 100% 可标记淘汰
      —— 检测 + 标记齐备且测试充分，但「标记后不再推荐」（T014-3）无实现，
      标记的实际效果为零。
- [!] SC005 自进化全链路 100% 进审计
      —— 五个事件包装存在，但**无生产者接线**（T017）、扫描与恢复不产生事件（T007-4/T015-3）。
      「全链路」与「100%」都不成立。

---

## 核对方法与结论

**取证方式**（全部可复现）：
- 读实现全文：`app/self_evolution/` 6 文件 704 行、`app/services/dream_cycle/` 5 文件 652 行。
- 跑测试：`services/chat-api/venv/bin/python -m pytest tests/self_evolution/ tests/services/test_dream_cycle.py tests/services/test_dream_evolution.py tests/services/test_dream_audit_config.py -q` → **66 passed**。
- 引用计数：`grep -rn "from app.self_evolution\|from app.services.dream_cycle" services/chat-api/app/ --include=*.py`（排除两层自身）→ **0 命中**。
- 关键符号存在性：`scheduled_tasks` 注册、`marked_low_quality` 消费方、`recommendation` 消费方、`normalized_edit_similarity` 调用方、`scan_id`/`draft_count`、`max_drafts_per_tenant`。

**判级统计**（`grep -c` 实测，六项 `[-]` 为 `T003-4`/`T015-3`/`XF004-3`/`T017-6`/`T018-4`/`SEC002`）：
`[x]` **55** 项 · `[!]` **35** 项 · `[-]` **6** 项（共 96 项）。

**七类待办**（按影响排序）：
1. **010/011 无生产接线**（T007、XF010-1、T017 全系列、T017-6）：`scanner` 从不被调度，五个 `audit_*` 从不被调用。这是「已实现但不在线」，需接线或明确降级为库。
2. **`normalized_edit_similarity` 是死代码**（T004-4）：编辑距离实现了但从未接入判定。需拍板接入或记录为辅助指标。
3. **审计事件命名两套并存**（T017-1…5）：清单 `friction_captured`/`draft_generated`/… vs 实现 `capture`/`generate`/…。契约文档已按实现写；**应以实现为准改清单**，否则审计查询会写错。
4. **标记/恢复无消费方**（T014-3、T015-2、SC004）：「不再推荐」「重新进入推荐」没有推荐路径可验，这两项目前不可证伪。
5. **「清理最旧」被实现成「拒绝新建」**（T009-1、ET003）：语义差异，若产品要的是 LRU 淘汰则需实现。
6. **配置有两份**（T018、T018-5）：`EvolutionConfig` 与核心层常量需手工同步；`runner.SHRADOW` 拼写错误应一并修。
7. **跨租户隔离只有内存层**（T002-1、ET005、SEC001、T009-3、T018-4）：无集合、无索引、`tenant_id` 默认 `"default"`、`AdoptionStore` 不按租户分区、per-tenant 上限不存在。

**清单本身的治理问题**（写回 spec 供后续修订）：
- 模块清单与实际布局不符（本文件顶部「结论摘要 1」），`tasks.md` 里同样是扁平假设。
- `contracts/` 的实际位置（仓库根）应写进 `tasks.md`/`plan.md`，避免下一个人再找不到。
- `checklists/requirements.md`（16/16）与 `tasks.md`（19/19）此前已勾选，与本清单的 `[!]`/`[-]` 不矛盾：
  前两者勾的是**需求质量与任务存在性**，本清单勾的是**实施细节的可证伪证据**。

**Checklist Gate**: 96 项中 55 项已核对通过；**41 项（`[!]` 35 + `[-]` 6）仍需处置**，
不得据此进入 `/speckit-converge`。处置方式有两类：修实现（或接线），或修订清单使其与已交付的
库能力一致 —— 两者都需先由产品/规格对上面「七类待办」拍板，尤其是第 1、3 项。
**Review Ownership**: 已由实现人逐项取证（2026-10-02）；评审人抽检建议优先看 `[!]` 项。
**Marker Semantics**: `[x]` = 功能已实现且测试通过；`[!]` = 有实现但证据不足/与描述不符；
`[-]` = 条目本身不成立（模块、命名、路径不存在，或非 011 职责）。
