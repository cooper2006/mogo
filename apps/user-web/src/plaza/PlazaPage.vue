<script setup lang="ts">
import { t } from '../composables/i18n'
/**
 * /plaza 模板广场页（053-plaza-template-distribution，user-web 门户侧）。
 * 目录（租户内已上架模板）→ 详情（版本序列）→ 克隆入口提示。
 * 数据经 chat-api ``/askai-api/api/v1/plaza/templates``（end_user 会话，只读）。
 */
import { computed, onMounted, ref } from 'vue'
import {
  fetchPlazaTemplates,
  type PlazaTemplateItem,
  type PlazaTemplateType,
} from '@/api/plazaTemplates'

const loading = ref(true)
const error = ref('')
const items = ref<PlazaTemplateItem[]>([])
const assetType = ref<PlazaTemplateType | 'all'>('all')

const typeLabels: Record<string, string> = {
  employee_template: '员工模板',
  sop_template: 'SOP 模板',
}

const filtered = computed(() => items.value)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await fetchPlazaTemplates(
      assetType.value === 'all' ? {} : { asset_type: assetType.value },
    )
    items.value = res.items
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function setType(t: PlazaTemplateType | 'all') {
  assetType.value = t
  load()
}

function cloneHint() {
  window.alert('克隆功能需管理员会话，请在 admin-web 模板管理页操作')
}

onMounted(load)
</script>

<template>
  <div class="plaza-page">
    <header class="plaza-header">
      <h1>{{ t('模板广场') }}</h1>
      <p>{{ t('从广场复制模板到你名下，得到可编辑副本；原件只读，不受影响。') }}</p>
    </header>

    <div class="plaza-filters">
      <button :class="{ active: assetType === 'all' }" @click="setType('all')">{{ t('全部') }}</button>
      <button :class="{ active: assetType === 'employee_template' }" @click="setType('employee_template')">{{ t('员工模板') }}</button>
      <button :class="{ active: assetType === 'sop_template' }" @click="setType('sop_template')">{{ t('SOP 模板') }}</button>
    </div>

    <p v-if="loading" class="plaza-hint">{{ t('加载中…') }}</p>
    <p v-else-if="error" class="plaza-error">{{ error }}</p>
    <p v-else-if="filtered.length === 0" class="plaza-hint">{{ t('暂无模板') }}</p>

    <ul v-else class="plaza-grid">
      <li v-for="item in filtered" :key="item.template_id" class="plaza-card">
        <div class="plaza-card-head">
          <span class="plaza-type">{{ typeLabels[item.asset_type] || item.asset_type }}</span>
          <span class="plaza-version">v{{ item.version }}</span>
        </div>
        <h3>{{ item.name }}</h3>
        <p class="plaza-desc">{{ item.description || '（无描述）' }}</p>
        <div class="plaza-meta">
          <span>上架者：{{ item.owner_id || '—' }}</span>
          <span>分类：{{ item.category || '未分类' }}</span>
        </div>
        <button class="plaza-clone" @click="cloneHint">{{ t('复制到我的') }}</button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.plaza-page {
  max-width: 1080px;
  margin: 0 auto;
  padding: 32px 24px;
}
.plaza-header h1 {
  font-size: 28px;
  margin: 0 0 8px;
}
.plaza-header p {
  color: #888;
  margin: 0 0 24px;
}
.plaza-filters {
  display: flex;
  gap: 8px;
  margin-bottom: 24px;
}
.plaza-filters button {
  padding: 6px 14px;
  border: 1px solid #ddd;
  border-radius: 6px;
  background: #fff;
  cursor: pointer;
}
.plaza-filters button.active {
  background: #1677ff;
  color: #fff;
  border-color: #1677ff;
}
.plaza-hint {
  color: #888;
}
.plaza-error {
  color: #d03050;
}
.plaza-grid {
  list-style: none;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}
.plaza-card {
  border: 1px solid #eee;
  border-radius: 10px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.plaza-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.plaza-type {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
  background: #e6f4ff;
  color: #1677ff;
}
.plaza-version {
  font-size: 12px;
  color: #888;
}
.plaza-card h3 {
  margin: 0;
  font-size: 16px;
}
.plaza-desc {
  color: #666;
  font-size: 13px;
  min-height: 36px;
}
.plaza-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
  color: #999;
}
.plaza-clone {
  margin-top: auto;
  padding: 8px;
  border: none;
  border-radius: 6px;
  background: #1677ff;
  color: #fff;
  cursor: pointer;
}
</style>
