<template>
  <a href="#main-content" class="skip-link">跳转到主内容</a>
  <n-config-provider
    :theme="themeInstance"
    :theme-overrides="naiveOverrides"
    :locale="naiveLocale"
    :date-locale="naiveDateLocale"
  >
    <n-dialog-provider>
      <n-message-provider>
        <main id="main-content">
          <router-view />
        </main>
      </n-message-provider>
    </n-dialog-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue';
import { zhCN, dateZhCN, enUS, dateEnUS, darkTheme } from 'naive-ui';
import { useLocale } from '@/composables/i18n';
import { useTheme } from '@/composables/theme';

const { locale } = useLocale();
const { activeTheme, naiveOverrides } = useTheme();

// 组件外观由 theme/naive.ts 的 CSS 变量引用驱动，深浅主题只需切换 base theme。
const themeInstance = computed(() => {
  return activeTheme.value === 'dark' ? darkTheme : null;
});

const naiveLocale = computed(() => {
  return locale.value === 'en-US' ? enUS : zhCN;
});

const naiveDateLocale = computed(() => {
  return locale.value === 'en-US' ? dateEnUS : dateZhCN;
});

watch(
  locale,
  (value) => {
    document.documentElement.lang = value;
  },
  { immediate: true },
);
</script>
