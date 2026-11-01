# Tasks: Three-Scope Memory (personal / workspace / org)

> ⚠️ **落地审计（2026-10-03）：判定 `hollow`** —— 本文件 `[x]` 只代表**任务条目已勾选**，不代表功能落地。
> 按今天的标准（生产调用方/消费方/真实数据源/端到端可证伪）重检，本特性的结论是：三级 scope 纯函数+单测；app.memory 在 app/ 零生产导入，store/promote/sediment/endpoint 全缺失。
> 详见 [`specs/LANDING_AUDIT_2026-10-03.md`](../LANDING_AUDIT_2026-10-03.md)。
>
> **2026-10-05 重检（优化轮实现后）**：原审计对当前代码已不成立——`app.memory` 已被生产导入
>（`enterprise_capabilities/runtime/adapters.py:78` RAG 注入、`api/endpoints/memory.py` CRUD、`main.py:364` 衰减循环）。
> 本轮在此基础上落地了**密度轴**：`tiering.py`/`address.py`/`sediment.py` + `store`/`retrieval`/`scope` 分层扩展 + `context_space`（021）首期 memory tenant。
> **残留**：009 `SessionEnd` → `on_session_end` 的调度接线仍是**已定义未接线的 seam**（见 T016 注）；其余均已实现并通过单测（35 项新增 + 20 项既有）。

**Input**: Design documents from `/specs/017-three-scope-memory/`

**Prerequisites**: plan.md (required), spec.md (required)

**Clarify Decisions (governing tasks, 2026-07-08)**:
- 单人会话默认 personal、多人默认 workspace、组织需显式提升。
- 衰减 30 天（访问重置）；组织提升经 006 全能力管理员授权。

**Checklist Gate**: `checklists/requirements.md` 已 100% 勾选。

**Organization**: 落点 = `chat-api/app/memory/`。

---

## Phase 1: Setup (Module Skeleton)

- [x] T001 创建 chat-api/app/memory/ 包骨架 + 子模块
- [x] T002 定义核心数据模型/契约 schema

## Phase 2: Foundational (Blocking Prerequisites)

- [x] T003 [P] 实现核心纯逻辑（与 DB/网络解耦，可单测）
- [x] T004 [P] 实现声明式配置解析 + 校验

## Phase 3: User Story 1 (P1) — 三级记忆写入与隔离

- [x] T005 实现 scope 模型（personal/workspace/org）+ 存储隔离
- [x] T006 实现可见性隔离（个人/成员/全组织）
- [x] T007 US1 测试：三级隔离无越权

## Phase 4: User Story 2 (P2) — 范围升级 + 生命周期

- [x] T008 实现范围升级授权（经 006 + 审计）
- [x] T009 实现衰减/清理（30 天，访问重置）
- [x] T010 实现记忆进 RAG 检索（按 scope 过滤）
- [x] T011 US2 测试：升级授权 + 衰减 + 检索过滤


## Phase 5: 密度分层 + 渐进检索 + 地址暴露 + 会话结合（A/B/C + 会话，2026-10-05 优化轮）

> 本轮优化：受 OpenViking 思路（统一地址空间 + L0/L1/L2 + 检索轨迹）启发，给 017 叠加与 scope 正交的"密度轴"，并把会话（002/009）纳入统一上下文。详见 spec FR-13~FR-20、plan OQ-6/10/11/13。

- [x] T012 实现密度模型（tiering.py：l0/l1/l2 字段 + 写入时上游 LLM 生成 + summary_refresh_days 过期惰性回退；纯二进制标记 `tierable=false` 走 FR-16 兜底）。`Memory` dataclass 已扩展，`config` 新增 `MEMORY_SUMMARY_REFRESH_DAYS=30` / `MEMORY_L2_HARD_MAX_BYTES`。
- [x] T013 实现渐进检索（retrieval.py：`progressive_memory_retrieval` L0→L1→按需 L2；`memory_rag_candidates` 增加 tier 字段；产出 `retrieval_trace` 绑定 session_id/turn_id，已接入 `adapters.knowledge_search` 真实 RAG 路径）。
- [x] T014 实现 `mogo://memory/<scope>/<owner>/<id>/[L0|L1|L2]` 地址解析（address.py + `Memory.addr()`，供 021 统一上下文地址空间消费）。
- [x] T015 实现会话上下文可见性（FR-19：021 `visibility.py` 委托 017 `visible_to`，按 `viewer_id/role/is_workspace_member` 判定；单人/co-presence 由请求上下文的 `is_workspace_member` 体现）。
- [x] T016 实现会话沉淀→分层记忆（FR-20：已实现 `sediment.py` 的 `on_session_end`/`build_session_memory`，产出 L0/L1/L2 + `source_session_id`/`source_type=session`）。生产接线：`api/endpoints/sessions.py:998-1013` 会话删除端点调用 `sediment_session_end`（best-effort，异常不阻塞删除）；`sediment.py` 内 `emit_hook` 可选发射 009 `SessionEnd` 事件。
- [x] T017 测试：分层检索默认不注入 L2 + 轨迹可回看 + 会话可见性 + 沉淀产分层记忆（新增 `test_tiering/address/retrieval_trace/sediment/store_tier/context_space`，共 35 项，全部通过）。
- [x] T018 文档：更新 `quickstart.md` + `contracts/`（mogo:// 地址与 tier 适配器示例）—— **已完成（2026-10-06 QA 审计）**。`quickstart.md` 补齐两条正交轴说明、密度分层用法（写时/读时两条路径）、`_select_tier` 降级规则、`progressive_memory_retrieval`、地址往返、会话沉淀接线；新增 `contracts/memory-context-contract.md`（017+021 合并契约：正交轴、10 条不变量、地址语法、可见性委托矩阵、HTTP 契约、沉淀接线图）。文档内引用的全部符号与地址往返不变量已用脚本验证真实可用。

## Polish & Cross-Cutting Concerns

- [x] T999 [P] 审计/可观测接入
- [x] T998 写 `quickstart.md` + `contracts/` 契约文档

---

## Dependencies

```text
Phase 1 → Phase 2 → 各用户故事（按 spec 优先级 P1→P2）→ Polish
```

## MVP Scope
- **最小 = Phase 1 + Phase 2 + 首个 P1 故事**；其余按优先级增量。

## Notes
- 跨特性关系已在 spec 双向声明；复用 005 个人知识底层；不改变 005 契约。
- 本轮已改 `services/chat-api/app/memory/*`、`app/api/endpoints/memory.py`、`app/enterprise_capabilities/runtime/adapters.py`、`app/core/config.py`，并新增 `app/context_space/`（021 首期 tenant）。单测 35 项新增 + 20 项既有全绿。
