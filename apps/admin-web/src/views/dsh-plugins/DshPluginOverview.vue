<template>
  <div class="metrics-row">
    <n-card v-for="metric in metrics" :key="metric.key" class="metric-card" :bordered="false" size="small">
      <div class="metric-main">
        <span class="metric-icon" :class="`metric-icon-${metric.key}`">
          <DshPluginsIcon v-if="metric.key === 'total'" />
          <svg v-else-if="metric.key === 'enabled'" viewBox="0 0 24 24"><path d="m5 12 4 4L19 6" /></svg>
          <svg v-else-if="metric.key === 'disabled'" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" /><path d="M6 6l12 12" /></svg>
          <svg v-else viewBox="0 0 24 24"><path d="M4 8h16M4 16h16" /><circle cx="8" cy="8" r="2" /><circle cx="16" cy="16" r="2" /></svg>
        </span>
        <div><div class="metric-label">{{ metric.label }}</div><div class="metric-value">{{ metric.value }}</div></div>
      </div>
      <div class="metric-note">{{ metric.note }}</div>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NCard } from 'naive-ui'
import type { DshPlugin } from '@/api/dsh-plugins'
import { t } from '@/composables/i18n'
import { DshPluginsIcon } from '@/icons/DshPluginsIcon'

const props = defineProps<{ plugins: DshPlugin[] }>()
const metrics = computed(() => [
  { key: 'total', label: t('dshPlugins.total'), value: props.plugins.length, note: t('dshPlugins.totalNote') },
  { key: 'enabled', label: t('dshPlugins.enabledCount'), value: props.plugins.filter(item => item.enabled).length, note: t('dshPlugins.enabledNote') },
  { key: 'disabled', label: t('dshPlugins.disabledCount'), value: props.plugins.filter(item => !item.enabled).length, note: t('dshPlugins.disabledNote') },
  { key: 'tools', label: t('dshPlugins.toolsCount'), value: new Set(props.plugins.flatMap(item => item.tool_names || [])).size, note: t('dshPlugins.toolsNote') },
])
</script>

<style scoped>
.metrics-row{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;padding:12px}
.metric-card{border:1px solid var(--mg-border);border-radius:8px;background:var(--mg-bg-surface);box-shadow:var(--mg-shadow-xs)}
.metric-main{display:flex;align-items:flex-start;gap:12px}.metric-label{color:var(--mg-text-3);font-size:12px;line-height:1.3}.metric-value{margin-top:4px;color:var(--mg-text-1);font-size:24px;font-weight:600;line-height:1.1}.metric-note{margin-top:6px;color:var(--mg-text-3);font-size:12px}
.metric-icon{width:44px;height:44px;border-radius:50%;display:grid;place-items:center}.metric-icon :deep(svg){width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}.metric-icon-total{color:var(--mg-brand);background:var(--mg-brand-soft)}.metric-icon-total :deep(svg){fill:currentColor;stroke:none}.metric-icon-enabled{color:var(--mg-success-text);background:var(--mg-success-bg)}.metric-icon-disabled{color:var(--mg-warning-text);background:var(--mg-warning-bg)}.metric-icon-tools{color:var(--mg-accent-violet-text);background:var(--mg-accent-violet-bg)}
@media(max-width:1200px){.metrics-row{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:640px){.metrics-row{grid-template-columns:1fr}}
</style>
