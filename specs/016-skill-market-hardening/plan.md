# Implementation Plan: Skill Full-Lifecycle Marketplace Hardening

**Branch**: `016-skill-market-hardening` | **Date**: 2026-07-08 | **Spec**: [spec.md](./spec.md)

**Input**: 缺口新特性（P2 规模化生态，后置）。在特性 004（Skill 生命周期基础）之上做市场侧强化：调用监控、效果打分、版本灰度/回滚、低质量自动标记。沉淀闭环（会话→经验→Skill 草稿）由 011 承载，本特性专注市场强化。

## Summary

新增 `services/admin-api/app/services/skill_market/` 子模块：Skill 调用监控聚合（复用既有审计/事件通道 + token_usage）、效果打分模型、灰度调度器、低质量自动标记。与 004 `skill_lifecycle` 共用版本模型，016 是"市场侧"叠加层，不改变 004 草稿/发布契约。

## Technical Context

**Language/Version**: Python 3.13（admin-api/chat-api 既有栈）

**Primary Dependencies**: 既有 `admin-api/services/skill_lifecycle.py`（版本/发布模型）+ 既有审计通道 + `chat-api/token_usage`（调用指标）；新增灰度调度（`scheduled_tasks` 复用）

**Storage**: 新增 `skill_metrics`（调用/效果指标）+ `skill_rollouts`（灰度/回滚记录）+ 复用 004 `organization_skill_releases`

**Testing**: pytest（指标聚合单测 + 效果分模型测试 + 灰度调度测试 + 回滚测试 + 标记测试）

**Target Platform**: 自托管 Docker Compose

**Project Type**: 既有模块扩展（Skill 市场强化，P2 后置）

## 现有挂载点依据

- 版本模型：`admin-api/services/skill_lifecycle.py`（`OrganizationSkillLifecycle` 版本/发布，016 在其上叠加）
- 调用指标：复用既有审计/事件 + `chat-api/token_usage`（调用量/成功率来源）
- 灰度调度：复用 `chat-api/scheduled_tasks`（周期任务框架）
- 低质量标记：与 011 Dream Cycle 的"低采纳淘汰"口径对齐（011 做经验侧淘汰，016 做市场侧标记，二者不重复）

## Constitution Check

| 原则 | 结果 |
|---|---|
| I. Specification-First | 通过 |
| II. Production Readiness | 通过：灰度/回滚可追溯 |
| III. Security | 通过：标记/回滚事件审计 |
| IV. i18n | 通过 |
| V. Observability | 通过：本特性即调用监控刚需 |

## Project Structure

```text
services/admin-api/app/
├── services/
│   ├── skill_lifecycle.py   # 既有：版本/发布基础
│   └── skill_market/        # 新增市场强化
│       ├── __init__.py
│       ├── metrics.py        # 调用监控聚合
│       ├── scoring.py        # 效果打分模型
│       ├── rollout.py        # 灰度调度 + 回滚
│       └── marking.py        # 低质量自动标记
services/chat-api/app/scheduled_tasks/  # 既有：灰度周期调度复用
```

## Open Questions（已 clarify 消解）
- OQ-1 效果分口径：**成功率（0.5）+ 采纳率（0.3）+ 纠正率反向（0.2）加权**；权重可配（`skill_scoring_weights`）。
- OQ-2 灰度策略：**按租户**（首期，最粗粒度，匹配自托管多租户）；按比例/按用户为后续扩展。
- OQ-3 回滚触发：**异常率 > 20% 自动回滚**（可配阈值 `rollout_auto_rollback_threshold`）+ 手动回滚。
- OQ-4 低质量标记阈值：**效果分 < 0.4 持续 7 天 → 自动标记低质量**（窗口可配 `quality_mark_window_days`）。
- OQ-5 与 011 分工边界：**011 做经验侧"低采纳淘汰"（自进化闭环），016 做市场侧"低质量标记/降权"**；二者共用同一标记位 `skill_status.marked_low_quality`，避免双写。

## OQ-6 效果分三维的数据归因口径（2026-10-03 决策 + 同日实现）

FR-3 的效果分需要 `successful_calls` / `adopted_calls` / `corrected_calls` 三个维度。落地调研确认：
三维此前都没有"按 skill 归因"的事实，需先定口径。口径与实现状态如下（**四项均已实现**，见 `tasks.md` T020–T024）：

- **调用总数 `total_calls`**：已有真实源，✅ 已实现。DSH kernel 的 `skill.selected` 事件经
  `dsh_runtime/events/projection.py` 投影为 `item_kind="activity"` / `payload.category="skill"` 行，
  持久化在 `kernel_event_projections`，`item_id` 形如 `{message_id}:selected-skill:{source_id}`。
  admin-api `skill_market.quality_metrics.collect_skill_activity_metrics` 按 `stream_seq` 水位滚动采集。
- **采纳 `adopted_calls` —— 口径 = 按 `message_id` 关联**：某轮选中了 skill S（上条 `skill.selected` 携带
  `message_id`），且该 `message_id` 下存在 `enterprise_authoritative_deliveries` 里 `accepted=True` 的记录
  （由 `chat-api` `enterprise_capabilities/delivery/repository.py` 的 `AuthoritativeDeliveryRepository`
  在 `delivery_mode == "authoritative_markdown"` 的工具产出被接受时写入），则该次计为 S 的一次"采纳"。
  **数据两边都已存在，仅需按 `message_id` 关联，不需要新埋点。**
  注意：delivery 记录的是 `tool_name` 而非 skill；skill 是"注入提示影响模型行为"，其效果只能通过
  同轮 message 关联，故采用 message 级归因，而非 tool 级。
- **纠正 `corrected_calls` —— 口径 = 用户编辑该轮产物并保存**：以
  `POST /documents/save-blueprint`（`chat-api/app/api/endpoints/documents.py`，注释即
  "Save an **edited** blueprint back"）为"编辑产物"信号，配合 `blueprint_object_path` 与编辑后内容判定。
  ⚠️ **该端点目前只覆盖对象存储，不写任何 DB/审计/编辑事件** —— 因此纠正维度**必须先新增"编辑事件"
  埋点**（记录 `blueprint_object_path`、`tenant_id`/`user_id`、编辑前后指纹、来源 `message_id`）才能采集。
  这是本轮唯一需要新增埋点的维度。
- **成功 `successful_calls` —— 口径 = kernel_session + 时间窗（已实现）**：receipt 无 `message_id`
  （`EnterpriseActionReceipt` 只有 `conversation_id`/`kernel_session_id`），故按 `kernel_session_id` 归因：
  该 skill activity 前后 ±30min（`DEFAULT_SUCCESS_WINDOW_SECONDS`）内无 `failed`/`timed_out` 的
  `enterprise_action_receipts` 即视为成功。
- **实现状态（2026-10-03 同日完成）**：采集器已产出四维（total / success / adopted / corrected）。
  完整性门槛改为 `total_calls >= MIN_EFFECT_SAMPLES(20)` **且** `success_tracked`（采集器写入 success
  时置位；legacy total-only 桶仍被拒绝，防止只凭 total 得 0.2 分误杀全部 skill）。端到端测试
  （`test_three_dimensions_can_actually_mark_a_low_quality_skill`）已证明：三维齐备时低质量标记可被真实触发。

## 下一步
OQ 已 clarify 消解。P2 后置，按路线图节奏推进：`/speckit-checklist` → `/speckit-tasks` → `/speckit-analyze` → `/speckit-implement` → `/speckit-converge`。
