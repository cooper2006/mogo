# 真实浏览器 E2E（T031）

本目录下的 `*.spec.ts` 为 Playwright 端到端用例，覆盖 admin 端记忆治理：
待审批队列的通过 / 驳回（T035），以及离职用户记忆显式失效（T037）。
**当前仓库无浏览器、无 admin 凭据、无起服环境，无法自动执行**。

## 前置条件
1. 安装依赖：`cd apps/admin-web && pnpm add -D @playwright/test`，并执行 `npx playwright install`。
2. 同时起服：`admin-api`（:8001）与 `admin-web`（:5174）。
3. 准备一个 **full_access_admin** 账号（用于 `memory:approve` 与 offboard 端点）；
   另需一个可被 offboard 的普通用户 `u-offboard`（其记忆应已存在）。

## 执行
```bash
# 在 apps/admin-web 下
export ADMIN_WEB_BASE=http://localhost:5174
export E2E_ADMIN=admin
export E2E_ADMIN_PASSWORD='******'
export E2E_OFFBOARD_USER=u-offboard
npx playwright test e2e/memories-governance.spec.ts
```

## 关联用例
- `apps/user-web/e2e/memory-promote.spec.ts`：用户端发起提升申请。
- 后端契约见 `apps/admin-web/src/api/memories.ts` 的 `fetchAdminPendingApprovals` /
  `approveMemoryPromotion` / `rejectMemoryPromotion` / `offboardUserMemories`。

## 通过判据
- 待审批 tab 至少出现一条 `pending` 记忆；通过后该记忆进入「部门」范围且
  `promotion_status=approved`；驳回后从待审批列表消失（`rejected`）。
- offboard 后，被失效用户的个人/本主项目记忆退出普通检索（404 / 列表空）。
