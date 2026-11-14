// apps/admin-web/eslint.config.js
// admin-web 专属 ESLint 配置（QF-040）
// 共享规则见 ../eslint.shared.config.js

import pluginVue from 'eslint-plugin-vue';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import prettier from 'eslint-config-prettier';
import { buildSharedConfig } from '../eslint.shared.config.js';

// pnpm isolates vue-eslint-parser, so the string form used by
// pluginVue.configs['flat/recommended'] fails to resolve. Resolve it explicitly
// through eslint-plugin-vue's own dependency tree.
const requireFromVue = createRequire(
  fileURLToPath(import.meta.resolve('eslint-plugin-vue')),
);
const vueESLintParser = requireFromVue('vue-eslint-parser');
// 依赖实例在本文件内解析（apps/ 不是 pnpm 项目，共享配置不能自己 import 裸包）。
const sharedConfig = buildSharedConfig({ js, tseslint, prettier });

export default [
  ...sharedConfig,
  ...pluginVue.configs['flat/recommended'],
  {
    files: ['**/*.vue'],
    languageOptions: {
      parser: vueESLintParser,
      parserOptions: {
        parser: tseslint.parser,
        ecmaVersion: 'latest',
        sourceType: 'module',
        extraFileExtensions: ['vue'],
      },
    },
  },
  {
    files: ['*.ts', '*.tsx'],
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
      },
    },
  },
  {
    rules: {
      // admin-web 专属规则（如有）
    },
  },
];
