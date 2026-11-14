# Implementation Plan: 出站白名单与沙箱隔离强化（038-egress-sandbox）

**Branch**: `038-egress-sandbox` | **Date**: 2026-10-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/038-egress-sandbox/spec.md`

**Note**: 本特性为**全新特性**（代码尚未开工，非回溯补规格）。计划按 spec → plan → tasks → 实现推进；若实现中需偏离本计划，先回改 spec 再动代码。

## Summary

把脚本沙箱（`services/chat-api/app/enterprise_capabilities/data/script_engine/executor.py`，L572-576 `socket.socket = _deny_network`）的"网络默认拒绝"语义提升为全出站路径统一管控：新增独立白名单集合 `egress_allowlist`（平台/租户/工具三层，并集命中即放行）+ 共享出站检查器 `EgressGuard`；在 009 PreToolUse 的既有求值点（`tools/service.py:489-494`）内联落地 HTTP/MCP 工具出站检查，在 `browser_task` 入口（`browser/service.py:35`）落地浏览器 Agent 导航检查（含重定向落地判定）；admin-api 提供 CRUD、admin-web 提供配置页；命中/拒绝走既有审计通道。远程沙箱只保留 `kernel.py:63` 契约与接口预留，不实现本体。

## Technical Context

**Language/Version**: Python 3.11+（chat-api 与 admin-api，FastAPI + pydantic v2）；TypeScript 5（admin-web，Vue 3 + naive-ui）

**Primary Dependencies**: FastAPI、pydantic v2、MongoDB 驱动（既有 `get_db` 通道）；`urllib.parse`（URL 归一化，标准库，不引入新网络库）；前端 Vue 3 SFC + naive-ui

**Storage**: MongoDB 新集合 `egress_allowlist`（与 `hook_rules`、`dag_definitions` 同库）；无新表结构迁移（集合首次写入自动创建，种子数据随代码提供平台默认条目）

**Testing**: pytest（chat-api：`EgressGuard` 匹配/归一化/fail-closed 单测 + 两路径行为一致性 + 脚本沙箱回归；admin-api：CRUD 契约与租户隔离）；admin-web 用 `@vue/compiler-sfc` 单文件编译校验 SFC（规避本机 vue-tsc/build 耗时）

**Target Platform**: Docker Compose（chat-api / admin-api / admin-web 既有服务）；自托管 Linux/Docker

**Project Type**: web-service（chat-api + admin-api 双服务）+ web-app（admin-web），pnpm 工作区

**Performance Goals**: 出站检查为同步内存判定（白名单快照全量加载），单次判定毫秒级；超时预算可配（默认与 009 钩子 5s 同量级）；对工具调用链路的延迟增量可忽略

**Constraints**: 判定失败一律 fail-closed（不得提供放行配置）；不得新增 009 rule_type 枚举；不得修改脚本沙箱 `executor.py`；不得修改 `kernel.py` 契约枚举；不得引入新网络库；审计不记录完整 URL 查询串

**Scale/Scope**: 1 个新集合、1 个共享检查器、2 个执行挂载点（HTTP 工具 + 浏览器导航）、1 组 CRUD 路由、1 个前端配置页；白名单条目量级百级/租户

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Specification-First**: ✅ 本计划紧随 spec（2026-10-23 同批立项），代码未开工；任何偏离先回改 spec。
- **II. Enterprise Production Readiness**: ✅ 复用既有审计通道与 hooks 路由契约模式（信封/PATCH/204），失败路径可观测（`egress.denied` 全字段审计）；热更新复用 009"规则变更即时生效"已验证机制，不引入未验证组件。
- **III. Security and Data Protection**: ✅ 默认拒绝 + fail-closed（与 001 R4 恒拒同语义）；IP 字面量/非 http(s) scheme 前置拒绝同时构成 SSRF 防护；审计不落 URL 查询串；平台/租户/工具三层隔离，平台条目仅平台管理员可改。
- **IV. Cross-Platform and i18n**: ✅ admin-web 新页面文案走 `t()` 中文 key 回退（i18n 缺翻译时回退中文本身，无需改 locale 文件），保持双语可用；无平台相关分支逻辑。
- **V. Observability and Simplicity**: ✅ 不新增审计集合（复用工具调用审计通道）；单检查器两路径复用；三层并集语义一次说清；不建缓存层/索引服务（YAGNI）。

## Project Structure

### Documentation (this feature)

```text
specs/038-egress-sandbox/
├── spec.md              # 特性规约（本计划的上游）
├── plan.md              # 本文件
└── tasks.md             # 任务清单（全新特性，全部未勾选）
```

### Source Code (repository root)

```text
services/admin-api/
├── app/api/routes/egress.py            # 新增：白名单 CRUD（/api/egress/allowlist，仿 hooks.py 契约）
├── app/services/egress_store.py        # 新增：egress_allowlist 集合存取 + 三层查询 + 平台种子
└── tests/test_egress_allowlist.py      # 新增：CRUD/租户隔离/契约单测

services/chat-api/
├── app/enterprise_capabilities/tools/egress_guard.py   # 新增：EgressGuard（归一化+前置拒绝+三层并集+超时）
├── app/enterprise_capabilities/tools/service.py        # 复用：489-494 PreToolUse 求值点内联出站检查
├── app/enterprise_capabilities/browser/service.py      # 复用：browser_task 入口（L35）导航前置检查
├── app/enterprise_capabilities/browser/engine/action_contracts/_navigate.py  # 复用：final_url 回收点加重定向落地判定
├── app/services/external_tools.py                      # 复用：execute_runtime（L453）与凭证注入点（只读依赖，不改）
└── tests/test_egress_guard.py           # 新增：匹配/归一化/fail-closed/两路径一致性 + 脚本沙箱回归

apps/admin-web/
├── src/api/egress.ts                    # 新增：白名单 API client（对应 admin-api 路由）
├── src/views/egress/EgressAllowlistPage.vue  # 新增：三层白名单配置页
├── src/router/routes.ts                 # 复用：注册新页面路由（既有 vue-router 模式）
└── src/views/tools/ToolEditPage.vue     # 复用：工具编辑页挂工具级例外条目入口（本期最小挂点）
```

**Structure Decision**: 复用既有 monorepo 布局与双服务边界——配置态（CRUD/种子/租户隔离）归 admin-api（与 hooks CRUD 同侧，管理员已在 admin-web 操作），执行态（判定/拒绝/审计）归 chat-api（与工具调用链同进程，避免判定走网络往返）；两服务经同一 MongoDB 集合解耦（admin-api 写、chat-api 读快照）。不新增服务、不新增集合以外的存储、不引入新依赖。

## Complexity Tracking

> 无 constitution 违规，无需复杂度论证。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | — | — |
