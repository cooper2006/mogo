# Implementation Plan: 评测门禁（032-eval-gate）

**Branch**: `032-eval-gate` | **Date**: 2026-10-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/032-eval-gate/spec.md`

**Note**: **全新特性，代码尚未开工**——本计划先于实现落地，按 tasks.md（Phase 0 研究 → Phase 1 设计 → Phase 2 实现 → Phase 3 验证与接线）正向推进。

## Summary

在 `skill_lifecycle.publish()` 写入版本快照前插入硬门禁：admin-api 新增自包含模块 `eval_gate/`（黄金测试集 CRUD + 规则判定器 + 评测执行器 + 阈值策略），待发布草稿经 **chat-api 模型网关**（复用 007 韧性）逐用例执行，以三项可计算指标（引用支撑率 / 拒答正确率 / 任务成功率）对照租户阈值策略判定；不达标时 fail-closed 阻断发布（不生成 release）并复用 001 的 `gate_events` 审计汇聚点落事件。前端仅在发布对话框（`SkillPublishDialog.vue`）增量展示评测报告与试运行入口。

## Technical Context

**Language/Version**: Python 3.11+（admin-api，FastAPI + pydantic v2）；TypeScript 5（admin-web，Vue 3 + naive-ui）

**Primary Dependencies**: FastAPI、pydantic、MongoDB（`app.core.db.get_db`）、标准库 `urllib.request` + `asyncio.to_thread`（admin-api 出站 HTTP 既有范式，参照 `services/admin-api/app/services/skill_package_proxy.py`）；Vue 3 SFC、naive-ui、`@vue/compiler-sfc`（仅校验）

**Storage**: MongoDB 新增三个集合——`skill_eval_cases`（测试集）、`skill_eval_policies`（阈值策略）、`skill_eval_runs`（评测记录）；复用 `get_db()`，不引入新存储

**Testing**: pytest（admin-api，`tests/test_eval_gate.py`：判定器单测 + 门禁端到端 + fail-closed 路径）；`@vue/compiler-sfc` 单文件编译校验（前端 SFC，替代全量 vue-tsc/vite build）

**Target Platform**: Docker Compose（admin-api + chat-api 双服务协作）；自托管 Linux/Docker

**Project Type**: web-service（admin-api 为主体）+ web-app（admin-web 增量），pnpm 工作区

**Performance Goals**: 发布同步评测受用例数（默认 ≤50）与 LLM 延迟约束；整体超时默认 300s，超时即失败 fail-closed；无后台任务、无队列积压风险

**Constraints**: admin-api 不引入新 LLM 客户端、不引入新网络库（urllib 范式）；门禁不可整体关闭（FR-006）；评测记录不存完整 LLM 输出（FR-009）；前端新增文案走 `t()` 中文 key 回退（i18n 缺翻译时回退中文本身）

**Scale/Scope**: 1 个新模块（`eval_gate/`，约 7 个文件）+ 3 个新集合 + 1 处挂卡（`skill_lifecycle.publish()`）+ 1 条新路由（`skill_eval.py`）+ 1 个前端组件增量；预计 FR 12 条、US 3 个

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Specification-First**: ✅ 本特性 spec/plan/tasks 三件套先于代码落地，纯 SDD 正向流程（区别于 031 的回溯补规格）；tasks 全部未勾选，实现按清单推进。
- **II. Enterprise Production Readiness**: ✅ fail-closed 默认 + 同步执行 + 超时隔离，不引入任务队列/新基础设施；复用 007 韧性与既有 MongoDB；评测失败路径可观测（审计 + `skill_eval_runs`），不静默。
- **III. Security and Data Protection**: ✅ 服务间调用复用 `backend_service_token`（`services/admin-api/app/core/internal_service_auth.py` 的凭据解析）；测试集与评测数据按 `tenant_id` 隔离；评测记录只存判定摘要不存完整输出，避免评测库成为业务数据副本；审计不含敏感明文。
- **IV. Cross-Platform and i18n**: ✅ 前端新增文案（报告展示、试运行按钮）走 `t()` 中文 key 回退，保持中英文双语可用；无平台相关分支。
- **V. Observability and Simplicity**: ✅ 规则判定器确定性可复现；不引入 LLM-as-judge、任务队列、逃生通道（YAGNI）；架构增量限于一个自包含模块 + 一个挂卡点。

## Project Structure

### Documentation (this feature)

```text
specs/032-eval-gate/
├── spec.md              # 特性规约（本计划引用的 spec）
├── plan.md              # 本文件
└── tasks.md             # 任务清单（全新特性，全部未勾选）
```

### Source Code (repository root)

```text
services/admin-api/
├── app/services/eval_gate/
│   ├── __init__.py          # 新增：模块导出与 ensure_indexes
│   ├── models.py            # 新增：EvalCase/EvalPolicy/EvalRun 与集合名常量
│   ├── test_sets.py         # 新增：测试集 CRUD（租户隔离 + 用例上限）
│   ├── policies.py          # 新增：阈值策略（默认 fail-closed 值 + 租户覆盖）
│   ├── judges.py            # 新增：三指标规则判定器（确定性）
│   ├── executor.py          # 新增：评测执行器（chat-api 网关调用 + 超时隔离）
│   └── gate.py              # 新增：门禁编排（publish 前判定）+ gate_events 审计
├── app/api/routes/skill_eval.py      # 新增：测试集 CRUD + dry-run + 报告查询路由
├── app/services/skill_lifecycle.py   # 复用+改动：publish() 插入门禁调用与 EvalGateBlocked
├── app/api/routes/skill_lifecycle.py # 复用+改动：publish 路由 except 分支映射阻断为 4xx
└── tests/test_eval_gate.py           # 新增：判定器/门禁/fail-closed 单测

apps/admin-web/
├── src/api/skillEval.ts              # 新增：试运行评测 + 报告查询 + 测试集 API 客户端
└── src/views/skills/SkillPublishDialog.vue  # 复用+改动：发布对话框展示评测报告 + 试运行入口
```

**Structure Decision**: 复用既有 monorepo 布局与 admin-api 服务分层（`app/services/` + `app/api/routes/`），`eval_gate` 作为自包含新模块，经 `skill_lifecycle.publish()` **单一挂卡点**接入发布链路；不新增子项目、不新增第三方依赖；测试集管理 UI 首期不做（API 先行，Non-Goal），前端增量限于发布对话框报告展示。

## Complexity Tracking

> 无 constitution 违规，无需复杂度论证。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | — | — |
