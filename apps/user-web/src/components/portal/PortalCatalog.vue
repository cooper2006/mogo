<template>
  <div class="page-stack portal-page">
    <header class="page-head">
      <div class="head-text">
        <h1>资产门户</h1>
        <p class="muted">浏览本租户已上架的技能与能力资产，一键申领使用权限；审批通过后立即生效。</p>
      </div>
      <n-space :size="8">
        <n-button quaternary :loading="loading" @click="load">刷新</n-button>
      </n-space>
    </header>

    <n-tabs v-model:value="tab" type="segment" animated>
      <n-tab-pane name="catalog" tab="资产目录">
        <div class="catalog-filters">
          <n-input
            v-model:value="keyword"
            placeholder="搜索资产名称 / 描述 / 标签"
            clearable
            style="max-width: 320px"
            @keyup.enter="load"
            @clear="load"
          />
          <n-select
            v-model:value="category"
            :options="categoryOptions"
            placeholder="全部分类"
            clearable
            style="width: 180px"
            @update:value="load"
          />
          <n-select
            v-model:value="assetType"
            :options="assetTypeOptions"
            placeholder="全部类型"
            clearable
            style="width: 160px"
          />
          <n-button type="primary" secondary @click="load">搜索</n-button>
        </div>

        <n-alert v-if="error" type="error" :bordered="false">{{ error }}</n-alert>

        <n-spin :show="loading">
          <n-grid v-if="filteredItems.length" :cols="gridCols" :x-gap="12" :y-gap="12" responsive="screen">
            <n-gi v-for="item in filteredItems" :key="`${item.asset_type}:${item.asset_key}`">
              <n-card :bordered="false" embedded size="small" class="catalog-card" hoverable @click="openDetail(item)">
                <div class="card-head">
                  <strong>{{ item.name }}</strong>
                  <n-tag size="tiny" :bordered="false">{{ item.asset_type === 'skill' ? '技能' : '能力' }}</n-tag>
                </div>
                <p class="card-desc muted">{{ item.description || '暂无描述' }}</p>
                <div class="card-meta">
                  <n-tag size="tiny" :bordered="false">{{ item.category || '未分类' }}</n-tag>
                  <n-tag v-if="item.rating" size="tiny" type="info" :bordered="false">{{ item.rating.level }}</n-tag>
                  <n-tag v-if="item.is_low_quality" size="tiny" type="warning" :bordered="false">低质量</n-tag>
                  <span v-if="item.owner" class="muted">负责人 {{ item.owner }}</span>
                </div>
                <div v-if="item.effect?.effect_score != null" class="card-effect muted">
                  效果分 {{ Number(item.effect.effect_score).toFixed(2) }}
                  <template v-if="item.effect.samples">（{{ item.effect.samples }} 次样本）</template>
                </div>
              </n-card>
            </n-gi>
          </n-grid>
          <n-empty v-else-if="!loading && !error" description="没有匹配的资产，换个关键词试试" />
        </n-spin>

        <p v-if="total > pageSize" class="footnote muted">
          共 {{ total }} 个资产，当前展示前 {{ pageSize }} 个，请用搜索 / 分类缩小范围。
        </p>
      </n-tab-pane>

      <n-tab-pane name="mine" tab="我的申领">
        <MyRequests @open="openDetailByKey" @changed="markDirty" />
      </n-tab-pane>
    </n-tabs>

    <n-modal
      v-model:show="detailVisible"
      preset="card"
      :bordered="false"
      style="width: 720px; max-width: 92vw"
      :title="'资产详情'"
    >
      <PortalDetail
        v-if="activeAsset"
        :asset-type="activeAsset.asset_type"
        :asset-key="activeAsset.asset_key"
        @close="detailVisible = false"
        @changed="markDirty"
      />
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { NAlert, NButton, NCard, NEmpty, NGi, NGrid, NInput, NModal, NSelect, NSpace, NSpin, NTabPane, NTabs, NTag } from 'naive-ui'
import { fetchPortalCatalog, fetchPortalCategories, type PortalAssetType, type PortalCatalogItem, type PortalCategory } from '../../api/portal'
import PortalDetail from './PortalDetail.vue'
import MyRequests from './MyRequests.vue'

const PAGE_SIZE = 60

const tab = ref<'catalog' | 'mine'>('catalog')
const loading = ref(false)
const error = ref('')
const items = ref<PortalCatalogItem[]>([])
const total = ref(0)
const pageSize = PAGE_SIZE
const keyword = ref('')
const category = ref<string | null>(null)
const assetType = ref<PortalAssetType | null>(null)
const categories = ref<PortalCategory[]>([])
const detailVisible = ref(false)
const activeAsset = ref<PortalCatalogItem | null>(null)
const dirty = ref(false)

const categoryOptions = computed(() =>
  categories.value.map(entry => ({
    label: `${entry.category === 'uncategorized' ? '未分类' : entry.category}（${entry.count}）`,
    value: entry.category,
  })),
)

const assetTypeOptions = [
  { label: '技能', value: 'skill' },
  { label: '能力资产', value: 'capability_asset' },
]

/** 类型是本页面前端筛选（后端目录接口按资产类型混合返回）。 */
const filteredItems = computed(() =>
  assetType.value ? items.value.filter(item => item.asset_type === assetType.value) : items.value,
)

const gridCols = '1 s:2 m:3 l:4'

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [page, cats] = await Promise.all([
      fetchPortalCatalog({ keyword: keyword.value.trim(), category: category.value || '', pageSize: PAGE_SIZE }),
      fetchPortalCategories().catch(() => [] as PortalCategory[]),
    ])
    items.value = page.items
    total.value = page.total
    categories.value = cats
    dirty.value = false
  } catch (err: any) {
    error.value = err?.response?.data?.detail || '加载门户目录失败，请稍后重试。'
  } finally {
    loading.value = false
  }
}

function openDetail(item: PortalCatalogItem) {
  activeAsset.value = item
  detailVisible.value = true
}

function openDetailByKey(assetTypeValue: PortalAssetType, assetKey: string) {
  activeAsset.value = { asset_type: assetTypeValue, asset_key: assetKey } as PortalCatalogItem
  detailVisible.value = true
}

function markDirty() {
  dirty.value = true
  // 审批 / 回收会改变“已开通”状态，关闭弹层后下次切换 tab 重新拉取。
}

onMounted(load)

defineExpose({ reload: load, isDirty: () => dirty.value })
</script>

<style scoped>
.portal-page {
  padding: 16px;
}
.catalog-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.catalog-card {
  cursor: pointer;
  height: 100%;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.card-desc {
  margin: 6px 0 8px;
  font-size: 12px;
  min-height: 32px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.card-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 12px;
}
.card-effect {
  margin-top: 6px;
  font-size: 12px;
}
.footnote {
  margin-top: 12px;
  font-size: 12px;
}
</style>
