# Implementation Plan: 资产发布管控增强（比例灰度 + 影子发布）（033-canary-rollout）

**Branch**: `033-canary-rollout` | **Date**: 2026-10-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/033-canary-rollout/spec.md`

**Note**: **全新特性，代码尚未开工**——本计划先于实现落地，按 tasks.md（Phase 0 研究 → Phase 1 设计 → Phase 2 实现 → Phase 3 验证与接线）正向推进。

## Summary

在 016 既有按租户 canary 之上扩展三个维度：`Rollout` 增加 `traffic_ratio` 与阶梯字段（默认 1%→10%→50%→100% 可配置），由阶梯推进器按"样本 ≥20 且异常率 ≤20%"自动推进（并入既有 5 分钟扫描循环，到 100% 置 `PROMOTED`）；分流按 `(tenant_id, user_id)` 确定性哈希实现用户粘滞；影子模式在 chat-api Skill 调用入口对未命中比例的用户双跑候选版本——结果只记录不返回、不计入回滚判定、异常隔离吞并；既有自动回滚（20%/20）与手动一键回滚路由原样保留。admin-web 新增灰度配置页承载配置、进度、影子统计与一键回滚。

## Technical Context

**Language/Version**: Python 3.11+（admin-api 与 chat-api，FastAPI + pydantic v2）；TypeScript 5（admin-web，Vue 3 + naive-ui）

**Primary Dependencies**: FastAPI、pydantic、MongoDB（`app.core.db.get_db`，既有 `skill_rollouts` 集合扩展字段）；chat-api 侧复用 `dsh_runtime` 既有 Skill 解析/执行路径；Vue 3 SFC、naive-ui、`@vue/compiler-sfc`（仅校验）

**Storage**: MongoDB：`skill_rollouts`（扩展 `traffic_ratio` / `ladder` / `current_step` / `ladder_history` / `shadow_enabled` 字段，旧行读取默认值兼容）；新增 `skill_shadow_runs`（影子观察记录，只写 + 基础聚合查询）

**Testing**: pytest（admin-api 契约测试 `tests/test_canary_ratio.py` + 016 既有回归 `tests/` 下 canary 用例；chat-api 影子分流契约测试）；`@vue/compiler-sfc` 单文件编译校验（前端 SFC）

**Target Platform**: Docker Compose（admin-api + chat-api + admin-web）；自托管 Linux/Docker

**Project Type**: web-service（admin-api + chat-api）+ web-app（admin-web 新增页面），pnpm 工作区

**Performance Goals**: 分流为纯哈希计算（O(1)，无存储访问）；阶梯推进评估并入既有 5 分钟扫描循环，不新增定时任务；影子双跑的额外 LLM 成本由租户显式开启影子时承担（默认关闭）

**Constraints**: 不改 016 `evaluate_canary` / `apply_rollback` / `CanaryRollbackScanner` 核心逻辑；手动回滚路由与语义不变（FR-010）；影子结果绝不可进入用户响应路径；存量 `skill_rollouts` 行必须兼容（默认 ratio=1.0）；前端文案走 `t()` 中文 key 回退

**Scale/Scope**: `canary.py` 维度扩展 + 1 个阶梯推进器 + 1 个分流纯函数 + chat-api 1 处影子分流点 + `skill_canary.py` 路由参数扩展 + admin-web 1 个新页面；预计 FR 14 条、US 4 个

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Specification-First**: ✅ 本特性 spec/plan/tasks 三件套先于代码落地，纯 SDD 正向流程；tasks 全部未勾选，016 既有契约作为回归基线写入 FR-014/SC-005。
- **II. Enterprise Production Readiness**: ✅ 复用 016 生产已验证的回滚状态机与扫描器（不重造）；影子执行隔离吞并、绝不影响用户路径；存量数据兼容有明确默认值；回滚可追溯（前/后版本 + 原因）。
- **III. Security and Data Protection**: ✅ 分流仅用 `tenant_id`/`user_id` 做确定性哈希（不引入新身份数据）；`skill_shadow_runs` 只存执行观察指标（耗时/结果/错误摘要），不存用户内容；路由服务 token 鉴权模式不变。
- **IV. Cross-Platform and i18n**: ✅ 前端灰度配置页新增文案走 `t()` 中文 key 回退，保持中英文双语可用；无平台相关分支。
- **V. Observability and Simplicity**: ✅ 阶梯推进复用既有扫描循环（不新增调度器）；分流为无状态纯函数；影子统计走既有 MongoDB 查询模式；YAGNI——不做人群灰度、显著性检验、深度比对看板。

## Project Structure

### Documentation (this feature)

```text
specs/033-canary-rollout/
├── spec.md              # 特性规约（本计划引用的 spec）
├── plan.md              # 本文件
└── tasks.md             # 任务清单（全新特性，全部未勾选）
```

### Source Code (repository root)

```text
services/admin-api/
├── app/services/skill_market/canary.py    # 复用+改动：Rollout 增加 traffic_ratio/ladder/current_step/ladder_history/shadow_enabled；新增阶梯推进器与分流纯函数（旧行兼容默认值）
├── app/api/routes/skill_canary.py         # 复用+改动：创建/查询扩展 traffic_ratio/ladder/shadow 参数；查询返回档位与影子统计；手动回滚路由保留
└── tests/test_canary_ratio.py             # 新增：阶梯推进/影子隔离/分流确定性/存量兼容契约测试

services/chat-api/
├── app/dsh_runtime/（Skill 调用入口分流点）  # 复用+改动：命中判定 + 影子双跑 + skill_shadow_runs 落库 + 异常吞并隔离（具体挂载文件由 Phase 0 T002 确认，候选：profile/skills/resolver.py、turn_runner.py）
└── tests/（影子分流契约测试）               # 新增：用户结果来自稳定版、影子失败不回滚

apps/admin-web/
├── src/api/skillCanary.ts                 # 新增：灰度创建/查询/推进/回滚 API 客户端
└── src/views/skills/SkillCanaryConfigPage.vue  # 新增：灰度配置页（阶梯/影子配置、进度与影子统计、一键回滚）
```

**Structure Decision**: 复用既有 monorepo 布局——016 的 `skill_market/canary.py` 与 `skill_canary.py` 原地扩展（维度增加而非新建模块，保证 016 契约零回归）；影子分流点落在 chat-api 既有 Skill 调用入口（一个判定 + 一个双跑 + 一个落库，不新建执行引擎）；admin-web 新增独立配置页，不复用发布对话框（与 032 的发布对话框增量各自独立、互不干扰）。

## Complexity Tracking

> 无 constitution 违规，无需复杂度论证。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | — | — |
