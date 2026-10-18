# Implementation Plan: 模型供应商发现与多协议接入（031-model-provider-discover）

**Branch**: `031-model-provider-discover` | **Date**: 2026-10-18 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/031-model-provider-discover/spec.md`

**Note**: 本计划为**代码先行的回溯补规格**——实现已在 commit `6ea16f3` 落地，本文件把实现口径与剩余项固化。

## Summary

在「新增模型配置」中免去手敲模型 ID：admin-api 新增 `POST /api/models/discover`，用已配置的 baseUrl+apiKey 直连 provider 真实 API 拉回模型清单；本次将 discover 从 OpenAI/Azure 扩展到 **Anthropic / Gemini / Ollama** 三类协议（种子 + 前端类型 + 连接测试分发），并在首次配置向导 `SetupModelFields` 为这三类补专属字段提示。

## Technical Context

**Language/Version**: Python 3.11+（admin-api，FastAPI + pydantic v2）；TypeScript 5（admin-web，Vue 3 + naive-ui）

**Primary Dependencies**: FastAPI、pydantic、标准库 `urllib.request` + `asyncio.to_thread`（admin-api 无 httpx）；Vue 3 SFC、naive-ui、`@vue/compiler-sfc`（仅校验）

**Storage**: N/A（discover 为实时代理调用，不落库；provider 种子随 `DEFAULT_PROVIDERS` 在仓库内定义）

**Testing**: pytest（admin-api，`tests/test_models_discover.py` 11 项）；`@vue/compiler-sfc` 单文件编译校验（前端 SFC，替代全量 vue-tsc/vite build）

**Target Platform**: Docker Compose（admin-api 后端服务 + admin-web 前端）；自托管 Linux/Docker

**Project Type**: web-service（admin-api）+ web-app（admin-web），pnpm 工作区

**Performance Goals**: discover 为同步 HTTP 经 `asyncio.to_thread` 包装，单次拉取受 provider 接口延迟约束（无额外批处理）；占位/提示为纯前端 computed，无网络开销

**Constraints**: 后端不得引入 httpx（沿用 urllib）；provider_type 取值须在三处（seed / setup 校验 / 连接测试 / 前端类型）保持一致；前端改动须保持中英文双语文案键（i18n 缺翻译时回退中文 key）

**Scale/Scope**: 5 类 provider 协议；3 条新种子；2 个前端组件改造（ModelsPage.vue 已落地、SetupModelFields.vue 本轮扩展）

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Specification-First**: ✅ 本文件即补规格动作，符合"既有代码回溯补 spec"路径（参照 027/030）。
- **II. Enterprise Production Readiness**: ✅ discover 复用既有 `_build_ssl_context` / `_format_url_error`，失败路径可观测、不静默；不引入未验证镜像发布。
- **III. Security and Data Protection**: ✅ API Key 仅用于本次代理调用，复用 `_decrypt_api_key`；不落库、不写日志明文；gemini key 走 URL 参数、anthropic 走 header，均不回显。
- **IV. Cross-Platform and i18n**: ✅ 前端文案走 `t()` 中文 key 回退，保持双语可用。
- **V. Observability and Simplicity**: ✅ 不新增架构复杂度（纯函数 + 路由分发），符合 YAGNI。

## Project Structure

### Documentation (this feature)

```text
specs/031-model-provider-discover/
├── spec.md              # 特性规约（本文件引用的 spec）
├── plan.md              # 本文件
├── tasks.md             # 任务清单（已实现项已勾选）
└── checklists/          # 需求质量门禁（待 /speckit-checklist 生成）
```

### Source Code (repository root)

```text
services/admin-api/
├── app/api/routes/models.py          # 新增 discover 端点 + 五协议 discover 纯函数 + 连接测试三协议分支
├── app/repositories/model_repository.py  # DEFAULT_PROVIDERS 新增 anthropic/gemini/ollama 三条
└── tests/test_models_discover.py     # 新建：11 项 discover 单测

apps/admin-web/
├── src/api/models.ts                 # 新增 discoverProviderModels() 与 DiscoveredModel 接口
├── src/components/models/providerLabels.ts  # providerMessageKeys 新增三类
├── src/views/models/ModelsPage.vue   # 模型 ID 字段改 n-input-group + 「获取列表」弹窗（已落地）
└── src/components/setup/SetupModelFields.vue  # 首次向导字段提示扩展（本轮）
```

**Structure Decision**: 复用既有 monorepo 布局（admin-api 后端服务 + admin-web 前端 pnpm 工作区），不新增子项目、不新增依赖；discover 作为既有 models 路由的一个端点扩展，种子复用 `DEFAULT_PROVIDERS` 既有结构。

## Complexity Tracking

> 无 constitution 违规，无需复杂度论证。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | — | — |
