<template>
  <n-card class="list-card" :bordered="false" size="large">
    <div class="list-heading-row"><span class="list-heading">{{ t('plugins.listTitle') }}</span></div>
    <div class="list-filter-row">
      <div class="filter-toolbar">
        <n-space align="center" :size="10" class="filter-left">
          <n-input v-model:value="keyword" clearable :placeholder="t('plugins.search')" class="keyword-input" />
          <n-select v-model:value="scope" :options="scopeOptions" class="scope-select" />
        </n-space>
        <n-space :size="10" class="filter-right">
          <n-button secondary @click="emit('reload')">
            <template #icon><svg viewBox="0 0 24 24"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8M3 3v5h5M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16M16 16h5v5" /></svg></template>
            {{ t('ui.refresh') }}
          </n-button>
          <n-button type="primary" strong @click="emit('add')">
            <template #icon><svg viewBox="0 0 24 24"><path d="M5 12h14M12 5v14" /></svg></template>
            {{ t('plugins.add') }}
          </n-button>
        </n-space>
      </div>
    </div>
    <div class="list-body">
      <n-spin :show="loading">
        <div v-if="filtered.length" class="plugin-grid">
          <article v-for="plugin in filtered" :key="plugin.id" class="plugin-card" :class="{ 'plugin-card-disabled': !plugin.enabled }">
            <div class="card-head">
              <div class="card-tags">
                <n-tag size="small" :bordered="false" type="info">{{ t('plugins.dsh') }}</n-tag>
                <n-tag size="small" :bordered="false" :type="plugin.enabled ? 'success' : 'default'">{{ t(plugin.enabled ? 'plugins.enabled' : 'plugins.disabled') }}</n-tag>
                <n-tag size="small" :bordered="false" type="success">v{{ plugin.version }}</n-tag>
              </div>
              <span v-if="plugin.updatedAt" class="card-time">{{ formatAppDateTime(plugin.updatedAt) }}</span>
            </div>
            <div class="card-title">{{ plugin.name }}</div>
            <div class="card-desc">{{ plugin.description || plugin.spec }}</div>
            <PluginAvailability :availability="plugin.availability" :busy="busyId === plugin.id" :can-verify="plugin.scope === 'personal'" @verify="emit('verify', plugin)" />
            <div class="card-footrow">
              <n-tag size="small" :bordered="false" :type="plugin.scope === 'organization' ? 'info' : 'success'">{{ t(plugin.scope === 'organization' ? 'plugins.enterprise' : 'plugins.mine') }}</n-tag>
              <div v-if="plugin.scope === 'personal'" class="card-actions">
                <div class="card-switch"><span>{{ t(plugin.enabled ? 'plugins.enabled' : 'plugins.disabled') }}</span><n-switch size="small" :value="plugin.enabled" :loading="busyId === plugin.id" :disabled="!plugin.enabled && !['session_exposed', 'verified'].includes(plugin.availability?.status || '')" @update:value="enabled => emit('toggle', plugin, enabled)" /></div>
                <n-popconfirm @positive-click="emit('remove', plugin)">
                  <template #trigger><n-button class="delete-btn" size="small" quaternary circle :title="t('plugins.remove')" :aria-label="t('plugins.remove')"><svg viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14M10 11v6M14 11v6" /></svg></n-button></template>
                  {{ t('plugins.confirmRemove') }}
                </n-popconfirm>
              </div>
            </div>
          </article>
        </div>
        <div v-else class="empty-shell">
          <div class="empty-visual">DSH</div>
          <div class="empty-title">{{ t(plugins.length ? 'plugins.noMatches' : 'plugins.empty') }}</div>
          <div class="empty-desc">{{ t(plugins.length ? 'plugins.adjustFilters' : 'plugins.emptyHint') }}</div>
          <n-button v-if="!plugins.length" type="primary" @click="emit('add')">{{ t('plugins.add') }}</n-button>
        </div>
      </n-spin>
    </div>
  </n-card>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { NButton, NCard, NInput, NPopconfirm, NSelect, NSpace, NSpin, NSwitch, NTag } from 'naive-ui'
import type { DshPlugin } from '../../api/dshPlugins'
import { t } from '../../composables/i18n'
import { formatAppDateTime } from '../../composables/appTimezone'
import PluginAvailability from './PluginAvailability.vue'

const props = defineProps<{ plugins: DshPlugin[]; loading: boolean; busyId: string }>()
const emit = defineEmits<{ reload: []; add: []; toggle: [plugin: DshPlugin, enabled: boolean]; remove: [plugin: DshPlugin]; verify: [plugin: DshPlugin] }>()
const keyword = ref('')
const scope = ref('all')
const scopeOptions = computed(() => [
  { label: t('plugins.allScopes'), value: 'all' },
  { label: t('plugins.mine'), value: 'personal' },
  { label: t('plugins.enterprise'), value: 'organization' },
])
const filtered = computed(() => {
  const query = keyword.value.trim().toLocaleLowerCase()
  return props.plugins.filter(plugin =>
    (scope.value === 'all' || plugin.scope === scope.value) &&
    (!query || `${plugin.name} ${plugin.description} ${plugin.spec}`.toLocaleLowerCase().includes(query)),
  )
})
</script>

<style scoped>
.list-card{width:100%;margin:0;flex:1;min-height:0;overflow:hidden;border:1px solid #e6ebf5;border-radius:8px;background:#fff;box-shadow:0 6px 20px rgba(16,38,84,.05)}
.list-card :deep(.n-card-content){height:100%;display:flex;flex-direction:column}
.list-heading-row{display:flex;align-items:center;margin-bottom:14px;padding-bottom:10px;border-bottom:1px solid #edf1f7}
.list-heading{padding:8px 14px;border-radius:8px;background:#edf3ff;color:#2459e8;font-size:14px;font-weight:650}
.list-filter-row{padding:0 44px 12px;margin:0 -44px 12px;border-bottom:1px solid #edf1f7}
.filter-toolbar{display:flex;align-items:center;justify-content:space-between;gap:14px}.filter-left,.filter-right{flex-wrap:wrap}
.keyword-input{width:360px}.scope-select{width:160px}
.filter-toolbar svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.list-body{flex:1;min-height:0;overflow:auto}
.plugin-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
.plugin-card{min-height:188px;padding:14px;border:1px solid rgba(28,45,82,.08);border-radius:8px;background:#fff;box-shadow:0 8px 18px rgba(15,31,69,.06),0 1px 2px rgba(15,31,69,.04);display:flex;flex-direction:column;gap:10px;transition:border-color .2s,box-shadow .2s,transform .2s}
.plugin-card:hover{border-color:rgba(54,106,255,.36);box-shadow:0 14px 34px rgba(33,58,126,.14),0 4px 10px rgba(33,58,126,.08);transform:translateY(-2px)}
.plugin-card-disabled{background:linear-gradient(180deg,#fbfcfe,#f6f8fc)}
.card-head,.card-footrow{display:flex;align-items:center;justify-content:space-between;gap:10px}.card-tags{display:inline-flex;align-items:center;gap:6px;flex-wrap:wrap}
.card-time{color:#7a8797;font-size:12px;white-space:nowrap}.card-title{color:#17233d;font-size:16px;font-weight:800;overflow-wrap:anywhere}
.card-desc{color:#5f6f85;font-size:13px;line-height:1.55;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:3;overflow:hidden}
.card-footrow{margin-top:auto}.card-actions{display:inline-flex;align-items:center;gap:6px}
.card-switch{display:inline-flex;align-items:center;gap:8px;padding:4px 10px;border-radius:999px;background:#f6f9ff;border:1px solid #e3ebfb;color:#4a5d7c;font-size:12px}
.delete-btn svg{width:15px;height:15px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round}.delete-btn:hover{color:#d03050}
.empty-shell{min-height:320px;border:1px dashed #d8e2f2;border-radius:12px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;text-align:center;background:linear-gradient(180deg,#fbfdff,#fff)}
.empty-visual{width:54px;height:36px;border:1px solid #d8e2f2;border-radius:10px;display:grid;place-items:center;color:#2d63ff;font-size:11px;font-weight:700;box-shadow:0 4px 10px rgba(45,99,255,.06)}
.empty-title{color:#1a2744;font-size:15px;font-weight:700}.empty-desc{color:#6c7c94;font-size:13px}
@media(max-width:768px){.filter-toolbar{flex-direction:column;align-items:stretch}.keyword-input{width:100%}.plugin-grid{grid-template-columns:minmax(0,1fr)}.list-filter-row{padding:0 16px 12px;margin:0 -16px 12px}.card-time{display:none}}
</style>
