import { createPinia } from 'pinia';
import { createApp } from 'vue';
import { create, NAvatar, NBadge, NButton, NCard, NCheckbox, NConfigProvider, NDataTable, NDescriptions, NDescriptionsItem, NDialogProvider, NDivider, NDrawer, NDrawerContent, NDropdown, NEmpty, NForm, NFormItem, NGrid, NGridItem, NIcon, NInput, NInputNumber, NLayout, NLayoutContent, NLayoutFooter, NLayoutHeader, NLayoutSider, NMenu, NMessageProvider, NModal, NNumberAnimation, NPageHeader, NPagination, NPopover, NRadio, NRadioButton, NRadioGroup, NResult, NSelect, NSpace, NSpin, NStatistic, NSwitch, NTabPane, NTable, NTabs, NTag, NThing, NTree } from 'naive-ui';
import App from './App.vue';
import { router } from './router';
import { initVitals } from './plugins/vitals';

// 026 T033: 采集 LCP/FID/CLS/TTFB（FR-21）。
// 上报端点必须显式配置 VITE_VITALS_REPORT_URL：后端目前没有 /metrics/vitals 接收端点
// （T033 只落地了采集侧），硬编码默认值只会让每个页面刷一条 404。补齐接收端点后
// 配一个环境变量即可开启，无需再改代码。
const vitalsReportUrl = (import.meta.env.VITE_VITALS_REPORT_URL as string | undefined)?.trim();
if (vitalsReportUrl) initVitals({ reportUrl: vitalsReportUrl });

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
