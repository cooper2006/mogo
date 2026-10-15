# Implementation Plan: 为 user-web 新增 SSO 接收方

**Branch**: `029-user-web-sso-receiver` | **Date**: 2026-10-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/029-user-web-sso-receiver/spec.md`（设计闭环于 `docs/MOGO-Web应用集成方案.md` §1.3.2）

## Summary

为 MOGO 的 user-web 新增 **SSO 接收方**能力，使外部门户（企业自有门户 / 业务系统）已登录用户在**不二次登录**的前提下进入 MOGO 用户工作台。采用「路径 1：MOGO 签发 + 门户转发票据」：门户后端用 022 服务身份调 MOGO 签一次性 HMAC 票据 → 前端带票（经 `state=`）跳转 user-web → user-web 启动即换票、复用 `_create_session()` 建会话。账号按共享主键 `id` 匹配、不 JIT、多租户走挑战流程、票据跨域传递。

## Technical Context

**Language/Version**: Python 3.13（chat-api 后端）/ TypeScript + Vue 3（user-web 前端）

**Primary Dependencies**: FastAPI（chat-api 既有）；`hmac` / `hashlib`（stdlib，票据签名）；022 服务身份模块 `app/security/service_token.py` + `app/security/gatekeeper.py`（已具备）；Vue 3 `onMounted` + `window.history.state`（user-web）

**Storage**: MongoDB（复用既有 `end_users` / `end_user_sessions` 集合，**不新增集合**）；票据为内存态一次性凭证，不落独立表

**Testing**: `pytest`（chat-api 单测 / 集成，既有 `tests/` 体系）；user-web 前端测试（既有 Vitest / 组件测试体系）；门户侧为「外部系统」，仅提供示例，不进 MOGO 测试矩阵

**Target Platform**: Linux 服务（chat-api）/ 浏览器（user-web）

**Project Type**: web-service（chat-api 端点）+ frontend（user-web 启动换票）

**Performance Goals**: 换票建会话 p95 < 200ms（对齐现有登录）；票据 TTL 固定 60s

**Constraints**: 严格对齐 022 安全规约——fail-closed、常数时间比较、短 TTL、不落 URL、服务身份最小权限 scope；会话建立逻辑零改动（复用 `_create_session`）

**Scale/Scope**: 对接既有门户（单 / 多租户均支持）；MOGO 侧改动集中在 chat-api 2 端点 + user-web 启动逻辑 + gatekeeper scope 登记

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Specification-First（NON-NEGOTIABLE）**：本规约在落地前补全，符合 `.specify/memory/constitution.md` 的「先规格后实现」原则。✅ 通过（本文件即规格，且设计已在 §1.3.2 闭环）。
- **Agent Operating Rules（AGENTS.md）**：仅改本轮必要文件、不顺手重构；只 `git add` 具体路径；不越出工作区。✅ 规划已约束改动面。
- 无 Constitution 违规需 Complexity Tracking 声明。

## Project Structure

### Documentation (this feature)

```text
specs/029-user-web-sso-receiver/
├── plan.md              # 本文件
├── spec.md              # 特性规约（已填实）
└── tasks.md             # 任务拆分（4 阶段 + 测试）
```

> 本特性为「既有设计回溯补规格」，无需 Phase 0 research / data-model / contracts 独立产出；权威设计见 `docs/MOGO-Web应用集成方案.md` §1.3.2。

### Source Code (repository root)

```text
# 后端（chat-api）—— 新增 2 端点 + scope 登记
services/chat-api/app/api/endpoints/auth.py        # 新增 portal-ticket / portal-exchange，复用 _create_session
services/chat-api/app/security/service_token.py    # 既有；portal 用 scope 登记（如 portal:issue-ticket）
services/chat-api/app/security/gatekeeper.py       # 既有；端点注册表新增 portal-ticket 的 required_scope
services/chat-api/app/core/config.py               # 新增 PORTAL_SSO_SECRET（可选，缺省降级 END_USER_AUTH_SECRET）

# 前端（user-web）—— 启动换票
apps/user-web/src/App.vue                           # onMounted 读取 history.state.portalToken → replaceState 清除 → 换票 → 写 localStorage

# 门户侧（外部系统，仅示例，不进核心服务代码）
docs/samples/portal-sso-integration/               # 服务令牌调 portal-ticket + 前端跳转示例（阶段 3 交付物）
```

**Structure Decision**: 沿用既有 monorepo 布局（chat-api 属 `services/`，user-web 属 `apps/`），不引入新目录 / 新服务。票据签名密钥通过配置注入，复用既有 `app/core/config.py` 机制。

## 落地阶段映射（与 §1.3.2「落地阶段」一致）

| 阶段 | 内容 | 对应 tasks |
| --- | --- | --- |
| 1 | `portal-ticket` + `portal-exchange` 两端点 + 测试 | T1–T5 |
| 2 | user-web 启动换票 + 失败回落 | T6–T8 |
| 3 | 门户侧接入（服务令牌 + 跳转示例） | T9–T10 |
| 4 | 若多租户：接挑战流程 | T11–T13 |

## Complexity Tracking

> 无 Constitution 违规。本特性刻意**复用**既有 `_create_session` / `load_tenant_candidates` / `_create_login_challenge`，新增代码面小，不新增集合 / 不新增服务，复杂度可控。
