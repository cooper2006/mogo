<template>
  <div class="metrics-row">
    <n-card v-for="item in metrics" :key="item.key" class="metric-card" :bordered="false" size="small">
      <div class="metric-main">
        <span class="metric-icon" :class="`metric-icon-${item.key}`" v-html="item.icon"></span>
        <div class="metric-body"><div class="metric-label">{{ item.label }}</div><div class="metric-value">{{ item.value }}</div></div>
      </div>
      <div class="metric-note">{{ item.note }}</div>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NCard } from 'naive-ui'
import type { DshPlugin } from '../../api/dshPlugins'
import { t } from '../../composables/i18n'

const props = defineProps<{ plugins: DshPlugin[] }>()
const metrics = computed(() => [
  { key: 'total', icon: '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/></svg>', label: t('plugins.metricTotal'), value: props.plugins.length, note: t('plugins.metricTotalNote') },
  { key: 'personal', icon: '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>', label: t('plugins.metricPersonal'), value: props.plugins.filter(plugin => plugin.scope === 'personal').length, note: t('plugins.metricPersonalNote') },
  { key: 'enterprise', icon: '<svg viewBox="0 0 24 24"><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 7h2m4 0h2M8 11h2m4 0h2M9 21v-5h6v5"/></svg>', label: t('plugins.metricEnterprise'), value: props.plugins.filter(plugin => plugin.scope === 'organization').length, note: t('plugins.metricEnterpriseNote') },
  { key: 'enabled', icon: '<svg viewBox="0 0 24 24"><path d="m5 12 5 5L20 7"/></svg>', label: t('plugins.metricEnabled'), value: props.plugins.filter(plugin => plugin.enabled).length, note: t('plugins.metricEnabledNote') },
])
</script>

<style scoped>
.metrics-row{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.metric-card{border:1px solid #e6ebf5;border-radius:8px;background:#fff;box-shadow:0 4px 12px rgba(29,54,110,.04)}
.metric-main{display:flex;align-items:flex-start;gap:12px}.metric-body{display:flex;flex-direction:column;gap:4px}
.metric-icon{width:44px;height:44px;flex:none;border-radius:50%;display:grid;place-items:center}
.metric-icon :deep(svg){width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.metric-icon-total{color:#2d63ff;background:#eaf0ff}.metric-icon-personal{color:#0f9964;background:#e8f8ef}
.metric-icon-enterprise{color:#d9860a;background:#fff2df}.metric-icon-enabled{color:#7456e0;background:#f0ebff}
.metric-label{color:#606f8a;font-size:12px;line-height:1.3}.metric-value{color:#0f1f45;font-size:24px;font-weight:600;line-height:1.1}
.metric-note{margin-top:6px;color:#708099;font-size:12px}
@media(max-width:1200px){.metrics-row{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:768px){.metrics-row{grid-template-columns:minmax(0,1fr)}}
</style>
