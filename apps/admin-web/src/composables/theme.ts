import { ref, computed } from 'vue';
import type { GlobalThemeOverrides } from 'naive-ui';
import { createNaiveThemeOverrides } from '@/theme/naive';

export type ThemeMode = 'light' | 'dark' | 'system';
const STORAGE_KEY = 'askai-admin-theme';

function getSystemThemePreference(): 'light' | 'dark' {
  if (typeof window === 'undefined') return 'light';
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

const storedTheme = localStorage.getItem(STORAGE_KEY) as ThemeMode | null;
const _theme = ref<ThemeMode>(
  storedTheme === 'dark' || storedTheme === 'light' || storedTheme === 'system'
    ? storedTheme
    : 'system' // 默认跟随系统
);

const activeThemeMode = ref<'light' | 'dark'>('light');

/**
 * naive-ui 的 themeOverrides 必须是**实际色值**（seemly 无法解析 CSS 变量），
 * 所以在主题 class 切换后重建一次。令牌仍是唯一颜色来源。
 */
const naiveOverrides = ref<GlobalThemeOverrides>(createNaiveThemeOverrides());

function updateActiveTheme() {
  if (_theme.value === 'system') {
    activeThemeMode.value = getSystemThemePreference();
  } else {
    activeThemeMode.value = _theme.value;
  }
  syncHtmlClass(activeThemeMode.value);
  // 必须在 syncHtmlClass 之后读令牌，否则拿到的是旧主题的值
  naiveOverrides.value = createNaiveThemeOverrides();
}

function syncHtmlClass(mode: 'light' | 'dark') {
  if (typeof document !== 'undefined') {
    if (mode === 'dark') {
      document.documentElement.classList.add('dark');
      document.documentElement.setAttribute('data-theme', 'dark');
    } else {
      document.documentElement.classList.remove('dark');
      document.documentElement.setAttribute('data-theme', 'light');
    }
  }
}

// eslint-disable-next-line no-useless-assignment -- initial null assignment before matchMedia check
let mediaQuery: MediaQueryList | null = null;
const handleSystemThemeChange = () => {
  if (_theme.value === 'system') {
    updateActiveTheme();
  }
};

if (typeof window !== 'undefined') {
  mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
  if (mediaQuery.addEventListener) {
    mediaQuery.addEventListener('change', handleSystemThemeChange);
  } else {
    mediaQuery.addListener(handleSystemThemeChange);
  }
}

// 首次初始化
updateActiveTheme();

// ESM 的 import 提升会让本模块早于 styles.css 执行，此时令牌还没注入，
// overrides 会退回 fallback 值。下一帧 CSS 已就绪，校准一次。
if (typeof window !== 'undefined') {
  window.requestAnimationFrame(() => {
    naiveOverrides.value = createNaiveThemeOverrides();
  });
}

export function useTheme() {
  return {
    theme: computed(() => _theme.value),
    activeTheme: computed(() => activeThemeMode.value),
    naiveOverrides,
    setTheme(mode: ThemeMode) {
      _theme.value = mode;
      localStorage.setItem(STORAGE_KEY, mode);
      updateActiveTheme();
    },
  };
}
