# Implementation Plan: 配额可发现性与跨服务口径

**Branch**: `047-quota-discoverability` | **Date**: 2026-10-31 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/047-quota-discoverability/spec.md`；批次来源 `specs/035-cost-attribution/review-2026-10-30-dimension-source-audit.md` §7.2

**Note**: 本计划对应 035 §7.2 的**批次 A（可发现性，纯前端 + 一处路由）**与**批次 B 的 B1/B2（跨服务口径）**，以及**批次 C（文档验收）**。B0（`points_unlimited` 默认值）已并入 042 `tasks.md` T024；B4（网关补 `user_id`）属 046 T011/T012，本特性不重复。

## Summary

042 的配额引擎已实现，问题在**找不到、指错、看不见、两副本漂移**。四条主线：① admin-web 新增独立菜单「项目管理」（`/projects`），项目只读、配额可配；② 修深链——`?open=quota` 指向项目配额、新增 `?open=tenant` 指向租户额度，告警"去配置"按 `scope_type` 分流；③ 驾驶舱补「配额异常」卡片，消费后端已返回的 `quotaAnomalies`；④ 加跨服务一致性测试并统一 tz 语义，锁死两份 `quota_policy.py` 副本。

## Technical Context

**Language/Version**: TypeScript 5（admin-web，Vue 3 + naive-ui）；Python 3.11+（chat-api / admin-api）

**Primary Dependencies**: 既有 `apps/admin-web/src/views/organizations/TrafficAllocationsPage.vue`、`views/dashboard/DashboardPage.vue`、`views/models/ModelsPage.vue`、`api/traffic-allocations.ts`、`useMenuOptions.ts`（菜单由路由 `meta.title` 派生）；后端 `api/routes/traffic_allocations.py`、`api/routes/dashboard.py`、两份 `core/quota_policy.py`。**零新第三方依赖**

**Storage**: 只读既有集合（`user_quota_policies` / `quota_alert_events` / `projects`）；**本特性不新增集合、不新增字段**

**Testing**: 前端 `node scripts/check_sfc.mjs`（SFC 编译）+ `vue-tsc --noEmit`；后端新增 `tests/test_quota_consistency.py`（跨服务一致性）+ 既有配额测试回归

**Target Platform**: admin-web（浏览器）+ 双后端同栈部署

**Project Type**: web-app（前端为主）+ 后端一致性加固

**Performance Goals**: 项目管理页首屏一次请求（列表 + 用量合并返回，不 N+1）；一致性测试单次 < 5s

**Constraints**: 不改 `scope_type` 枚举与任何既有字段名；不改 `ANOMALY_STATUSES`；旧深链 `/organizations/traffic?open=quota` 不得 404

**Scale/Scope**: 前端 4 个文件（1 新建页面 + 3 修改）+ 1 个路由/菜单注册；后端 2 个文件（tz 统一）+ 1 个新测试；文档 2 处（042 spec 落点索引、双向声明）

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Specification-First**: ✅ 本 spec 先于实现；042 的既有实现作为"被扩展对象"在 FR-009/FR-010 显式声明。
- **II. Enterprise Production Readiness**: ✅ 所有改动向后兼容（旧深链保留、字段名不变、枚举不变）；一致性测试作为 CI 门禁防止单侧漂移。
- **III. Security and Data Protection**: ✅ 项目管理页只读，不新增写权限面；深链越权时明确提示而非静默降级。
- **IV. Cross-Platform and i18n**: ✅ 新文案走 `t()` 中文 key 回退；「团队」→「部门」是文案层替换，机器标识符不动。
- **V. Observability and Simplicity**: ✅ 复用 008 诚实占位纪律（`available=false` 显示 `reason`，不填零）；不新建推送通道。

## Project Structure

### Documentation (this feature)

```text
specs/047-quota-discoverability/
├── spec.md
├── plan.md              # 本文件
├── tasks.md
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
apps/admin-web/src/
├── views/projects/ProjectsPage.vue          # 【新】项目管理页（列表 + 用量/成本 + 项目额度）
├── router/…（或 routes 定义处）              # 【改】注册 /projects，meta.title = 项目管理（菜单自动派生）
├── views/organizations/TrafficAllocationsPage.vue  # 【改】旧入口改跳转；弹窗只留租户额度；文案「团队」→「部门」
├── views/dashboard/DashboardPage.vue        # 【改】新增「配额异常」卡片（消费 quotaAnomalies）
├── views/models/ModelsPage.vue              # 【改】?open=quota 分流；租户告警改 ?open=tenant
└── api/traffic-allocations.ts               # 【改】项目相关调用改指向 /projects 数据源（046 改名后）

services/chat-api/app/core/quota_policy.py   # 【改】tz 语义统一 + 文件头注明选择
services/admin-api/app/core/quota_policy.py  # 【改】同上（两侧必须一致）
services/*/tests/test_quota_consistency.py   # 【新】同内容 fixture 跨服务逐字段比对
```

**Structure Decision**: 前端沿用既有目录（新页面进 `views/projects/`，与 `views/organizations/` 平级）；菜单不单独维护，靠路由 `meta.title` 自动进侧边栏。后端只动 tz 与新增测试，不重构 `quota_policy`。

## 批次映射（035 §7.2 → 本特性）

| 035 编号 | 任务 | 落点 |
|---|---|---|
| A1 | 独立菜单「项目管理」 | FR-001，`ProjectsPage.vue` + 路由 |
| A2 | 修深链 `?open=quota` / 新增 `?open=tenant` | FR-002，`TrafficAllocationsPage.vue` 的 `consumeOpenQuotaQuery()` + `ModelsPage.vue` |
| A3 | 项目空态引导 | FR-003，`ProjectsPage.vue` 空态分支 |
| A4 | 驾驶舱配额异常卡片 | FR-004，`DashboardPage.vue` |
| A5 | 旧入口改跳转 | FR-005，`TrafficAllocationsPage.vue:25` 按钮 |
| — | 「团队」字样清理 | FR-006（文案改「部门」，标识符保留） |
| B1 | 跨服务一致性测试 | FR-007 |
| B2 | 统一 tz 语义 | FR-008 |
| C1 | 补 042 T023（SFC + 手工联调） | tasks 内收尾项 |
| C2 | 042 实现落点索引 | FR-009 |
| C3 | 与 035/046 双向声明 | FR-010 |

## 依赖与顺序

- **必须等 046 的集合改名（T004）完成**才能做 A1——新页面读的是 `projects`，不是 `desktop_projects`。
- **A5 依赖 A1**（旧入口要跳到新页面）。
- **A2 与 A1 同批**：深链目标就是新页面，分开做会出现"跳到不存在的页面"。
- **B1/B2 独立**，可与 A 批并行（纯后端 + 测试）。
- 048（业务线删除）与 047 共享 `DashboardPage.vue` 与 `dashboard.py`，但**改的是不同位置**（048 删维度段，047 加告警卡片）——可并行，注意同一文件冲突。

## Complexity Tracking

| 需要说明的点 | 为什么必须这样 | 更简单的替代为何不可行 |
|---|---|---|
| 新建独立页面而非改造弹窗 | 项目列表要展示用量/成本/额度三块，弹窗装不下；且菜单名才是可发现性的根因 | 在流量分配页加一级 tab → 菜单名仍是"流量分配"，语义不关联 |
| 一致性测试锁死两份副本 | 两服务分属不同进程，无法共享代码；副本已开始漂移（长度与 tz 都不同） | 抽公共包要动两个服务的依赖布局，跨特性改动，本期不做 |
| 旧深链保留兼容 | 已有收藏/文档引用，404 会直接打断用户 | 直接改路径 → 老链接失效，且告警"去配置"里还写死着旧参数 |
