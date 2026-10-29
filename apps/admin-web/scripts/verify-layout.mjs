#!/usr/bin/env node
/**
 * verify-layout.mjs — 用 Moli 浏览器（CDP）验证 admin-web 页面布局。
 *
 * 用法:
 *   node scripts/verify-layout.mjs              # 验证 5 个默认页面（需已构建 dist）
 *   node scripts/verify-layout.mjs /skills      # 只验证指定页面
 *   node scripts/verify-layout.mjs --no-moli    # 不自动启 moli（假设 9222 已在跑）
 *   node scripts/verify-layout.mjs --keep       # 验证后不清理 moli/静态服务器进程
 *
 * 流程: 自动拉起静态 dist 服务器(3200, 含 mock API + SPA fallback) + moli serve(9222)
 *       → connectOverCDP → 注入登录 → 逐页测量筛选栏横线 vs 内容区对齐/间距 → 输出 → 清理。
 *
 * 为什么用静态 dist 而不是 vite dev:
 *   Moli 的 CDP 网络栈加载子资源时请求头为空({})，vite dev 的模块协商因此对
 *   /@vite/client、/src/bootstrap.ts 返回 404，Vue 无法挂载。改用构建产物(静态
 *   文件)绕开该问题，且验证的正是用户实际看到的构建产物，更贴近真实。
 *
 * ★ Moli 布局刷新怪癖（务必知道，否则测量恒为 0）:
 *   Moli 的 --layout 虽会真实渲染像素（截图正常），但页面 JS 的 getBoundingClientRect
 *   在「布局被刷新前」一律返回全零，且元素被 Playwright 视为不可见。因此：
 *     1) waitForSelector 必须用 state:'attached'（默认 'visible' 会因零尺寸超时）；
 *     2) 读几何前必须先 page.screenshot() 强制 Moli 刷新一次布局，之后再 evaluate
 *        才能拿到真实坐标。moli serve --help 也印证："refresh layout once before
 *        running the script so geometry APIs can read it"。
 *   实测：截图前 filter/card rect 全为 {x:0,y:0,w:0,h:0}；截图后即返回真实值。
 *
 * 前置: 已构建 dist（apps/admin-web/dist 存在）；本机已装 Moli(/Users/cooper/moli/moli)。
 *       playwright 从全局 @playwright/cli 以绝对路径加载，不依赖项目 node_modules。
 */

import { spawn } from 'node:child_process';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const APP_DIR = path.resolve(__dirname, '..');
const DIST_DIR = path.join(APP_DIR, 'dist');
const MOLI_BIN = '/Users/cooper/moli/moli';
const MOLI_CDP = 'http://127.0.0.1:9222';
const STATIC_PORT = 3200;
const STATIC_URL = `http://127.0.0.1:${STATIC_PORT}/admin`;
const PLAYWRIGHT_INDEX = '/Users/cooper/.workbuddy-ai/binaries/node/versions/22.22.2-6/lib/node_modules/@playwright/cli/node_modules/playwright/index.mjs';

const args = process.argv.slice(2);
const onlyPages = args.filter((a) => a.startsWith('/'));
const autoMoli = !args.includes('--no-moli');
const keep = args.includes('--keep');

const NOW = '2026-10-29T20:00:00+08:00';

/* ---------- 1. 静态 dist 服务器（3200）：静态文件 + mock API + SPA fallback ---------- */
const MIME = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.png': 'image/png', '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.json': 'application/json', '.ico': 'image/x-icon' };

function startStaticServer() {
  const doc = (id, name, ext, size, status) => ({
    id, tenantId: 't-1', knowledgeBaseId: 'kb-1', name, description: '', originalFilename: name,
    fileExt: ext, mimeType: '', fileSize: size, storageType: 'local', storageBucket: '', storageKey: '',
    checksum: '', status: 'active', parseStatus: status, parseJobId: '', parseError: '', parseUpdatedAt: NOW,
    parsedMarkdownKey: '', parsedJsonKey: '', rawChunksKey: '', rawChunkCount: 0, ragChunksKey: '',
    ragChunkCount: 0, chunksKey: '', chunkCount: 0, chunkStatus: 'pending', indexStatus: 'pending',
    previewKey: '', previewMimeType: '', previewStatus: 'not_required', previewJobId: '', previewError: '',
    previewUpdatedAt: NOW, tags: [], createdBy: 'admin', createdByName: '系统管理员', updatedBy: 'admin',
    updatedByName: '系统管理员', createdAt: '2026-09-29T09:57:00+08:00', updatedAt: NOW, deletedAt: '',
    metadata: {}, downloadUrl: '', previewUrl: '',
  });
  const skill = {
    id: 'skill-expert-all', tenantId: 't-1', name: '内置技能合集（全量）',
    description: '一次性导入全部内置技能：文档处理、主题工厂及分析类技能。', scenario: '', type: 'expert_package',
    config: {}, enabled: true, createdAt: NOW, updatedAt: NOW,
    lifecycle: { authoringMode: 'platform', publicationStatus: 'published', publishedVersion: '1.0.0', publishedReleaseId: 'r-1', draftRevision: 0, hasUnpublishedChanges: false },
  };
  const userRow = {
    userId: 'u-1', name: '张伟', loginName: 'zhangwei', email: 'z@ex.com', mobile: '13800000000',
    status: 'active', departmentName: '研发部', quotaTokens: 1000000000, unlimited: false,
    usedTokens: 95000000, remainingTokens: 905000000, period: 'monthly', resetAt: NOW,
  };

  return http.createServer((req, res) => {
    const urlPath = decodeURIComponent(new URL(req.url, `http://127.0.0.1:${STATIC_PORT}`).pathname);
    // mock API（apiClient baseURL 是 /admin-api）
    const apiPath = urlPath.startsWith('/admin-api') ? urlPath.slice('/admin-api'.length) : urlPath;
    if (urlPath.startsWith('/api/v1/') || urlPath.startsWith('/admin-api/api/')) {
      res.setHeader('Content-Type', 'application/json; charset=utf-8');
      const json = (b, c = 200) => { res.statusCode = c; res.end(JSON.stringify(b)); };
      if (apiPath === '/api/v1/setup/status') return json({ completed: true, orgName: '系统', tenantId: 't-1', initializedAt: NOW, ready: true, platformAdminMissing: false, services: [], urls: {} });
      if (apiPath === '/api/v1/auth/me') return json({ name: '系统管理员', roleName: '组织管理员', orgName: '系统', username: 'admin', tenantId: 't-1' });
      if (apiPath === '/api/v1/skills' && req.method === 'GET') return json([skill]);
      if (apiPath === '/api/v1/portal/listings') return json({ items: [] });
      if (apiPath === '/api/v1/capabilities/list') return json({ items: [] });
      if (apiPath === '/api/v1/traffic-allocations/overview') return json({ orgPolicy: { totalTokens: 1e10, unlimited: false, period: 'monthly', timezone: 'Asia/Shanghai', status: 'active', usedTokens: 95000000, remainingTokens: 1e9, periodStartAt: NOW, resetAt: NOW }, defaultPolicy: { quotaTokens: 1e8, unlimited: false, period: 'monthly', status: 'active' }, assignedTokens: 1e8, assignedPolicyCount: 1 });
      if (apiPath === '/api/v1/traffic-allocations/users') return json([userRow]);
      if (apiPath === '/api/v1/traffic-allocations/teams') return json({ items: [], total: 0 });
      if (apiPath === '/api/v1/traffic-allocations/projects') return json({ items: [], total: 0 });
      if (apiPath === '/api/v1/traffic-allocations/logs') return json({ items: [], total: 0, page: 1, pageSize: 20 });
      if (apiPath === '/api/v1/directory/departments/tree') return json([]);
      if (apiPath === '/api/v1/knowledge/documents/stats') return json({ total: 1, indexed: 0, failed: 1, local: 1, oss: 0, totalSize: 144000 });
      if (apiPath === '/api/v1/knowledge/documents') return json({ data: [doc('d-1', 'intro-v4.pptx', 'pptx', 144000, 'failed')], total: 1, page: 1, pageSize: 10 });
      if (apiPath === '/api/v1/knowledge/directories/tree') return json([]);
      return json({});
    }
    // 静态文件（base /admin/）
    let filePath = urlPath.startsWith('/admin/') ? urlPath.slice('/admin'.length) : (urlPath === '/admin' ? '/' : urlPath);
    let file = path.join(DIST_DIR, filePath === '/' ? 'index.html' : filePath);
    if (!file.startsWith(DIST_DIR)) { res.statusCode = 403; return res.end(); }
    if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      file = path.join(DIST_DIR, 'index.html'); // SPA fallback
      if (!fs.existsSync(file)) { res.statusCode = 404; return res.end('dist 未构建'); }
    }
    res.setHeader('Content-Type', MIME[path.extname(file)] || 'application/octet-stream');
    fs.createReadStream(file).pipe(res);
  }).listen(STATIC_PORT, '127.0.0.1');
}

/* ---------- 2. 工具 ---------- */
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitPort(port, timeoutMs = 60000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try { const r = await fetch(`http://127.0.0.1:${port}/`); if (r.status < 500) return true; } catch { /* retry */ }
    await sleep(500);
  }
  return false;
}

/* ---------- 3. 页面与测量 ---------- */
const PAGES = [
  { name: 'Skill管理', path: '/skills', card: '.list-card', content: '.list-body', table: '.skill-grid' },
  { name: '工具与MCP', path: '/tools', card: '.list-card', content: '.list-body', table: '.n-data-table' },
  { name: '模型中心', path: '/models', card: '.list-card', content: '.list-body', table: '.n-data-table' },
  { name: '知识文档', path: '/knowledge/documents', card: null, content: '.list-body', table: '.n-data-table' },
  { name: '流量分配', path: '/organizations/traffic', card: '.list-card', content: '.table-shell', table: '.n-data-table' },
];

async function measure(page, cfg) {
  const data = await page.evaluate((cfg) => {
    const box = (sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: r.x, y: r.y, w: r.width, h: r.height };
    };
    return { filter: box('.list-filter-row'), card: cfg.card ? box(cfg.card) : null, content: box(cfg.content), table: box(cfg.table) };
  }, cfg);
  const f = data.filter;
  if (!f) return { ok: false, note: '未找到 .list-filter-row' };
  const out = { ok: true };
  const ref = data.card || data.content;
  if (ref) {
    out.overLeft = Math.round((ref.x - f.x) * 10) / 10;
    out.overRight = Math.round(((f.x + f.w) - (ref.x + ref.w)) * 10) / 10;
    out.横线 = `${Math.round(f.x)}~${Math.round(f.x + f.w)}`;
    out.参照 = `${Math.round(ref.x)}~${Math.round(ref.x + ref.w)}`;
  }
  if (data.content) { out.间距 = Math.round((data.content.y - (f.y + f.h)) * 10) / 10; out.内容左差 = Math.round((data.content.x - f.x) * 10) / 10; }
  return out;
}

/* ---------- 4. 主流程 ---------- */
async function main() {
  if (!fs.existsSync(DIST_DIR)) {
    console.error('✗ 未找到 dist（' + DIST_DIR + '）。请先执行 npm run build。');
    process.exit(1);
  }

  console.log('▶ 启动静态 dist 服务器(3200, 含 mock)…');
  const server = startStaticServer();
  await sleep(500);

  let moli = null;
  if (autoMoli) {
    console.log('▶ 启动 moli serve(9222)…');
    if (await waitPort(9222, 1500)) {
      console.log('  moli 已在运行，跳过启动');
    } else {
      moli = spawn(MOLI_BIN, ['serve', '--layout', '--resource'], { stdio: 'ignore' });
      const ok = await waitPort(9222);
      if (!ok) { console.error('✗ moli 启动失败'); server.close(); process.exit(1); }
      console.log('  moli 就绪 (Chrome CDP)');
    }
  }

  const { chromium } = await import('file://' + PLAYWRIGHT_INDEX);
  const browser = await chromium.connectOverCDP(MOLI_CDP);
  const ctx = browser.contexts()[0];
  const page = ctx.pages()[0] ?? await ctx.newPage();
  await page.setViewportSize({ width: 1568, height: 1017 });
  await page.addInitScript(() => {
    localStorage.setItem('askai-admin-auth', JSON.stringify({ token: 'mock-token', profile: { name: '系统管理员', roleName: '组织管理员', orgName: '系统', tenantId: 't-1' } }));
  });

  const targets = onlyPages.length ? PAGES.filter((p) => onlyPages.includes(p.path)) : PAGES;

  console.log('\n▶ 验证页面布局 (Moli via CDP, 构建产物 dist):\n');
  for (const cfg of targets) {
    const respLog = [];
    const onResp = (r) => { if (r.status() >= 400) respLog.push(`${r.status()} ${r.url()}`); };
    const onErr = (e) => respLog.push(`[pageerror] ${String(e).slice(0, 120)}`);
    page.on('response', onResp);
    page.on('pageerror', onErr);
    try {
      await page.goto(STATIC_URL + cfg.path, { waitUntil: 'domcontentloaded' });
      // Moli 在布局刷新前 getBoundingClientRect 返回全零，且元素被视为不可见，
      // 因此 waitForSelector 用 state:'attached'（只等存在），再截图强制刷新布局。
      await page.waitForSelector('.list-filter-row', { timeout: 15000, state: 'attached' });
      await page.waitForTimeout(400);
      await page.screenshot({ path: '/tmp/_moli_layout_refresh.png' }); // 强制 Moli 刷新布局，几何 API 才返回真实值
      await page.waitForTimeout(200);
      const m = await measure(page, cfg);
      console.log(`  ${cfg.name} (${cfg.path})`);
      if (!m.ok) { console.log('    ✗ ' + m.note); continue; }
      console.log(`    横线 ${m.横线} | 参照 ${m.参照} | 左超界 ${m.overLeft}px 右超界 ${m.overRight}px`);
      console.log(`    内容左差 ${m.内容左差}px | 横线→内容区间距 ${m.间距}px`);
      const alignOk = m.overLeft >= -1 && m.overRight >= -1;
      console.log(`    ${alignOk ? '✓ 对齐' : '✗ 需检查'}${m.间距 >= 16 ? ' ✓ 间距足够' : ' ⚠ 间距偏小'}`);
      console.log(`    ${Math.abs(m.内容左差) <= 1 ? '✓' : 'ℹ'} 内容左差 ${m.内容左差}px${Math.abs(m.内容左差) <= 1 ? '' : '（筛选栏负外边距拉出到卡片边缘，符合预期）'}`);
      if (respLog.length) console.log('    ⚠ 4xx/5xx/pageerror: ' + respLog.slice(0, 8).join(' | '));
    } catch (e) {
      console.log(`  ${cfg.name}: ✗ ${e.message.slice(0, 80)}`);
    } finally {
      page.off('response', onResp);
      page.off('pageerror', onErr);
    }
  }

  await browser.close();
  if (!keep) { server.close(); if (autoMoli && moli) moli.kill(); }
  console.log('\n完成。' + (keep ? ' (--keep 保留进程)' : ''));
  process.exit(0);
}

main().catch((e) => { console.error(e); process.exit(1); });
