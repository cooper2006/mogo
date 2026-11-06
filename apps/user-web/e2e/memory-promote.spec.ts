/**
 * T031 真实浏览器 E2E —— user-web「我的记忆」提升申请流程。
 *
 * 说明：本文件为可执行的 Playwright 规格，但**无法在当前无人浏览器 / 无凭据的环境
 * 运行**（依赖 chat-api + user-web 真实起服、登录态、目标部门可见性）。这里只落地
 * 用例脚本与步骤，真实执行见同目录 README.md 的「执行方式」。
 *
 * 覆盖链路：创建个人记忆 → 申请提升为部门记忆（pending）→ 校验回显 promotion_status。
 */
import { test, expect, type Page } from '@playwright/test';

const BASE = process.env.USER_WEB_BASE || 'http://localhost:5173';
// 目标部门（须对登录用户可见，否则 403 department_not_visible）
const TARGET_DEPARTMENT = process.env.E2E_DEPARTMENT_ID || 'd1';

async function loginAsUser(page: Page, username: string) {
  // 实际环境走 SSO / 账号密码；此处用环境变量注入的会话或 token 兜底。
  await page.goto(`${BASE}/login`);
  await page.fill('input[name="username"]', username);
  await page.fill('input[name="password"]', process.env.E2E_USER_PASSWORD || '');
  await page.click('button[type="submit"]');
  await page.waitForURL('**/memories**');
}

test.describe('记忆提升申请（T031 / T035）', () => {
  test('创建个人记忆并发起部门提升申请', async ({ page }) => {
    await loginAsUser(page, process.env.E2E_USER || 'u1');

    // 1) 进入「我的记忆」
    await page.goto(`${BASE}/memories`);
    await expect(page.getByTestId('my-memories-page')).toBeVisible();

    // 2) 新建一条个人记忆
    await page.getByRole('button', { name: /新建记忆|新建/ }).click();
    const content = `E2E 冒烟记忆 ${Date.now()}`;
    await page.fill('textarea[name="content"]', content);
    await page.getByRole('button', { name: /保存|创建/ }).click();
    await expect(page.getByText(content)).toBeVisible();

    // 3) 对该记忆发起「提升为部门」申请
    const row = page.locator('[data-testid="memory-row"]', { hasText: content }).first();
    await row.getByRole('button', { name: /提升|申请提升/ }).click();
    await page.fill('input[name="department_id"]', TARGET_DEPARTMENT);
    await page.getByRole('button', { name: /提交申请|申请/ }).click();

    // 4) 校验回显：状态进入 pending，且不可被普通用户直接提升
    await expect(row.getByTestId('promotion-status')).toHaveText('pending');
  });

  test('非部门可见范围时申请被拒绝', async ({ page }) => {
    await loginAsUser(page, process.env.E2E_USER || 'u1');
    await page.goto(`${BASE}/memories`);
    const content = `E2E 越权记忆 ${Date.now()}`;
    await page.getByRole('button', { name: /新建记忆|新建/ }).click();
    await page.fill('textarea[name="content"]', content);
    await page.getByRole('button', { name: /保存|创建/ }).click();

    const row = page.locator('[data-testid="memory-row"]', { hasText: content }).first();
    await row.getByRole('button', { name: /提升|申请提升/ }).click();
    // 传入一个对当前用户不可见的部门 → 期望 403 department_not_visible
    await page.fill('input[name="department_id"]', 'unreachable-dept');
    await page.getByRole('button', { name: /提交申请|申请/ }).click();
    await expect(page.getByText(/department_not_visible|无权限/)).toBeVisible();
  });
});
