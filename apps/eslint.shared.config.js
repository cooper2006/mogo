// apps/eslint.shared.config.js
// 共享 ESLint 配置（QF-040 / QF-042）
//
// 两个前端应用（user-web / admin-web）通过 extends 复用此配置，
// 消除规则集漂移。安全隐患相关规则在此集中定义。

import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import prettier from 'eslint-config-prettier';

/** @type {import('eslint').Linter.Config[]} */
export const sharedConfig = [
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.ts', '**/*.tsx'],
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
      // 基础规则
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      'vue/multi-word-component-names': 'off',
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
      '@typescript-eslint/no-explicit-any': 'warn',

      // 复杂度控制（QF-054：门禁级别）
      complexity: ['error', { max: 15 }],
      'max-depth': ['warn', 4],
      'max-params': ['warn', 6],
      'max-lines': ['warn', { max: 2000, skipBlankLines: true, skipComments: true }],

      // 安全隐患类别（QF-042）
      'no-eval': 'error',
      'no-implied-eval': 'error',
      'no-script-url': 'error',
      'no-alert': 'warn',
      'no-new-func': 'error',
      'no-useless-escape': 'warn',
      'no-undef': 'error',
      'no-unused-vars': 'off', // 由 @typescript-eslint/no-unused-vars 覆盖
    },
  },
  prettier,
];
