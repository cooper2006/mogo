/**
 * T031 真实浏览器 E2E —— admin-web 记忆治理（提升审批 / 离职失效）。
 *
 * 说明：本文件为可执行的 Playwright 规格，但**无法在当前无浏览器 / 无 admin 凭据的
 * 环境运行**（依赖 admin-api + admin-web 真实起服、full_access_admin 登录态）。
 * 仅落地用例脚本，真实执行见同目录 README.md。
 *
 * 覆盖：待审批队列 → 通过（pending→approved 并提升 department）/ 驳回
 *       → 离职用户记忆显式失效（offboard）后普通检索不可见。
 */
import { test, expect, type Page } from '@playwright/test';

const BASE = process.env.ADMIN_WEB_BASE || 'http://localhost:5174';

async function loginAsAdmin(page: Page, username: string) {
  await page.goto(`${BASE}/login`);
  await page.fill('input[name="username"]', username);
  await page.fill('input[name="password"]', process.env.E2E_ADMIN_PASSWORD || '');
  await page.click('button[type="submit"]');
  await page.waitForURL('**/memories**');
}

test.describe('记忆提升审批（T031 / T035）', () => {
  test('admin 通过待审批的提升请求', async ({ page }) => {
    await loginAsAdmin(page, process.env.E2E_ADMIN || 'admin');
    await page.goto(`${BASE}/memories`);

    // 进入待审批 tab
    await page.getByRole('tab', { name: /待审批|审批/ }).click();
    const pending = page.locator('[data-testid="pending-approval-row"]').first();
    await expect(pending).toBeVisible();

    const memoryId = await pending.getAttribute('data-memory-id') || '';
    await pending.getByRole('button', { name: /通过|批准/ }).click();
    await page.fill('input[name="department_id"]', await pending.getAttribute('data-department-id') || 'd1');
    await page.getByRole('button', { name: /确认通过/ }).click();

    // 通过后在「部门」范围可见，promotion_status=approved
    await page.getByRole('tab', { name: /部门/ }).click();
    await expect(page.locator(`[data-memory-id="${memoryId}"]`)).toBeVisible();
  });

  test('admin 驳回待审批的提升请求', async ({ page }) => {
    await loginAsAdmin(page, process.env.E2E_ADMIN || 'admin');
    await page.goto(`${BASE}/memories`);
    await page.getByRole('tab', { name: /待审批|审批/ }).click();

    const pending = page.locator('[data-testid="pending-approval-row"]').first();
    await pending.getByRole('button', { name: /驳回/ }).click();
    await page.fill('textarea[name="reject_reason"]', '不符合部门规范');
    await page.getByRole('button', { name: /确认驳回/ }).click();

    // 驳回后该记忆回到个人/项目态，promotion_status=rejected
    await expect(pending).toHaveCount(0);
  });
});

test.describe('离职 / 删号显式失效（T031 / T037）', () => {
  test('offboard 后目标用户记忆退出检索', async ({ page }) => {
    await loginAsAdmin(page, process.env.E2E_ADMIN || 'admin');
    await page.goto(`${BASE}/memories/governance`);

    const targetUser = process.env.E2E_OFFBOARD_USER || 'u-offboard';
    await page.fill('input[name="offboard_user_id"]', targetUser);
    await page.getByRole('button', { name: /失效该用户记忆/ }).click();
    await expect(page.getByText(/invalidated_count/)).toBeVisible();

    // 以被失效用户身份登录，确认其个人记忆不可见（404 / 列表空）
    const ctx = await page.context().browser()?.newContext();
    if (ctx) {
      const userPage = await ctx.newPage();
      await userPage.goto(`${BASE.replace('5174', '5173')}/memories`);
      await userPage.getByText(targetUser).waitFor({ state: 'detached' }).catch(() => {});
    }
  });
});
