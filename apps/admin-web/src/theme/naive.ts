/**
 * naive-ui 主题桥接层（admin-web）
 *
 * 设计原则：themeOverrides 里**只引用 CSS 变量**（var(--mg-*)），不写死色值。
 * 这样浅色 / 深色切换时无需重建 overrides 对象，naive 组件与自定义样式共用同一套 token，
 * 从根上避免「深色下某些组件还是浅色」的不一致。
 *
 * 规范文档：docs/design-system.md
 */
import type { GlobalThemeOverrides } from 'naive-ui';

const fontFamily = '"SF Pro Text", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif';

export const naiveThemeOverrides: GlobalThemeOverrides = {
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
    primaryColor: 'var(--mg-brand)',
    primaryColorHover: 'var(--mg-brand-hover)',
    primaryColorPressed: 'var(--mg-brand-pressed)',
    primaryColorSuppl: 'var(--mg-brand-hover)',
    infoColor: 'var(--mg-info-text)',
    infoColorHover: 'var(--mg-brand-hover)',
    infoColorPressed: 'var(--mg-brand-pressed)',
    infoColorSuppl: 'var(--mg-brand-hover)',
    successColor: 'var(--mg-success-text)',
    successColorHover: 'var(--mg-success-text)',
    successColorPressed: 'var(--mg-success-text)',
    successColorSuppl: 'var(--mg-success-text)',
    warningColor: 'var(--mg-warning-text)',
    warningColorHover: 'var(--mg-warning-text)',
    warningColorPressed: 'var(--mg-warning-text)',
    warningColorSuppl: 'var(--mg-warning-text)',
    errorColor: 'var(--mg-danger-text)',
    errorColorHover: 'var(--mg-danger-text)',
    errorColorPressed: 'var(--mg-danger-text)',
    errorColorSuppl: 'var(--mg-danger-text)',

    // 文本三级层次
    textColorBase: 'var(--mg-text-1)',
    textColor1: 'var(--mg-text-1)',
    textColor2: 'var(--mg-text-2)',
    textColor3: 'var(--mg-text-3)',
    textColorDisabled: 'var(--mg-text-disabled)',
    placeholderColor: 'var(--mg-text-3)',
    placeholderColorDisabled: 'var(--mg-text-disabled)',
    iconColor: 'var(--mg-text-3)',
    iconColorHover: 'var(--mg-brand)',
    iconColorPressed: 'var(--mg-brand-pressed)',
    iconColorDisabled: 'var(--mg-text-disabled)',

    // 表面
    bodyColor: 'var(--mg-bg-app)',
    cardColor: 'var(--mg-bg-surface)',
    modalColor: 'var(--mg-bg-surface)',
    popoverColor: 'var(--mg-bg-surface)',
    tableColor: 'var(--mg-bg-surface)',
    tableHeaderColor: 'var(--mg-bg-subtle)',
    inputColor: 'var(--mg-bg-surface)',
    inputColorDisabled: 'var(--mg-bg-subtle)',
    actionColor: 'var(--mg-bg-subtle)',
    tagColor: 'var(--mg-neutral-bg)',
    hoverColor: 'var(--mg-bg-surface-hover)',
    invertedColor: 'var(--mg-bg-inverse)',

    // 边框
    borderColor: 'var(--mg-border)',
    dividerColor: 'var(--mg-divider)',
    closeIconColor: 'var(--mg-text-3)',
    closeIconColorHover: 'var(--mg-text-1)',
    clearColor: 'var(--mg-text-3)',
    clearColorHover: 'var(--mg-text-2)',

    // 形状
    borderRadius: '10px',
    borderRadiusSmall: '8px',

    // 阴影
    boxShadow1: 'var(--mg-shadow-sm)',
    boxShadow2: 'var(--mg-shadow-md)',
    boxShadow3: 'var(--mg-shadow-lg)',
  },

  Card: {
    borderRadius: '14px',
    color: 'var(--mg-bg-surface)',
    borderColor: 'var(--mg-border)',
    titleTextColor: 'var(--mg-text-1)',
    textColor: 'var(--mg-text-2)',
    colorEmbedded: 'var(--mg-bg-subtle)',
    boxShadow: 'var(--mg-shadow-card)',
  },

  DataTable: {
    thColor: 'var(--mg-bg-subtle)',
    thColorHover: 'var(--mg-bg-inset)',
    thTextColor: 'var(--mg-text-2)',
    thFontWeight: '600',
    tdColor: 'var(--mg-bg-surface)',
    tdColorHover: 'var(--mg-bg-surface-hover)',
    tdColorStriped: 'var(--mg-bg-surface-hover)',
    tdTextColor: 'var(--mg-text-1)',
    borderColor: 'var(--mg-border-subtle)',
    borderRadius: '10px',
  },

  Layout: {
    color: 'var(--mg-bg-app)',
    siderColor: 'var(--mg-bg-surface)',
    headerColor: 'var(--mg-bg-surface)',
    siderBorderColor: 'var(--mg-border)',
    headerBorderColor: 'var(--mg-border)',
    footerColor: 'var(--mg-bg-surface)',
  },

  Menu: {
    itemTextColor: 'var(--mg-text-2)',
    itemTextColorHover: 'var(--mg-text-1)',
    itemTextColorActive: 'var(--mg-brand-text)',
    itemTextColorActiveHover: 'var(--mg-brand-text)',
    itemTextColorChildActive: 'var(--mg-brand-text)',
    itemIconColor: 'var(--mg-text-3)',
    itemIconColorHover: 'var(--mg-text-1)',
    itemIconColorActive: 'var(--mg-brand)',
    itemIconColorActiveHover: 'var(--mg-brand)',
    itemIconColorChildActive: 'var(--mg-brand)',
    itemColorHover: 'var(--mg-brand-soft)',
    itemColorActive: 'var(--mg-brand-soft)',
    itemColorActiveHover: 'var(--mg-brand-soft-hover)',
    itemColorActiveCollapsed: 'var(--mg-brand-soft)',
    itemBorderRadius: '10px',
  },

  Tag: {
    borderRadius: '999px',
    colorBordered: 'var(--mg-bg-surface)',
    textColor: 'var(--mg-text-2)',
  },

  Button: {
    borderRadiusTiny: '6px',
    borderRadiusSmall: '8px',
    borderRadiusMedium: '10px',
    borderRadiusLarge: '12px',
    textColor: 'var(--mg-text-2)',
    textColorHover: 'var(--mg-brand-text)',
    textColorPressed: 'var(--mg-brand-pressed)',
    textColorFocus: 'var(--mg-brand-text)',
    border: '1px solid var(--mg-border)',
    borderHover: '1px solid var(--mg-brand)',
    borderPressed: '1px solid var(--mg-brand-pressed)',
    borderFocus: '1px solid var(--mg-brand)',
  },

  Input: {
    borderRadius: '8px',
    color: 'var(--mg-bg-surface)',
    colorFocus: 'var(--mg-bg-surface)',
    border: '1px solid var(--mg-border)',
    borderHover: '1px solid var(--mg-border-strong)',
    borderFocus: '1px solid var(--mg-brand)',
    boxShadowFocus: '0 0 0 2px var(--mg-brand-soft)',
    textColor: 'var(--mg-text-1)',
    placeholderColor: 'var(--mg-text-3)',
  },

  Select: {
    peers: {
      InternalSelection: {
        borderRadius: '8px',
        color: 'var(--mg-bg-surface)',
        colorActive: 'var(--mg-bg-surface)',
        border: '1px solid var(--mg-border)',
        borderHover: '1px solid var(--mg-border-strong)',
        borderActive: '1px solid var(--mg-brand)',
        borderFocus: '1px solid var(--mg-brand)',
        boxShadowActive: '0 0 0 2px var(--mg-brand-soft)',
        boxShadowFocus: '0 0 0 2px var(--mg-brand-soft)',
        textColor: 'var(--mg-text-1)',
        placeholderColor: 'var(--mg-text-3)',
      },
      InternalSelectMenu: {
        borderRadius: '10px',
        color: 'var(--mg-bg-surface)',
        optionTextColor: 'var(--mg-text-1)',
        optionTextColorActive: 'var(--mg-brand-text)',
        optionColorPending: 'var(--mg-bg-surface-hover)',
        optionColorActive: 'var(--mg-brand-soft)',
      },
    },
  },

  Tabs: {
    tabTextColorLine: 'var(--mg-text-2)',
    tabTextColorActiveLine: 'var(--mg-brand-text)',
    tabTextColorHoverLine: 'var(--mg-brand-text)',
    barColor: 'var(--mg-brand)',
    tabBorderColor: 'var(--mg-border)',
    tabColorSegment: 'var(--mg-bg-subtle)',
    tabTextColorSegment: 'var(--mg-text-2)',
    tabTextColorActiveSegment: 'var(--mg-text-1)',
    tabColorSegmentActive: 'var(--mg-bg-surface)',
  },

  Modal: {
    color: 'var(--mg-bg-surface)',
    borderRadius: '14px',
  },

  Alert: {
    borderRadius: '10px',
    titleTextColor: 'var(--mg-text-1)',
    contentTextColor: 'var(--mg-text-2)',
    iconColor: 'var(--mg-brand)',
  },

  Descriptions: {
    thColor: 'var(--mg-bg-subtle)',
    tdColor: 'var(--mg-bg-surface)',
    thTextColor: 'var(--mg-text-2)',
    tdTextColor: 'var(--mg-text-1)',
    borderColor: 'var(--mg-border)',
  },

  Empty: {
    iconColor: 'var(--mg-text-3)',
    textColor: 'var(--mg-text-3)',
  },

  Dropdown: {
    color: 'var(--mg-bg-surface)',
    optionTextColor: 'var(--mg-text-1)',
    optionTextColorHover: 'var(--mg-text-1)',
    optionTextColorActive: 'var(--mg-brand-text)',
    optionColorHover: 'var(--mg-brand-soft)',
    borderRadius: '10px',
  },

  PageHeader: {
    titleTextColor: 'var(--mg-text-1)',
    subtitleTextColor: 'var(--mg-text-3)',
    backColorHover: 'var(--mg-brand-soft)',
  },

  Form: {
    labelTextColor: 'var(--mg-text-2)',
    feedbackTextColorError: 'var(--mg-danger-text)',
  },

  Pagination: {
    itemTextColor: 'var(--mg-text-2)',
    itemTextColorActive: 'var(--mg-brand-text)',
    itemColorActive: 'var(--mg-brand-soft)',
    itemColorHover: 'var(--mg-bg-surface-hover)',
  },
};
