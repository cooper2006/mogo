# 真实浏览器 E2E（T031）

本目录下的 `*.spec.ts` 为 Playwright 端到端用例，覆盖「我的记忆 → 申请提升为部门记忆」
（T035 用户侧链路）。**当前仓库无浏览器、无登录凭据、无起服环境，无法自动执行**；
执行需人工在具备以下条件的环境进行：

## 前置条件
1. 安装依赖：`cd apps/user-web && pnpm add -D @playwright/test`，并执行 `npx playwright install`。
2. 同时起服：`chat-api`（:8000）与 `user-web`（:5173，vite 代理 `/askai-api` → chat-api）。
3. 准备一个**普通终端用户**账号（非 full_access_admin），且该用户至少可见一个部门
   （用于 `department_id` 入参，否则预期 403 `department_not_visible`）。

## 执行
```bash
# 在 apps/user-web 下
export USER_WEB_BASE=http://localhost:5173
export E2E_USER=u1
export E2E_USER_PASSWORD='******'
export E2E_DEPARTMENT_ID=d1
npx playwright test e2e/memory-promote.spec.ts
```

## 关联用例
- `apps/admin-web/e2e/memories-governance.spec.ts`：admin 端「待审批 → 通过/驳回」与
  T037 离职失效流程。
- 后端契约：`apps/user-web/src/api/memories.ts::requestPromoteMemory`、
  `apps/admin-web/src/api/memories.ts::fetchAdminPendingApprovals / approveMemoryPromotion /
  rejectMemoryPromotion / offboardUserMemories`。

## 通过判据（SC-11 用户侧交互）
- 个人记忆创建后出现在「我的记忆」列表；
- 点击「提升」并选择可见部门后，记忆 `promotion_status` 回显 `pending`；
- 传入不可见部门时，前端收到 403（文案「无权限 / 内容不存在」）。
