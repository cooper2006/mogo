import { createPinia } from 'pinia';
import { createApp } from 'vue';
import { create, NAvatar, NBadge, NButton, NCard, NCheckbox, NConfigProvider, NDataTable, NDescriptions, NDescriptionsItem, NDialogProvider, NDivider, NDrawer, NDrawerContent, NDropdown, NEmpty, NForm, NFormItem, NGrid, NGridItem, NIcon, NInput, NInputNumber, NLayout, NLayoutContent, NLayoutFooter, NLayoutHeader, NLayoutSider, NMenu, NMessageProvider, NModal, NNumberAnimation, NPageHeader, NPagination, NPopover, NRadio, NRadioButton, NRadioGroup, NResult, NSelect, NSpace, NSpin, NStatistic, NSwitch, NTabPane, NTable, NTabs, NTag, NThing, NTree } from 'naive-ui';
import App from './App.vue';
import { router } from './router';
import { initVitals } from './plugins/vitals';

// 026 T033: 采集 LCP/FID/CLS/TTFB 并上报（FR-21）。端点可用 VITE_VITALS_REPORT_URL 覆盖。
initVitals({ reportUrl: (import.meta.env.VITE_VITALS_REPORT_URL as string | undefined) || '/api/v1/metrics/vitals' });

export function bootstrap() {
  const app = createApp(App);
  const pinia = createPinia();
  const naive = create({
    components: [
      NButton,
      NAvatar,
      NBadge,
      NCard,
      NCheckbox,
      NConfigProvider,
      NDataTable,
      NDescriptions,
      NDescriptionsItem,
      NDialogProvider,
      NDivider,
      NDrawer,
      NDrawerContent,
      NDropdown,
      NEmpty,
      NForm,
      NFormItem,
      NGrid,
      NGridItem,
      NIcon,
      NInput,
      NInputNumber,
      NLayout,
      NLayoutContent,
      NLayoutFooter,
      NLayoutHeader,
      NLayoutSider,
      NMenu,
      NMessageProvider,
      NModal,
      NNumberAnimation,
      NPageHeader,
      NPagination,
      NPopover,
      NRadio,
      NRadioButton,
      NRadioGroup,
      NResult,
      NSelect,
      NSpace,
      NSpin,
      NStatistic,
      NSwitch,
      NTabPane,
      NTable,
      NTabs,
      NTag,
      NThing,
      NTree,
    ],
  });

  app.use(pinia);
  app.use(router);
  app.use(naive);
  app.mount('#app');
}
