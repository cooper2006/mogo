# Implementation Plan: Session-Level Versioning, Handoff & Collaboration

**Branch**: `002-session-versioning` | **Date**: 2026-07-08 | **Spec**: [spec.md](./spec.md)

**Input**: 缺口新特性。plan 把规格技术化，落到既有会话代码（`chat-api/api/endpoints/sessions.py` + `dsh_runtime/conversation/`）之上，复用现有版本化基础。

## Summary

现有会话已具备**部分**版本化基础：`sessions.py` 有 `_make_version_entry`（文档版本条目）、`versions` 列表（保留最近 12 版）、`_next_seq`（消息序号）与 `chat_messages` 按 seq 顺序。本特性在此之上补齐：显式 commit 快照（覆盖整个会话而非仅文档）、log 时间线、resume 线性续写、share 交接链接、co-presence，以及 commit/share 时的低熵秘密过滤。

## Technical Context

**Language/Version**: Python 3.13（chat-api 既有栈）

**Primary Dependencies**: MongoDB（chat_sessions + chat_messages + 新增 session_snapshots）；Redis（co-presence 在线态，可选）

**Storage**: 新增 `session_snapshots` 集合（commit 快照）+ 复用 `chat_messages`（线性时间线）

**Testing**: pytest（sessions 既有测试 + 快照/秘密过滤单测）

**Target Platform**: 自托管 Docker Compose

**Project Type**: backend-service（chat-api 会话模块扩展）

## 现有实现事实（contract 依据）

- `sessions.py`：
  - `_next_seq` → 消息按 session 内 seq 线性递增（天然支持线性时间线，不产生分叉）
  - `_make_version_entry(doc, version)` → 文档版本条目（title/content/preview/type/object_path/url）
  - `doc["versions"]` 保留最近 12 版（`prev_versions[-12:]`），文档更新即 version+1 追加
  - `SessionCreate/SessionUpdate/MessageAppend` → 会话与消息模型
- `dsh_runtime/conversation/repository.py` → 会话仓库

## Constitution Check

| 原则 | 结果 |
|---|---|
| I. Specification-First | 通过：spec 已定义 |
| II. Production Readiness | 通过：快照不可变、秘密过滤 |
| III. Security | 通过：秘密不上链、解引用审计 |
| IV. i18n | 通过：后端为主 |
| V. Observability | 通过：快照/交接事件审计 |

## Project Structure

```text
specs/002-session-versioning/
├── plan.md
├── research.md        # 既有版本化基础（sessions.py versions/seq）调研
├── data-model.md      # session_snapshots 字段 + 线性时间线约束
├── contracts/
│   └── session-versioning-contract.md  # commit/log/resume/share API 契约
└── quickstart.md
```

源码改动（最小）：
- `chat-api/app/api/endpoints/sessions.py`：新增 commit/log/resume/share 端点 + 秘密过滤钩子
- 新增 `chat-api/app/services/session_versioning/`：快照存储、线性合并、低熵识别、可逆占位符
- 复用 001 审计落点（若 001 未实现，先用 system_audit 现有通道）

## Open Questions
- OQ-1: 快照存储用独立 collection（session_snapshots）还是内嵌 session 文档？（大数据量建议独立）
- OQ-2: 低熵秘密识别算法（Shannon 熵阈值 + 正则特征）的具体阈值需 clarify
- OQ-3: co-presence 是否需要 Redis 在线态，还是仅靠 MongoDB 会话状态即可（首期建议不引入 Redis）
- OQ-4: share 链接的鉴权模型（与 006 RBAC 权限码联动还是独立 token）

## 下一步
`/speckit-clarify` 消解 OQ → 补 research/data-model/contracts/quickstart → checklist → tasks → analyze。
