# Implementation Plan: Unified Context Address Space

**Branch**: `021-unified-context-address` | **Date**: 2026-10-05 | **Spec**: [spec.md](./spec.md)

**Input**: 受 OpenViking 启发的"上下文操作系统"层（虚拟路由 + per-type tier 适配器 + 委托式可见性 + 统一检索轨迹），首期 tenant = 017 memory。

## Summary

新增 `services/chat-api/app/context_space/`（或独立 service）子模块：URI 路由器 + tier 适配器注册表 + 委托式可见性解析 + 统一检索轨迹。不新建存储，复用 017/005/004/002 各后端库。首期只接 017 memory，验证范式后按节奏接入 resource/skill/session。

## Technical Context

**Language/Version**: Python 3.13（chat-api 既有栈）

**Primary Dependencies**: 017 `app.memory`（memory 根，首期）、后续 005/014/015/004/018/002

**Storage**: 无新增集合；轨迹落观测日志（复用既有 observability 通道，可视化由 008 ops-dashboard 承接）

**Testing**: 路由解析单测 + 委托可见性单测 + 轨迹回看单测

**Target Platform**: 自托管 Docker Compose

**Project Type**: 新增模块（P2 架构演进）

## 项目结构（首期）

```text
services/chat-api/app/context_space/
├── __init__.py
├── router.py        # mogo:// URI 解析 + 路由到各后端适配器
├── adapters/        # per-type tier 适配器（首期 memory，后续 resource/skill/session）
│   ├── base.py      # TierAdapter 接口 (l0,l1,l2,tierable,provenance)
│   └── memory.py    # 017 memory 适配器
├── visibility.py    # 委托式可见性：调各后端既有检查，静默裁剪
└── trace.py         # retrieval_trace 产出 + 观测日志落点（绑定 session/turn）
```

## 现有挂载点依据

- memory 根：017 `app.memory.address`（FR-17/FR-18），首期唯一接入
- 委托可见性：017 `visible_to` / 005 `retrieval_access_policy` / 014 `bizdata:read` / 015 `kg:read` / 004 角色授权 / 002 会话参与者
- 轨迹落点：复用 chat-api 既有 observability（具体通道由 008 ops-dashboard 承接可视化）
- 会话生命周期：009 `SessionStart`/`SessionEnd` 钩子

## Constitution Check

| 原则 | 结果 |
|---|---|
| I. Specification-First | 通过 |
| II. Production Readiness | 通过：首期 tenant 可端到端验证 |
| III. Security | 通过：委托既有鉴权，不新增越权面 |
| IV. i18n | 通过 |
| V. Observability | 通过：轨迹可回看 |

## Open Questions（本轮已定）

- OQ-1 首期 tenant：**memory（017）**，resource/skill/session 地址约定先定、按节奏接入。
- OQ-2 可见性：**委托各后端**，地址层不建统一权限模型。
- OQ-3 非记忆类 L0/L1：**复用既有字段不调 LLM**。
- OQ-4 会话角色：消费 + 生产（SessionEnd→017 分层沉淀）+ 归档（mogo://session/...）。

## 下一步

先完成 017 优化（spec FR-13~FR-20 + Phase 5 任务），再落地 021 首期 memory tenant；resource/skill/session 接入随各自 spec 排期。
