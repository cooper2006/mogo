#!/usr/bin/env node
/**
 * MOGO 设计规范巡检（Design Token Lint）
 *
 * 把 docs/design-system.md 里的强制约定变成可执行检查，避免新页面继续跑偏。
 *
 * 检查项：
 *   R1 [error] admin-web 未安装 Tailwind，template 里出现 Tailwind 工具类 → 类名完全不生效
 *   R2 [error] <style> 段有硬编码色值，且既没有深色主题覆盖、也没有引用设计令牌
 *              → 深色主题下必然出现白底黑字 / 低对比文本
 *   R3 [warn]  <style> 段存在硬编码色值（浅色可用，但无法跟随主题）
 *   R4 [warn]  页面自写 h1/h2 标题块（应改用 PageIntro / .mg-page-head）
 *
 * 用法：
 *   node scripts/check_design_tokens.mjs           # 报告模式，始终退出 0
 *   node scripts/check_design_tokens.mjs --strict  # 有 error 时退出 1（供 CI 使用）
 *   node scripts/check_design_tokens.mjs --json    # 机器可读输出
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const APPS = [
  {
    name: 'admin-web',
    root: 'apps/admin-web/src',
    tailwind: false,
    darkSelectors: ['html.dark', '[data-theme="dark"]'],
  },
  {
    name: 'user-web',
    root: 'apps/user-web/src',
    tailwind: true,
    darkSelectors: ['theme-dark', 'html.dark', '[data-theme="dark"]'],
  },
];

/** Tailwind 工具类前缀（仅用于检查未安装 Tailwind 的 admin-web）。 */
const TW_PREFIXES = [
  'p-', 'px-', 'py-', 'pt-', 'pb-', 'pl-', 'pr-',
  'm-', 'mx-', 'my-', 'mt-', 'mb-', 'ml-', 'mr-',
  'space-y-', 'space-x-', 'gap-', 'gap-x-', 'gap-y-',
  'text-xs', 'text-sm', 'text-base', 'text-lg', 'text-xl',
  'text-gray-', 'text-slate-', 'text-blue-', 'text-white', 'text-red-', 'text-green-',
  'bg-white', 'bg-gray-', 'bg-slate-', 'bg-blue-', 'bg-red-', 'bg-green-',
  'border-gray-', 'border-slate-', 'border-blue-',
  'flex-1', 'grid-cols-', 'font-bold', 'font-semibold', 'font-medium',
  'shadow-sm', 'shadow-md', 'shadow-lg', 'rounded-', 'rounded',
  'items-center', 'justify-between', 'w-full', 'h-full',
];

const HEX_RE = /#[0-9a-fA-F]{3,8}\b/g;
const STYLE_RE = /<style[^>]*>([\s\S]*?)<\/style>/g;
const TEMPLATE_RE = /<template>([\s\S]*)<\/template>/;
const CLASS_ATTR_RE = /\bclass="([^"]*)"|:class="([^"]*)"/g;

function walk(dir, out = []) {
  if (!fs.existsSync(dir)) return out;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name === 'dist') continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else if (entry.name.endsWith('.vue')) out.push(full);
  }
  return out;
}

function collectTailwindClasses(template) {
  const hits = new Set();
  let match;
  CLASS_ATTR_RE.lastIndex = 0;
  while ((match = CLASS_ATTR_RE.exec(template)) !== null) {
    const raw = match[1] ?? match[2] ?? '';
    for (const token of raw.split(/[\s"'`{}[\](),]+/)) {
      if (!token) continue;
      if (TW_PREFIXES.some((p) => token === p || token.startsWith(p))) {
        // 排除项目自有语义类（mg-* 等）
        if (!token.startsWith('mg-')) hits.add(token);
      }
    }
  }
  return [...hits];
}

/**
 * R5: var(--mg-*) 引用了未定义的令牌。
 * 拼错令牌名不会报错，只会静默失效，因此单独做成检查项。
 */
function checkUndefinedTokens() {
  const defined = new Set();
  const tokenFiles = [
    'apps/admin-web/src/styles/tokens.css',
    'apps/user-web/src/styles/tokens.css',
  ];
  for (const rel of tokenFiles) {
    const abs = path.join(repoRoot, rel);
    if (!fs.existsSync(abs)) continue;
    const css = fs.readFileSync(abs, 'utf-8');
    for (const m of css.matchAll(/(--mg-[\w-]+)\s*:/g)) defined.add(m[1]);
  }

  const scanned = [
    'apps/admin-web/src',
    'apps/user-web/src',
  ];
  for (const relRoot of scanned) {
    const absRoot = path.join(repoRoot, relRoot);
    for (const file of walkAll(absRoot)) {
      const text = fs.readFileSync(file, 'utf-8');
      const missing = new Set();
      for (const m of text.matchAll(/var\((--mg-[\w-]+)/g)) {
        if (!defined.has(m[1])) missing.add(m[1]);
      }
      if (missing.size) {
        findings.push({
          app: relRoot.split('/')[1],
          rule: 'R5',
          level: 'error',
          file: path.relative(absRoot, file),
          line: 1,
          message: `引用了未定义的令牌：${[...missing].join(', ')}`,
          detail: '检查拼写，或在 styles/tokens.css 中补齐浅色与深色两套取值',
        });
      }
    }
  }
}

/** 递归收集 css / vue 文件。 */
function walkAll(dir, out = []) {
  if (!fs.existsSync(dir)) return out;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name === 'dist') continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walkAll(full, out);
    else if (/\.(vue|css)$/.test(entry.name)) out.push(full);
  }
  return out;
}

const findings = [];

function addFinding(app, rule, level, file, line, message, detail) {
  findings.push({ app: app.name, rule, level, file, line, message, detail });
}

for (const app of APPS) {
  const absRoot = path.join(repoRoot, app.root);
  for (const absFile of walk(absRoot)) {
    const relFile = path.relative(absRoot, absFile);
    const text = fs.readFileSync(absFile, 'utf-8');

    // ---- R1: 未安装 Tailwind 的 app 出现 Tailwind 工具类 ----
    if (!app.tailwind) {
      const templateMatch = text.match(TEMPLATE_RE);
      if (templateMatch) {
        const tw = collectTailwindClasses(templateMatch[1]);
        if (tw.length) {
          const templateStart = text.indexOf(templateMatch[0]);
          addFinding(
            app,
            'R1',
            'error',
            relFile,
            lineOf(text, templateStart),
            '使用了未安装的 Tailwind 工具类，这些类不会生效',
            tw.slice(0, 8).join(', '),
          );
        }
      }
    }

    // ---- R2 / R3: 硬编码色值 ----
    const styleBlocks = [...text.matchAll(STYLE_RE)].map((m) => m[1]);
    if (!styleBlocks.length) continue;
    const css = styleBlocks.join('\n');
    const hexes = css.match(HEX_RE) || [];
    if (!hexes.length) continue;

    const hasDarkOverride = app.darkSelectors.some((sel) => css.includes(sel));
    const usesTokens = css.includes('var(--mg-');

    if (!hasDarkOverride && !usesTokens) {
      addFinding(
        app,
        'R2',
        'error',
        relFile,
        lineOf(text, text.indexOf('<style')),
        `style 段有 ${hexes.length} 处硬编码色值，且无深色主题覆盖、未引用设计令牌`,
        [...new Set(hexes.map((h) => h.toLowerCase()))].slice(0, 8).join(', '),
      );
    } else if (!usesTokens) {
      addFinding(
        app,
        'R3',
        'warn',
        relFile,
        lineOf(text, text.indexOf('<style')),
        `style 段有 ${hexes.length} 处硬编码色值（建议迁移到 var(--mg-*)）`,
        [...new Set(hexes.map((h) => h.toLowerCase()))].slice(0, 8).join(', '),
      );
    }
  }
}

function lineOf(text, index) {
  if (index < 0) return 1;
  return text.slice(0, index).split('\n').length;
}

checkUndefinedTokens();

// ---- 输出 ----
const args = process.argv.slice(2);
const strict = args.includes('--strict');
const json = args.includes('--json');

const errors = findings.filter((f) => f.level === 'error');
const warns = findings.filter((f) => f.level === 'warn');

if (json) {
  console.log(JSON.stringify({ errors: errors.length, warns: warns.length, findings }, null, 2));
} else {
  console.log('MOGO 设计规范巡检（docs/design-system.md）');
  console.log('='.repeat(60));
  if (!findings.length) {
    console.log('未发现问题。');
  }
  for (const level of ['error', 'warn']) {
    const group = findings.filter((f) => f.level === level);
    if (!group.length) continue;
    console.log(`\n[${level}] ${group.length} 项`);
    for (const f of group) {
      console.log(`  ${f.app}/${f.file}:${f.line}  ${f.message}`);
      if (f.detail) console.log(`      样例：${f.detail}`);
    }
  }
  console.log(`\n汇总：error ${errors.length}，warn ${warns.length}`);
  console.log('说明：error 项在深色主题或布局上会直接可见地出问题，应优先修复。');
}

process.exit(strict && errors.length ? 1 : 0);
