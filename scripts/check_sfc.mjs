#!/usr/bin/env node
/**
 * SFC 单文件编译校验（前端改动的轻量验收，替代全量 `vite build`）。
 *
 * 为什么用它：本仓库前端全量构建在本机 >10min，spec 里各特性的前端验收统一写成
 * 「用 `@vue/compiler-sfc` 编译改动的 .vue 通过」。本脚本把这条约定固化成一条命令，
 * 逐文件跑 parse → compileScript → compileTemplate → compileStyle。
 *
 * 依赖：`@vue/compiler-sfc`（版本必须与应用里的 `vue` 一致，admin-web 为 3.4.38）。
 * 仓库内 `apps/<app>/node_modules` 可能是残缺安装，因此支持从外部目录借依赖：
 *
 *   # 1) 项目内已装（正常情况）
 *   node scripts/check_sfc.mjs apps/admin-web/src/views/tools/ToolEditPage.vue
 *
 *   # 2) 项目未装：装到任意隔离目录，用 NODE_PATH 指过去
 *   npm install --prefix /tmp/sfc @vue/compiler-sfc@3.4.38
 *   NODE_PATH=/tmp/sfc/node_modules node scripts/check_sfc.mjs <files...>
 *
 *   # 3) 不传文件时，默认校验 git 工作区里改动/新增的 .vue
 *   node scripts/check_sfc.mjs
 *
 * 退出码：0 全部通过；1 有失败；2 用法或依赖问题。
 */
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';

const require = createRequire(import.meta.url);

function loadCompiler() {
  try {
    return require('@vue/compiler-sfc');
  } catch {
    console.error(
      [
        '找不到 @vue/compiler-sfc。',
        '  方式一：在对应应用下 `npm i` 后重试；',
        '  方式二：装到隔离目录并用 NODE_PATH 指向它，例如',
        '    npm install --prefix /tmp/sfc @vue/compiler-sfc@3.4.38',
        '    NODE_PATH=/tmp/sfc/node_modules node scripts/check_sfc.mjs <files...>',
      ].join('\n'),
    );
    process.exit(2);
  }
}

/** 未显式传文件时，取工作区里改动/新增的 .vue（含未跟踪）。 */
function changedVueFiles() {
  const output = execFileSync('git', ['status', '--porcelain', '--', '*.vue'], { encoding: 'utf8' });
  return output
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => line.replace(/^[A-Z?!]{1,2}\s+/, ''))
    .map((file) => file.replace(/^"|"$/g, ''))
    .filter((file) => file.endsWith('.vue'));
}

const { parse, compileScript, compileTemplate, compileStyle, version } = loadCompiler();

const args = process.argv.slice(2);
const files = args.length ? args : changedVueFiles();
if (!files.length) {
  console.error('没有待校验的 .vue 文件（显式传路径，或在有 .vue 改动的工作区运行）。');
  process.exit(2);
}

console.log(`@vue/compiler-sfc ${version}\n`);

let failed = 0;
for (const file of files) {
  const source = readFileSync(path.resolve(file), 'utf8');
  const id = `sfc-${Buffer.from(file).toString('hex').slice(0, 8)}`;
  const problems = [];

  const { descriptor, errors } = parse(source, { filename: file });
  for (const error of errors) problems.push(`parse: ${error.message || error}`);

  if (descriptor.script || descriptor.scriptSetup) {
    try {
      compileScript(descriptor, { id });
    } catch (error) {
      problems.push(`script: ${error.message}`);
    }
  }

  if (descriptor.template) {
    const result = compileTemplate({
      source: descriptor.template.content,
      filename: file,
      id,
      compilerOptions: { expressionPlugins: ['typescript'] },
    });
    for (const error of result.errors) problems.push(`template: ${error.message || error}`);
  }

  descriptor.styles.forEach((style, index) => {
    const result = compileStyle({ source: style.content, filename: file, id, scoped: style.scoped });
    for (const error of result.errors) problems.push(`style[${index}]: ${error.message || error}`);
  });

  if (problems.length) {
    failed += 1;
    console.log(`FAIL ${file}`);
    for (const problem of problems) console.log(`     - ${problem}`);
  } else {
    console.log(`ok   ${file}`);
  }
}

console.log(`\n${files.length - failed}/${files.length} SFC 编译通过`);
process.exit(failed ? 1 : 0);
