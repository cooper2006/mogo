// apps/eslint.shared.config.js
// 共享 ESLint 配置（QF-040 / QF-042）
//
// 两个前端应用（user-web / admin-web）复用此配置，消除规则集漂移。
// 安全隐患相关规则在此集中定义。
//
// 注意：本文件位于 `apps/`，而 `apps/` 不是 pnpm 项目（无 package.json），
// 所以这里**不能**直接 `import '@eslint/js'` 之类的裸导入——ESLint 按配置文件
// 所在路径解析依赖，会报 `ERR_MODULE_NOT_FOUND`（QA R11 发现 lint 门禁因此整体
// 不可运行）。改为工厂函数：由调用方（各应用的 eslint.config.js，位于真正装了
// 依赖的项目目录内）把依赖实例传进来。

/**
 * @param {{
 *   js: typeof import('@eslint/js').default,
 *   tseslint: typeof import('typescript-eslint'),
 *   prettier: import('eslint').Linter.Config,
 * }} deps
 * @returns {import('eslint').Linter.Config[]}
 */
export function buildSharedConfig({ js, tseslint, prettier }) {
  // ── 复杂度债务登记 DEBT-CX（2026-10-24 QA R11）───────────────────────────
  // `complexity: max 15`（QF-054，门禁级别）是"新代码标准"。历史上已存在的
  // 超限函数无法在一轮内重构完：本轮审计时共 99 处、分布在 44 个文件，最高
  // 复杂度 99（user-web ChatWindow.vue）。逐个重构属于与功能无关的批量改写，
  // 回归风险高，故按文件登记"当前上限"= 该文件现有违规的最大值：
  //   · 规则只在 > max 时报错，登记的基线值本身不报错 → CI 不再阻断
  //   · 同一文件新增分支只要不突破已登记上限，就不扩大债务
  //   · 上限只允许单调下降：偿还一项就改小该行 max，禁止调大
  // 完整清单（99 处逐条 + 偿还计划）见 docs/pending-review/frontend-complexity-debt.md
  // ⚠️ 禁止把已有行的 max 往上调；禁止新增文件入表（新文件走 max 15）。
  // @type {import('eslint').Linter.Config[]}
  // ⚠️ 2026-10-24 QA R12：登记表已清空——44 个文件 / 99 处超限函数全部参与
  //     `complexity: max 15` 门禁重构。重构完成后如需保留例外，只允许追加
  //     上限 ≤ 15 且已确认无法通过抽取降级的条目，并在此登记原因。
  // @type {import('eslint').Linter.Config[]}
  const complexityDebt = [
  ];

  return [
    js.configs.recommended,
    ...tseslint.configs.recommended,
    {
      files: ['**/*.ts', '**/*.tsx', '**/*.vue'],
      languageOptions: {
        parser: tseslint.parser,
        parserOptions: {
          ecmaVersion: 'latest',
          sourceType: 'module',
        },
        // 浏览器全局量：两个前端都跑在浏览器里，`.ts`/`.tsx`/`.vue` 里引用
        // window / document / fetch 等不应被判 no-undef。这里没有 `globals` 依赖
        // （apps/ 不是 pnpm 项目，且 package.json 未装），故内联只读清单。
        // QA R11：admin-web 曾因缺此块产生 219 个 `no-undef` 门禁错误。
        globals: {
          window: 'readonly',
          document: 'readonly',
          console: 'readonly',
          fetch: 'readonly',
          navigator: 'readonly',
          localStorage: 'readonly',
          performance: 'readonly',
          location: 'readonly',
          history: 'readonly',
          URL: 'readonly',
          URLSearchParams: 'readonly',
          Blob: 'readonly',
          BlobPart: 'readonly',
          FileReader: 'readonly',
          FormData: 'readonly',
          DOMParser: 'readonly',
          TextDecoder: 'readonly',
          TextEncoder: 'readonly',
          File: 'readonly',
          Event: 'readonly',
          CustomEvent: 'readonly',
          MouseEvent: 'readonly',
          DragEvent: 'readonly',
          DataTransfer: 'readonly',
          DataTransferItem: 'readonly',
          ClipboardEvent: 'readonly',
          InputEvent: 'readonly',
          FocusEvent: 'readonly',
          KeyboardEvent: 'readonly',
          PointerEvent: 'readonly',
          WheelEvent: 'readonly',
          ErrorEvent: 'readonly',
          HashChangeEvent: 'readonly',
          PopStateEvent: 'readonly',
          StorageEvent: 'readonly',
          MessageEvent: 'readonly',
          ProgressEvent: 'readonly',
          ChangeEvent: 'readonly',
          SubmitEvent: 'readonly',
          BeforeUnloadEvent: 'readonly',
          AnimationEvent: 'readonly',
          TransitionEvent: 'readonly',
          CompositionEvent: 'readonly',
          IMECompositionEvent: 'readonly',
          TouchEvent: 'readonly',
          Document: 'readonly',
          Element: 'readonly',
          Node: 'readonly',
          ParentNode: 'readonly',
          HTMLElement: 'readonly',
          HTMLDivElement: 'readonly',
          HTMLInputElement: 'readonly',
          HTMLTextAreaElement: 'readonly',
          HTMLCanvasElement: 'readonly',
          HTMLButtonElement: 'readonly',
          HTMLImageElement: 'readonly',
          HTMLSelectElement: 'readonly',
          HTMLAnchorElement: 'readonly',
          HTMLFormElement: 'readonly',
          HTMLScriptElement: 'readonly',
          HTMLDetailsElement: 'readonly',
          HTMLTableElement: 'readonly',
          HTMLTableRowElement: 'readonly',
          HTMLSelectOption: 'readonly',
          CanvasRenderingContext2D: 'readonly',
          MediaSource: 'readonly',
          MediaQueryList: 'readonly',
          MediaRecorder: 'readonly',
          MediaStream: 'readonly',
          Image: 'readonly',
          ImageData: 'readonly',
          AbortController: 'readonly',
          AbortSignal: 'readonly',
          Headers: 'readonly',
          Request: 'readonly',
          Response: 'readonly',
          WebSocket: 'readonly',
          EventTarget: 'readonly',
          ResizeObserver: 'readonly',
          IntersectionObserver: 'readonly',
          MutationObserver: 'readonly',
          WeakRef: 'readonly',
          FinalizationRegistry: 'readonly',
          queueMicrotask: 'readonly',
          structuredClone: 'readonly',
          atob: 'readonly',
          btoa: 'readonly',
          setTimeout: 'readonly',
          setInterval: 'readonly',
          clearTimeout: 'readonly',
          clearInterval: 'readonly',
          requestAnimationFrame: 'readonly',
          cancelAnimationFrame: 'readonly',
          alert: 'readonly',
          confirm: 'readonly',
          prompt: 'readonly',
          isFinite: 'readonly',
          isNaN: 'readonly',
          parseInt: 'readonly',
          parseFloat: 'readonly',
          encodeURI: 'readonly',
          decodeURI: 'readonly',
          encodeURIComponent: 'readonly',
          decodeURIComponent: 'readonly',
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
    // DEBT-CX：按文件登记的复杂度上限，排在 prettier 之前（prettier 收尾关规则）
    ...complexityDebt,
    prettier,
  ];
}
