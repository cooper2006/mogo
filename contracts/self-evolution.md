# Self-Evolution Contract (011)

> 011-dream-cycle-self-evolution — 经验片段 schema + MR 契约。
> 本文件定义 chat-api `app/services/dream_cycle/` 的对外接口与不变量。

## 经验片段 schema（FrictionFragment / T005-T006）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `key` | str | 片段唯一键（非空） |
| `category` | str | `retry` / `fallback` / `timeout`（三类，US1） |
| `tool` | str | 来源工具（非空） |
| `stage` | str | 调用阶段 |
| `prompt_preview` | str | 提示预览，截断至 120 字符（紧凑，不留大 payload / 密文） |
| `outcome` | str | 结果说明 |
| `created_at` | datetime | UTC 时间戳 |

- 提取：`extract_friction_from_signals(signals, store)` — 每条匹配信号产出一个片段，
  有 `store` 时落经验存储。
- 完整性自检（US1 T006）：`as_document()` 必须含上表全部字段。

## 候选信号与置信门（T002 / T011-T012 / OQ-1）

- `rank_candidates(signals, top_n)` — 按 score 降序取 Top-N（默认 10）。
- 高置信 = **Jaccard ≥ 0.7 且 samples ≥ 5**（`EvolutionConfig.confidence_gate` 可调，T018）。
- **模式发现的二级判定（T004-4）**：场景 Jaccard 是集合指标（共享词汇但做完全不同的事仍得 1.0），
  故聚类时叠加**动作序列的编辑相似度**作为次级门槛 —— `cluster_by_similarity(..., action_getter=,
  action_threshold=)`，默认 `DEFAULT_ACTION_SIMILARITY_THRESHOLD = 0.5`；
  `ScanConfig.action_similarity_threshold = None` 可关闭该门槛（退回纯 Jaccard）。
- 草稿 vs MR 边界（T012）：草稿 = 全部模式中间态；高置信在草稿基础上生成
  `ImprovementMR`（目标 004 草稿目录 `specs/004-skillhub-lifecycle/drafts`，
  人工审阅后发布），低置信仅草稿。

## MR 契约（ImprovementMR / T011 / US3）

`ImprovementMR.as_document()` 输出：
`{key, label: "improvement-mr", jaccard, samples, target_dir, requires_human_review: true}`
- `generate_improvement_mr(candidate)` 非高置信时返回 `None`。
- 每个 MR 必须人工审阅后才能发布（`requires_human_review` 恒为 True）。

## 淘汰与恢复（Deprecation / T014-T015 / US4）

- 低采纳判定（`detect_low_adoption` / `EvolutionConfig.is_low_adoption`）：
  窗口 ≤ 14 天 且 曝光 ≥ 20 且 采纳率 < 10%。
- 标记：`marked_low_quality` 位与 016 硬加固共用；淘汰在租户内生效。
- 人工恢复（`AdoptionStore.restore`）：重置采纳计数 + 重新启用推荐。

## Dream 管道（Runner / T001-T008）

`run_dream_cycle(signals, validator, journal, dry_run, shadow_ratio, top_n, cycle_id)`
-> `DreamResult`
- 流程：rank → validate → apply（dry-run 或 shadow）→ report。
- dry-run：只记录计划（journal op=`dry_run`），不落任何真实变更。
- shadow：按 `shadow_ratio`（默认 0.1，clamped 到 [0,1]）路由流量。

## 周期触发（Runtime / T007）

- 触发不在核心层，而在 `app/services/dream_cycle/runtime.py`：`DreamCycleScanner`
  （`app/main.py` lifespan 里 `start()` / `stop()`）按 `EvolutionConfig.scan_interval_hours`
  （默认 24h）跑 `run_once`。
- **不复用 `scheduled_tasks`**：那是面向用户的聊天任务模型（要求 `prompt` 与 `session_id`），
  011 的扫描没有这两者。
- `run_once` 从 `kernel_event_projections` 的 `item.failed` / `item.completed` 行派生摩擦信号
  （`signals_from_rows` → `fragments_from_signals`，即 `FrictionSignal` → `ExperienceFragment`），
  再按租户扫描。它**不修改** DSH turn 热路径。

## 审计与可配置（T017-T018）

- `EvolutionConfig`：扫描周期 / 置信阈值 / 淘汰阈值 / shadow 比例集中可配；
  `jaccard_threshold` / `min_samples` / `action_similarity_threshold` 直接引用
  `app.self_evolution.similarity` 的常量（单一来源，防漂移）。
- `record_evolution_event(sink, event_type, actor, payload)`：
  `event_type` ∈ `capture / generate / mr / deprecate / restore`，
  委托 001 审计落点，全链路可审计。
- 默认落点：`runtime._default_audit_sink` → `feature_audit_bridge.emit_feature_event("011", ...)`
  → **`position_role_audit_logs`**（chat-api 侧的 001 审计流；`system_audit_logs` 是 admin-api 侧的集合）。

## 错误

- `ValueError` 子类：未知 friction 类别 / 未知审计事件类型 / 空片段 key。
