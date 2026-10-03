import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import pluginVue from 'eslint-plugin-vue';
import prettier from 'eslint-config-prettier';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

// pnpm isolates vue-eslint-parser, so the string form used by
// pluginVue.configs['flat/recommended'] fails to resolve. Resolve it explicitly
// through eslint-plugin-vue's own dependency tree.
const requireFromVue = createRequire(
  fileURLToPath(import.meta.resolve('eslint-plugin-vue')),
);
const vueESLintParser = requireFromVue('vue-eslint-parser');

export default [
  js.configs.recommended,
  ...tseslint.configs.recommended,
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
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      'vue/multi-word-component-names': 'off',
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
      '@typescript-eslint/no-explicit-any': 'warn',
    },
  },
  prettier,
];
