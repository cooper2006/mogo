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
.metric-card{border:1px solid var(--mg-border);border-radius:8px;background:var(--mg-bg-surface);box-shadow:var(--mg-shadow-xs)}
.metric-main{display:flex;align-items:flex-start;gap:12px}.metric-body{display:flex;flex-direction:column;gap:4px}
.metric-icon{width:44px;height:44px;flex:none;border-radius:50%;display:grid;place-items:center}
.metric-icon :deep(svg){width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.metric-icon-total{color:var(--mg-brand);background:var(--mg-brand-soft)}.metric-icon-personal{color:var(--mg-success-text);background:var(--mg-success-bg)}
.metric-icon-enterprise{color:var(--mg-warning-text);background:var(--mg-warning-bg)}.metric-icon-enabled{color:var(--mg-accent-violet-text);background:var(--mg-accent-violet-bg)}
.metric-label{color:var(--mg-text-3);font-size:12px;line-height:1.3}.metric-value{color:var(--mg-text-1);font-size:24px;font-weight:600;line-height:1.1}
.metric-note{margin-top:6px;color:var(--mg-text-3);font-size:12px}
@media(max-width:1200px){.metrics-row{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:768px){.metrics-row{grid-template-columns:minmax(0,1fr)}}
</style>
