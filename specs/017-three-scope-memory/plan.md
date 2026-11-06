# Implementation Plan: Three-Scope Memory Granularity

**Branch**: `017-three-scope-memory` | **Date**: 2026-07-08 | **Spec**: [spec.md](./spec.md)

> **版本标注（v3 / D4，2026-11-06）**：本文件题头日期为 2026-07-08；正文中标注为「旧稿 / 不再有 / 旧值」的历史沿革表述按原文保留。以上为 2026-07-08 原稿，已被 v3 取代 —— 范围轴当前有效口径为 `personal / project / department`（D4 直接改名、无兼容层），以 `spec.md` v3、`design-2026-11-05-project-department-scopes.md` 与 `contracts/memory-context-contract.md` 为准。

**Input**: 缺口新特性（P2 规模化生态，后置）。区分个人 / 项目 / 部门三级记忆范围，与特性 002（会话级多人协同）打通，让 Agent 在不同范围记住不同粒度上下文。

## Summary

新增 `services/chat-api/app/memory/` 子模块：三级记忆模型（scope 维度 + 存储隔离 + 可见性）+ 写入范围指定 + 范围升级授权（部门级需 001 授权 + 审计）+ 会话沉淀按范围共享（**分层记忆**，接 009 SessionEnd）+ **密度分层（L0/L1/L2）** + **渐进检索 + 检索轨迹（可回看）** + **`mogo://memory/...` 地址暴露**（供 021 统一上下文地址空间）。底层可复用 005 个人知识（个人范围）+ 新增 project/部门记忆存储。本特性是 021 统一上下文地址空间的**首个 tenant 样板**。

## Technical Context

**Language/Version**: Python 3.13（chat-api 既有栈）

**Primary Dependencies**: 既有 005 个人知识（个人范围底层）+ 新增 project/部门记忆集合 + `governance`（部门级写入授权/审计）

**Storage**: 新增 `memories`（含 scope ∈ {personal, project, department} + 可见性 + 衰减/生命周期字段 + **密度分层字段 `l0_summary` / `l1_overview` / `l2_raw` / `tierable` / `summary_generated_at` / `summary_refresh_days`（默认 30）/ `l2_hard_max_bytes` + provenance `source_session_id` / `source_type`**）；底层复用 005 个人知识

**Testing**: pytest（三级隔离单测 + 范围升级授权测试 + 会话沉淀共享测试 + 生命周期测试）

**Target Platform**: 自托管 Docker Compose

**Project Type**: 新增模块（三范围记忆，P2 后置）

## 现有挂载点依据

- 个人范围：复用 005 `api/endpoints/personal_knowledge.py`（个人知识目录/资源）作为底层存储参照
- 会话沉淀：复用 002 `sessions.py` 的会话/快照机制（会话结束 → 记忆按范围共享）
- 部门级授权/审计：复用 `governance/`（001 联动）
- 生命周期（衰减/清理）：新增配置项（阈值需 clarify）

## Constitution Check

| 原则 | 结果 |
|---|---|
| I. Specification-First | 通过 |
| II. Production Readiness | 通过：范围升级需授权 + 审计 |
| III. Security | 通过：跨范围读取不越权；部门级受 001 约束 |
| IV. i18n | 通过 |
| V. Observability | 通过：范围变更审计 |

## Project Structure

```text
services/chat-api/app/
└── memory/
    ├── __init__.py
    ├── viewer.py             # MemoryViewerContext + 统一身份解析（B1 已落地，v3 唯一上下文）
    ├── scope.py              # 三范围模型（personal/project/department）+ visible_to + promote_to_department
    ├── store.py              # 记忆存储 + 可见性隔离
    │                         # 无独立 promote.py：提升动作落在 endpoints/memory.py 的 promote 端点，
    │                         # 走增量 $set（spec D-6）；旧 Project Structure 曾列此文件，已标注移除
    ├── sediment.py           # 会话沉淀 → 记忆（按范围共享）
    ├── lifecycle.py          # 衰减/清理策略
    ├── tiering.py            # L0/L1/L2 密度生成（写入时调上游 LLM 钩子）+ 惰性回退（summary_refresh_days 过期补全）
    ├── retrieval.py          # 渐进检索（L0 粗筛 → L1 → 按需 L2）+ retrieval_trace 输出（绑定 session_id/turn_id）
    └── address.py            # mogo://memory/<personal|project|department>/<owner>/<id>/[L0|L1|L2] 地址解析（供 021 消费）
services/chat-api/app/api/endpoints/
└── memory.py                 # 记忆 CRUD + 范围指定 + promote（已存在；旧稿误记为「新增 memories.py」）
```

## Open Questions（已 clarify 消解）
- OQ-1 默认写入范围（**v3 D2**）：**有有效项目上下文 → `project`，否则 `personal`**；多人会话 → `project`（无有效项目上下文回落 `personal`）；不再有 `workspace` /「组织级默认」，提升到 `department` 一律显式且需授权。
- OQ-2 记忆生命周期：**衰减周期 30 天（可配 `memory_decay_days`），访问命中重置衰减计时；清理触发 = 衰减到期 + 未被引用**。
- OQ-3 范围提升授权与可见性（**v3**）：提升到 `department` 需 `full_access_admin` + 目标部门在 `visible_department_ids` 内 + 001 审计（G-1/G-2），普通用户走审批状态机；**可见性的唯一判据是 `visible_to(memory, MemoryViewerContext)`（B-4）**，不再按 `viewer_id` / `is_workspace_member` / `viewer_org_id` 等散参数判定，身份一律由服务端构造。
- OQ-4 与 005 个人知识关系：**复用 005 个人知识底层存储**（personal scope 直接指向 005 资源），不重复建库；project/department scope 新建 `memories` 集合。
- OQ-5 记忆检索：**进 RAG 检索范围**（与 005 检索融合），按 scope 可见性过滤。
- OQ-6 摘要刷新周期 `summary_refresh_days`：**默认 30**（与衰减 `memory_decay_days` 对齐，便于统一生命周期语义）。
- OQ-10 可见性委托（**v3 / D4**）：**021 地址层只委托、不重写鉴权** —— `memory` 根把 `ViewerContext.memory_viewer` 原样转给 017 `visible_to(memory, MemoryViewerContext)`，缺 `memory` 或缺 `memory_viewer` 一律 fail-closed；scope 段值域为 `personal|project|department`，旧 `workspace` / `org` 段运行时 404。其余后端仍各自委托（005 `retrieval_access_policy` / 014 `bizdata:read` / 015 `kg:read` / 004 角色授权 / 018 `a2a_exposed` / 002 会话参与者）。
- OQ-11 非记忆类 L0/L1 来源：**复用既有字段，不调 LLM**——doc chunk 用 005 citation 产物、biz 实体用 014 抽取、kg 节点用 015、skill 用 004 元数据+018 契约；仅 017 memory（自由文本）需上游 LLM 生成摘要。
- OQ-13 会话是否独立地址根：**是**，列为第四类 `mogo://session/<tenant>/<sessionId>/[L0|L1|L2]`（归档/浏览），活跃会话同时是统一上下文的消费方与生产方。

> **D4（v3，2026-11-06）**：`workspace/org → project/department` **直接改名、无运行时兼容层**——**无别名、无 `normalize_scope`、无双写、无字段级三级回退**；**代码全量替换与数据迁移须在同一维护窗口原子切换**（M1 代码替换不发布 → M2 冻结写入 + 幂等迁移 → M3 原子切换 + 解冻 → M4 对账），回滚必须走 `--reverse` 连数据一起回退。详见 `design-2026-11-05-project-department-scopes.md` §10 与 `rollout-017-d4-cutover.md`。

## 下一步
OQ 已 clarify 消解。P2 后置，按路线图节奏推进：`/speckit-checklist` → `/speckit-tasks` → `/speckit-analyze` → `/speckit-implement` → `/speckit-converge`。
