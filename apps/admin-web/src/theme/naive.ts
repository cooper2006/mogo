/**
 * naive-ui 主题桥接层（admin-web）
 *
 * ⚠️ 关键约束：themeOverrides 的颜色值**必须是实际色值**，不能是 `var(--mg-*)`。
 * naive-ui 内部用 seemly 在 JS 里解析颜色做运算（计算 hover 色、透明叠加等），
 * 遇到 CSS 变量会抛 `[seemly/rgba]: Invalid color value`。
 *
 * 因此这里在**运行时**从 :root 读取令牌的 computed 值：
 *   令牌仍是唯一来源 → 主题切换时重建 overrides 对象（见 composables/theme.ts）
 *
 * 规范文档：docs/design-system.md
 */
import type { GlobalThemeOverrides } from 'naive-ui';

const fontFamily = '"SF Pro Text", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif';

/**
 * 浅色主题下的兜底值。仅在以下情况使用：
 *   - SSR / 非浏览器环境
 *   - 令牌尚未注入（理论上不会发生：styles.css 先于 JS 执行）
 * 取值必须与 tokens.css 的浅色段一致。
 */
const FALLBACK: Record<string, string> = {
  '--mg-brand': '#366aff',
  '--mg-brand-hover': '#5580ff',
  '--mg-brand-pressed': '#2757e6',
  '--mg-brand-soft': '#eef3ff',
  '--mg-brand-soft-hover': '#e4ecff',
  '--mg-brand-soft-border': '#dbe6ff',
  '--mg-brand-text': '#2248b8',

  '--mg-text-1': '#101c3d',
  '--mg-text-2': '#4a5773',
  '--mg-text-3': '#8a94a8',
  '--mg-text-disabled': '#b3bccb',
  '--mg-text-link': '#2248b8',
  '--mg-text-on-brand': '#ffffff',

  '--mg-bg-app': '#f5f7fc',
  '--mg-bg-surface': '#ffffff',
  '--mg-bg-surface-hover': '#fafbfe',
  '--mg-bg-subtle': '#eef2f9',
  '--mg-bg-inset': '#edf1f8',
  '--mg-bg-inverse': '#101c3d',

  '--mg-border': '#e3e9f4',
  '--mg-border-strong': '#cfd9ea',
  '--mg-border-subtle': '#edf1f8',
  '--mg-divider': '#edf1f8',

  '--mg-success-text': '#127a44',
  '--mg-warning-text': '#a35a06',
  '--mg-danger-text': '#c0293f',
  '--mg-info-text': '#2248b8',

  '--mg-neutral-bg': '#f2f5fa',
  '--mg-neutral-text': '#6b7688',

  '--mg-shadow-sm': '0 2px 8px rgba(16, 38, 84, 0.06)',
  '--mg-shadow-md': '0 6px 20px rgba(16, 38, 84, 0.07)',
  '--mg-shadow-lg': '0 16px 40px rgba(16, 38, 84, 0.1)',
  '--mg-shadow-card': '0 6px 20px rgba(16, 38, 84, 0.07)',
};

/**
 * 读取令牌的运行时值（跟随当前 html class 对应的主题）。
 *
 * 注意：语义层是用 `--mg-brand: var(--mg-palette-blue-500)` 这种间接引用定义的，
 * 而 getComputedStyle 对自定义属性返回的是**未解析的字面值**（`var(--mg-palette-blue-500)`），
 * 不会像普通属性那样递归替换。所以这里必须自己递归展开，否则传给 naive 的仍是 var()，
 * seemly 会抛 `[seemly/rgba]: Invalid color value`。
 */
export function readToken(name: string, depth = 0): string {
  if (typeof document === 'undefined' || depth > 6) return FALLBACK[name] ?? '#000000';

  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  if (!value) return FALLBACK[name] ?? '#000000';

  // 纯 var() 引用：递归展开到实际值
  const alias = /^var\(\s*(--mg-[\w-]+)\s*\)$/.exec(value);
  if (alias) return readToken(alias[1], depth + 1);

  // 混在其它值里的 var()（如 `1px solid var(--x)`）：逐个替换
  if (value.includes('var(')) {
    return value.replace(/var\(\s*(--mg-[\w-]+)\s*\)/g, (_, inner) => readToken(inner, depth + 1));
  }

  return value;
}

/**
 * 构建当前主题下的 naive overrides。
 * 必须在 <html> 的主题 class 切换**之后**调用，才能读到新主题的令牌值。
 */
export function createNaiveThemeOverrides(): GlobalThemeOverrides {
  const c = readToken;

  return {
    common: {
      fontFamily,
      fontSize: '14px',
      fontSizeMini: '12px',
      fontSizeTiny: '12px',
      fontSizeSmall: '13px',
      fontSizeMedium: '14px',
      fontSizeLarge: '15px',
      fontSizeHuge: '16px',

      // 品牌
      primaryColor: c('--mg-brand'),
      primaryColorHover: c('--mg-brand-hover'),
      primaryColorPressed: c('--mg-brand-pressed'),
      primaryColorSuppl: c('--mg-brand-hover'),
      infoColor: c('--mg-info-text'),
      infoColorHover: c('--mg-brand-hover'),
      infoColorPressed: c('--mg-brand-pressed'),
      infoColorSuppl: c('--mg-brand-hover'),
      successColor: c('--mg-success-text'),
      successColorHover: c('--mg-success-text'),
      successColorPressed: c('--mg-success-text'),
      successColorSuppl: c('--mg-success-text'),
      warningColor: c('--mg-warning-text'),
      warningColorHover: c('--mg-warning-text'),
      warningColorPressed: c('--mg-warning-text'),
      warningColorSuppl: c('--mg-warning-text'),
      errorColor: c('--mg-danger-text'),
      errorColorHover: c('--mg-danger-text'),
      errorColorPressed: c('--mg-danger-text'),
      errorColorSuppl: c('--mg-danger-text'),

      // 文本三级层次
      textColorBase: c('--mg-text-1'),
      textColor1: c('--mg-text-1'),
      textColor2: c('--mg-text-2'),
      textColor3: c('--mg-text-3'),
      textColorDisabled: c('--mg-text-disabled'),
      placeholderColor: c('--mg-text-3'),
      placeholderColorDisabled: c('--mg-text-disabled'),
      iconColor: c('--mg-text-3'),
      iconColorHover: c('--mg-brand'),
      iconColorPressed: c('--mg-brand-pressed'),
      iconColorDisabled: c('--mg-text-disabled'),

      // 表面
      bodyColor: c('--mg-bg-app'),
      cardColor: c('--mg-bg-surface'),
      modalColor: c('--mg-bg-surface'),
      popoverColor: c('--mg-bg-surface'),
      tableColor: c('--mg-bg-surface'),
      tableHeaderColor: c('--mg-bg-subtle'),
      inputColor: c('--mg-bg-surface'),
      inputColorDisabled: c('--mg-bg-subtle'),
      actionColor: c('--mg-bg-subtle'),
      tagColor: c('--mg-neutral-bg'),
      hoverColor: c('--mg-bg-surface-hover'),
      invertedColor: c('--mg-bg-inverse'),

      // 边框
      borderColor: c('--mg-border'),
      dividerColor: c('--mg-divider'),
      closeIconColor: c('--mg-text-3'),
      closeIconColorHover: c('--mg-text-1'),
      clearColor: c('--mg-text-3'),
      clearColorHover: c('--mg-text-2'),

      // 形状
      borderRadius: '10px',
      borderRadiusSmall: '8px',

      // 阴影
      boxShadow1: c('--mg-shadow-sm'),
      boxShadow2: c('--mg-shadow-md'),
      boxShadow3: c('--mg-shadow-lg'),
    },

    Card: {
      borderRadius: '14px',
      color: c('--mg-bg-surface'),
      borderColor: c('--mg-border'),
      titleTextColor: c('--mg-text-1'),
      textColor: c('--mg-text-2'),
      colorEmbedded: c('--mg-bg-subtle'),
      boxShadow: c('--mg-shadow-card'),
    },

    DataTable: {
      thColor: c('--mg-bg-subtle'),
      thColorHover: c('--mg-bg-inset'),
      thTextColor: c('--mg-text-2'),
      thFontWeight: '600',
      tdColor: c('--mg-bg-surface'),
      tdColorHover: c('--mg-bg-surface-hover'),
      tdColorStriped: c('--mg-bg-surface-hover'),
      tdTextColor: c('--mg-text-1'),
      borderColor: c('--mg-border-subtle'),
      borderRadius: '10px',
    },

    Layout: {
      color: c('--mg-bg-app'),
      siderColor: c('--mg-bg-surface'),
      headerColor: c('--mg-bg-surface'),
      siderBorderColor: c('--mg-border'),
      headerBorderColor: c('--mg-border'),
      footerColor: c('--mg-bg-surface'),
    },

    Menu: {
      itemTextColor: c('--mg-text-2'),
      itemTextColorHover: c('--mg-text-1'),
      itemTextColorActive: c('--mg-brand-text'),
      itemTextColorActiveHover: c('--mg-brand-text'),
      itemTextColorChildActive: c('--mg-brand-text'),
      itemIconColor: c('--mg-text-3'),
      itemIconColorHover: c('--mg-text-1'),
      itemIconColorActive: c('--mg-brand'),
      itemIconColorActiveHover: c('--mg-brand'),
      itemIconColorChildActive: c('--mg-brand'),
      itemColorHover: c('--mg-brand-soft'),
      itemColorActive: c('--mg-brand-soft'),
      itemColorActiveHover: c('--mg-brand-soft-hover'),
      itemColorActiveCollapsed: c('--mg-brand-soft'),
      itemBorderRadius: '10px',
    },

    Tag: {
      borderRadius: '999px',
      colorBordered: c('--mg-bg-surface'),
      textColor: c('--mg-text-2'),
    },

    Button: {
      borderRadiusTiny: '6px',
      borderRadiusSmall: '8px',
      borderRadiusMedium: '10px',
      borderRadiusLarge: '12px',
      textColor: c('--mg-text-2'),
      textColorHover: c('--mg-brand-text'),
      textColorPressed: c('--mg-brand-pressed'),
      textColorFocus: c('--mg-brand-text'),
      border: `1px solid ${c('--mg-border')}`,
      borderHover: `1px solid ${c('--mg-brand')}`,
      borderPressed: `1px solid ${c('--mg-brand-pressed')}`,
      borderFocus: `1px solid ${c('--mg-brand')}`,
    },

    Input: {
      borderRadius: '8px',
      color: c('--mg-bg-surface'),
      colorFocus: c('--mg-bg-surface'),
      border: `1px solid ${c('--mg-border')}`,
      borderHover: `1px solid ${c('--mg-border-strong')}`,
      borderFocus: `1px solid ${c('--mg-brand')}`,
      boxShadowFocus: `0 0 0 2px ${c('--mg-brand-soft')}`,
      textColor: c('--mg-text-1'),
      placeholderColor: c('--mg-text-3'),
    },

    Select: {
      peers: {
        InternalSelection: {
          borderRadius: '8px',
          color: c('--mg-bg-surface'),
          colorActive: c('--mg-bg-surface'),
          border: `1px solid ${c('--mg-border')}`,
          borderHover: `1px solid ${c('--mg-border-strong')}`,
          borderActive: `1px solid ${c('--mg-brand')}`,
          borderFocus: `1px solid ${c('--mg-brand')}`,
          boxShadowActive: `0 0 0 2px ${c('--mg-brand-soft')}`,
          boxShadowFocus: `0 0 0 2px ${c('--mg-brand-soft')}`,
          textColor: c('--mg-text-1'),
          placeholderColor: c('--mg-text-3'),
        },
        InternalSelectMenu: {
          borderRadius: '10px',
          color: c('--mg-bg-surface'),
          optionTextColor: c('--mg-text-1'),
          optionTextColorActive: c('--mg-brand-text'),
          optionColorPending: c('--mg-bg-surface-hover'),
          optionColorActive: c('--mg-brand-soft'),
        },
      },
    },

    Tabs: {
      tabTextColorLine: c('--mg-text-2'),
      tabTextColorActiveLine: c('--mg-brand-text'),
      tabTextColorHoverLine: c('--mg-brand-text'),
      barColor: c('--mg-brand'),
      tabBorderColor: c('--mg-border'),
      tabColorSegment: c('--mg-bg-subtle'),
      tabTextColorSegment: c('--mg-text-2'),
      tabTextColorActiveSegment: c('--mg-text-1'),
      tabColorSegmentActive: c('--mg-bg-surface'),
    },

    Modal: {
      color: c('--mg-bg-surface'),
      borderRadius: '14px',
    },

    Alert: {
      borderRadius: '10px',
      titleTextColor: c('--mg-text-1'),
      contentTextColor: c('--mg-text-2'),
      iconColor: c('--mg-brand'),
    },

    Descriptions: {
      thColor: c('--mg-bg-subtle'),
      tdColor: c('--mg-bg-surface'),
      thTextColor: c('--mg-text-2'),
      tdTextColor: c('--mg-text-1'),
      borderColor: c('--mg-border'),
    },

    Empty: {
      iconColor: c('--mg-text-3'),
      textColor: c('--mg-text-3'),
    },

    Dropdown: {
      color: c('--mg-bg-surface'),
      optionTextColor: c('--mg-text-1'),
      optionTextColorHover: c('--mg-text-1'),
      optionTextColorActive: c('--mg-brand-text'),
      optionColorHover: c('--mg-brand-soft'),
      borderRadius: '10px',
    },

    PageHeader: {
      titleTextColor: c('--mg-text-1'),
      subtitleTextColor: c('--mg-text-3'),
      backColorHover: c('--mg-brand-soft'),
    },

    Form: {
      labelTextColor: c('--mg-text-2'),
      feedbackTextColorError: c('--mg-danger-text'),
    },

    Pagination: {
      itemTextColor: c('--mg-text-2'),
      itemTextColorActive: c('--mg-brand-text'),
      itemColorActive: c('--mg-brand-soft'),
      itemColorHover: c('--mg-bg-surface-hover'),
    },
  };
}
