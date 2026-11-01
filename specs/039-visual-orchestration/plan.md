# Implementation Plan: 可视化编排画布（039-visual-orchestration）

**Branch**: `039-visual-orchestration` | **Date**: 2026-10-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/039-visual-orchestration/spec.md`

**Note**: 本特性为**全新特性**（代码尚未开工，非回溯补规格）。计划按 spec → plan → tasks → 实现推进；若实现中需偏离本计划，先回改 spec 再动代码。

## Summary

给 010 DAG 引擎补前端可视化画布（user-web + vue-flow）：新增序列化/反序列化模块作为画布 JSON ↔ 010 YAML 的唯一转换层（YAML 为权威定义，画布是投影；`layout` 为可丢失的投影元数据存于 YAML 顶层）；chat-api 新增编排定义读写端点（当前 `dag_definitions` 无 HTTP API）与 `store._document_shape` 的 `layout` 透传（**两处联合改动点，需同步 010 spec**）；画布保存前做与引擎侧一致的校验（环/孤立节点/非法条件），发布走 001 gatekeeper 与 010 版本化语义。引擎执行语义零改动。

## Technical Context

**Language/Version**: Python 3.11+（chat-api，FastAPI + pydantic v2）；TypeScript 5（user-web，Vue 3 + naive-ui）

**Primary Dependencies**: 后端复用 `app/orchestration/`（loader/store/registry/topo/conditions，零新依赖）；前端新增 `@vue-flow/core`（MIT，Vue 3 原生）及其配套（`@vue-flow/background` 等按需最小集）

**Storage**: MongoDB 既有集合 `dag_definitions`（010 store 已定义）；无新集合、无迁移脚本；`layout` 随 document 透传（联合改动点）

**Testing**: pytest（chat-api：序列化往返、校验一致性、编排端点契约、010 回归）；前端 `@vue/compiler-sfc` 单文件编译校验 SFC + 序列化模块 TS 单测（画布交互用手动验收，规避本机 vue-tsc/build 耗时）

**Target Platform**: Docker Compose（chat-api + user-web 既有服务）；自托管 Linux/Docker

**Project Type**: web-service（chat-api）+ web-app（user-web），pnpm 工作区

**Performance Goals**: 画布交互为纯前端渲染；序列化/反序列化为纯函数（YAML 解析走既有 PyYAML / 前端 js-yaml 或既有依赖）；保存/打开走一次 HTTP 往返；百节点图首期不做专项优化（记录限制）

**Constraints**: 不改 010 引擎执行语义（engine/supervisor/topo/conditions 零行为变更）；`layout` 可丢失不得影响有效性；首期只做 sequential/graph；不得新增第三种定义格式；发布不得绕过 001 gatekeeper

**Scale/Scope**: 1 个新前端页面（画布 + 属性面板 + 校验展示）、1 个序列化模块（画布 JSON ↔ YAML）、1 组 chat-api 编排端点、2 处 010 联合改动（store layout 透传 + 端点）；首期 2 种模式

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Specification-First**: ✅ 本计划紧随 spec（2026-10-23 同批立项），代码未开工；联合改动点（010 store/端点）已在 spec FR-011 与 tasks 显式列出并注明同步 010 spec。
- **II. Enterprise Production Readiness**: ✅ 保存走 010 既有 `dag_definitions` 持久化与版本化（生产已验证机制）；校验复用引擎侧 `topo`/`registry.validate()` 单一权威，不发明第二套判定；失败路径（打开损坏 YAML/坏 layout）有明确降级。
- **III. Security and Data Protection**: ✅ 发布过 001 gatekeeper（权限/审批），画布无直通生产路径；租户隔离遵循既有数据边界；画布不透出凭证类字段（节点 payload 仅 010 既有声明式键）。
- **IV. Cross-Platform and i18n**: ✅ user-web 新页面文案走 `t()` 中文 key 回退，保持双语可用；画布库无平台分支。
- **V. Observability and Simplicity**: ✅ 单一转换层（序列化模块）+ 单一校验权威（引擎侧）；不新增持久化格式、不新增缓存层；supervisor/hybrid 二期、协同编辑不做（YAGNI）。

## Project Structure

### Documentation (this feature)

```text
specs/039-visual-orchestration/
├── spec.md              # 特性规约（本计划的上游）
├── plan.md              # 本文件
└── tasks.md             # 任务清单（全新特性，全部未勾选）
```

### Source Code (repository root)

```text
services/chat-api/
├── app/orchestration/store.py               # 复用+联合改动：_document_shape 增加 layout 透传（需同步 010 spec）
├── app/orchestration/loader.py              # 复用：load_orchestration_document/text（零改动，raw 已透传 layout）
├── app/api/endpoints/orchestrations.py      # 新增：编排定义读写端点（dag_definitions 的 HTTP 出口）
└── tests/test_orchestration_canvas_api.py   # 新增：端点契约 + layout 透传 + 010 回归

apps/user-web/
├── src/api/orchestration.ts                 # 新增：编排定义 API client（对应 chat-api 端点）
├── src/components/orchestration/OrchestrationCanvasPage.vue   # 新增：画布页（vue-flow）
├── src/components/orchestration/canvasSchema.ts               # 新增：画布 JSON ↔ 010 YAML 序列化/反序列化（唯一转换层）
├── src/components/orchestration/NodePropertyPanel.vue         # 新增：节点属性面板（复用 Skill/工具选择器）
├── src/components/orchestration/canvasValidation.ts           # 新增：保存前校验（环/孤立节点/条件，与引擎同口径）
├── src/App.vue                              # 复用：组件式注册新页面（懒加载）
├── src/api/skills.ts                        # 复用：Skill 选择器数据源（属性面板）
└── src/api/tools.ts                         # 复用：工具选择器数据源（属性面板）
```

**Structure Decision**: 复用既有 monorepo 布局——画布落在 user-web（业务侧自助编排，与"降低编排门槛到业务人员"定位一致；admin-web 保持平台管理端定位），序列化逻辑放前端纯函数模块（画布 JSON 本就是前端模型，转换放前端避免为投影格式新增后端概念）；chat-api 只新增 `dag_definitions` 的 HTTP 出口（store/loader 语义不变）。010 引擎零行为改动，仅 store 一处透传字段 + 新增端点两处联合改动，均同步 010 spec。

## Complexity Tracking

> 无 constitution 违规，无需复杂度论证。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | — | — |
