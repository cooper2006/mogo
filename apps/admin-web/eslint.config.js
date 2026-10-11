// apps/admin-web/eslint.config.js
// admin-web 专属 ESLint 配置（QF-040）
// 共享规则见 ../eslint.shared.config.js

import pluginVue from 'eslint-plugin-vue';
import { sharedConfig } from '../eslint.shared.config.js';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

// pnpm isolates vue-eslint-parser, so the string form used by
// pluginVue.configs['flat/recommended'] fails to resolve. Resolve it explicitly
// through eslint-plugin-vue's own dependency tree.
const requireFromVue = createRequire(
  fileURLToPath(import.meta.resolve('eslint-plugin-vue')),
);
const vueESLintParser = requireFromVue('vue-eslint-parser');
const tseslint = (await import('typescript-eslint')).default;

export default [
  ...sharedConfig,
  ...pluginVue.configs['flat/recommended'],
  {
    files: ['*.vue'],
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
