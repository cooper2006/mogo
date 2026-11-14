# Implementation Plan: 可信评级 L1–L4 资产分级（036-trust-rating）

**Branch**: `036-trust-rating` | **Date**: 2026-10-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/036-trust-rating/spec.md`

**Note**: 本计划为**全新特性的事前设计**——代码尚未开工，先过 Constitution Check，再按 tasks.md 的 Phase 0→3 推进。

## Summary

在 admin-api 新增 `trust_rating` 领域模块与评级管理 API：资产（Agent/Skill/工作流）打 L1–L4 可信评级（默认 L1），评级经 `TRUST_TO_AUTONOMY_CAP` 映射为 001 门禁的自主级上限（封顶在矩阵查询前生效），L4 写操作经 `gate_approvals` 扩展实现双人复核；新增周期扫描器实现「连续 21 天不达标自动降级 + 权限收缩 + 018 deprecated 迁移」，全链路审计接 022。核心策略是**映射绑定而非另起炉灶**：复用 001 矩阵/审批/审计、016 效果分、018 状态机，不修改其本体语义。

## Technical Context

**Language/Version**: Python 3.11+（admin-api，FastAPI + pydantic v2）；TypeScript 5（admin-web，Vue 3 + naive-ui）

**Primary Dependencies**: FastAPI、pydantic v2、MongoDB（经 `app.core.db.get_db()`，不引入 Redis/新存储）；前端 Vue 3 SFC + naive-ui + `@vue/compiler-sfc`（仅校验）

**Storage**: 新增 `trust_ratings` 集合（评级主档，键 `tenant_id + asset_type + asset_key`）+ `trust_autonomy_caps` 集合（租户覆盖，同构 `autonomy_matrix` 的 cell 文档模式）+ `trust_rating_scan_state` 单文档（扫描游标）；扩展 `gate_approvals` 文档字段（`required_approvals` / `approvals[]`，不新建集合）

**Testing**: pytest（admin-api：`tests/test_trust_rating.py` 纯函数 + API + 门禁封顶 + 双人复核 + 扫描器集成）；前端 `@vue/compiler-sfc` 单文件编译校验

**Target Platform**: Docker Compose（admin-api + admin-web）；自托管 Linux/Docker

**Project Type**: web-service（admin-api）+ web-app（admin-web），pnpm 工作区

**Performance Goals**: 封顶查表为一次 `trust_ratings` 点查（可随门禁上下文缓存，首期不缓存——评级变更低频，正确性优先）；扫描器周期对齐 016 `SkillQualityScanner`（默认 6h 级），单次扫描 O(持有评级的资产数)，按批处理

**Constraints**: 不得修改 `AUTONOMY_MATRIX` 25 格本体与 R4 恒拒；不得新建第二张审批表；单人审批路径零回归；`approval.py` 扩展必须向后兼容（旧票据无新字段时按 1 人审批）；降级/升级必须落 022 审计；自动降级开关默认开、可配

**Scale/Scope**: 4 档评级；3 类资产载体；1 个新领域模块 + 1 个新路由 + 2 处既有文件扩展（approval.py、main.py）+ admin-web 1 个新视图 + 1 个既有列表扩展

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Specification-First**: ✅ 本三件套先行，spec 已固化 7 项已定决策与 FR-001..017；tasks.md 全部未勾选，实现未开工。
- **II. Enterprise Production Readiness**: ✅ 失败路径全部 fail-closed（未授权 403、无评级按 L1 封顶、票据前提不满足拒绝消费、覆盖值非法回落常量）；扫描器复用 016 生产任务的启停模式；评级/降级全审计可追溯；无未验证镜像或配置漂移。
- **III. Security and Data Protection**: ✅ 双人复核要求两名**不同**审批人（防单人凑数）；requester 与 approver 分离沿用 001「审批与消费分离」教训；L1 owner-only 可见性收敛数据暴露面；审计不落 PII（仅 asset_key 与 actor）。
- **IV. Cross-Platform and i18n**: ✅ admin-web 新增文案走 `t()` 中文 key 回退（i18n 缺翻译时回退中文本身），保持双语可用；后端无平台相关分支。
- **V. Observability and Simplicity**: ✅ 不引入新框架/新存储/新调度；复用 001 矩阵即数据模式、016 扫描器样板、018 状态机；新增一个领域模块（ ratings + scanner）与一个路由，符合 YAGNI；扫描游标单文档提供可观测性。

## Project Structure

### Documentation (this feature)

```text
specs/036-trust-rating/
├── spec.md              # 特性规约（本文件引用的 spec）
├── plan.md              # 本文件
└── tasks.md             # 任务清单（全新特性，全部未勾选）
```

### Source Code (repository root)

```text
services/admin-api/
├── app/services/trust_rating/              # 新增：评级领域模块
│   ├── __init__.py
│   ├── ratings.py                          # 新增：TRUST_LEVELS/TRUST_TO_AUTONOMY_CAP/默认值/变更校验/上限解析/不达标判定纯函数
│   └── downgrade_scanner.py                # 新增：周期扫描（仿 quality_metrics.py SkillQualityScanner 启停模式）
├── app/api/routes/trust_ratings.py         # 新增：评级查询/变更/开关/分布聚合 API（RBAC: trust:read/trust:manage）
├── app/governance/layers/approval.py       # 复用+扩展：required_approvals/approvals[] 双人复核（向后兼容，单人路径零改动）
├── app/governance/risk.py                  # 复用：AUTONOMY_LEVELS 封顶校验与 R4 恒拒不变
├── app/governance/schema.py                # 复用参考：矩阵即数据/种子集合模式（trust_autonomy_caps 同构）
├── app/services/capability_assets/registry.py   # 复用：set_state 执行 deprecated 迁移（FR-12）
├── app/services/skill_market/quality_metrics.py # 复用：质量信号与扫描器样板（032 就绪前兜底）
├── app/services/skill_market/scoring.py    # 复用：compute_effect_score / 阈值 / is_low_quality 口径
├── app/main.py                             # 复用+扩展：on_event startup/shutdown 注册降级扫描器（仿 _QUALITY_SCANNER）
└── tests/test_trust_rating.py              # 新增：纯函数 + API + 门禁封顶 + 双人复核 + 扫描器测试

apps/admin-web/
├── src/views/skills/SkillsPage.vue         # 复用+扩展：资产行评级徽标与变更入口
└── src/views/trust-ratings/TrustRatingPage.vue  # 新增：评级管理视图（筛选/变更/历史/分布）
```

**Structure Decision**: 复用既有 monorepo 布局与「领域服务 + 路由 + admin-web 视图」的落位习惯（对照 016 `skill_market/` + `skill_monitoring.py` 路由），不新增子项目、不新增依赖。评级独立成 `trust_rating` 领域模块而非塞进 `governance/`：其输入跨 016/018/032 多个特性，落 `governance/` 会形成反向耦合；`TRUST_TO_AUTONOMY_CAP` 的租户覆盖集合与 `autonomy_matrix` 同构但独立命名，避免污染 001 的矩阵 CRUD 端点语义。

## Complexity Tracking

> 无 constitution 违规，无需复杂度论证。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | — | — |
