<template>
  <div class="mg-page portal-page">
    <header class="mg-page-head">
      <div class="mg-page-head__text">
        <h1 class="mg-page-title">{{ t('portal.title') }}</h1>
        <p class="mg-page-desc">{{ t('portal.subtitle') }}</p>
      </div>
      <n-space :size="8">
        <n-button quaternary :loading="loading" @click="load">{{ t('ui.refresh') }}</n-button>
      </n-space>
    </header>

    <n-tabs v-model:value="tab" type="segment" animated>
      <n-tab-pane name="catalog" :tab="t('portal.tab.catalog')">
        <div class="catalog-filters">
          <n-input
            v-model:value="keyword"
            :placeholder="t('portal.search_placeholder')"
            clearable
            style="max-width: 320px"
            @keyup.enter="load"
            @clear="load"
          />
          <n-select
            v-model:value="category"
            :options="categoryOptions"
            :placeholder="t('portal.filter.category')"
            clearable
            style="width: 180px"
            @update:value="load"
          />
          <n-select
            v-model:value="assetType"
            :options="assetTypeOptions"
            :placeholder="t('portal.filter.type')"
            clearable
            style="width: 160px"
          />
          <n-button type="primary" secondary @click="load">{{ t('portal.search') }}</n-button>
        </div>

        <n-alert v-if="error" type="error" :bordered="false">{{ error }}</n-alert>

        <n-spin :show="loading">
          <n-grid v-if="filteredItems.length" :cols="gridCols" :x-gap="12" :y-gap="12" responsive="screen">
            <n-gi v-for="item in filteredItems" :key="`${item.asset_type}:${item.asset_key}`">
              <n-card
                :bordered="false"
                embedded
                size="small"
                class="catalog-card"
                hoverable
                @click="openDetail(item)"
              >
                <div class="card-head">
                  <strong>{{ item.name }}</strong>
                  <n-tag size="tiny" :bordered="false">
                    {{ item.asset_type === 'skill' ? t('portal.type.skill') : t('portal.type.capability') }}
                  </n-tag>
                </div>
                <p class="card-desc mg-text-3">{{ item.description || t('portal.no_description') }}</p>
                <div class="card-meta">
                  <n-tag size="tiny" :bordered="false">{{ item.category === 'uncategorized' ? t('portal.category.uncategorized') : item.category }}</n-tag>
                  <n-tag v-if="item.rating" size="tiny" type="info" :bordered="false">
                    {{ t('portal.rating', { level: item.rating.level }) }}
                  </n-tag>
                  <n-tag v-if="item.is_low_quality" size="tiny" type="warning" :bordered="false">{{ t('portal.low_quality') }}</n-tag>
                  <span v-if="item.owner" class="mg-text-3">{{ t('portal.owner', { name: item.owner }) }}</span>
                </div>
                <div v-if="item.effect?.effect_score != null" class="card-effect mg-text-3">
                  {{ t('portal.effect_score', { score: Number(item.effect.effect_score).toFixed(2) }) }}
                  <template v-if="item.effect.samples">{{ t('portal.effect_samples', { count: item.effect.samples }) }}</template>
                </div>
              </n-card>
            </n-gi>
          </n-grid>
          <n-empty v-else-if="!loading && !error" :description="t('portal.empty')" />
        </n-spin>

        <p v-if="total > pageSize" class="footnote mg-caption">
          {{ t('portal.page_total', { total, pageSize }) }}
        </p>
      </n-tab-pane>

      <n-tab-pane name="mine" :tab="t('portal.tab.mine')">
        <MyRequests @open="openDetailByKey" @changed="markDirty" />
      </n-tab-pane>
    </n-tabs>

    <n-modal
      v-model:show="detailVisible"
      preset="card"
      :bordered="false"
      style="width: 720px; max-width: 92vw"
      :title="t('portal.detail_title')"
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
import { useI18n } from '@/composables/i18n'
import { fetchPortalCatalog, fetchPortalCategories, type PortalAssetType, type PortalCatalogItem, type PortalCategory } from '../../api/portal'
import PortalDetail from './PortalDetail.vue'
import MyRequests from './MyRequests.vue'

const { t } = useI18n()
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
    label: `${entry.category === 'uncategorized' ? t('portal.category.uncategorized') : entry.category}（${entry.count}）`,
    value: entry.category,
  })),
)

const assetTypeOptions = [
  { label: t('portal.type.skill'), value: 'skill' },
  { label: t('portal.type.capability'), value: 'capability_asset' },
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
    error.value = err?.response?.data?.detail || t('portal.load_failed')
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
/* 页面骨架 / 文本层级 / 卡片表面均由 src/styles/base.css 的语义类提供，
   此处只保留目录页特有的布局与交互，颜色一律引用设计令牌。 */
.portal-page {
  height: 100%;
  min-height: 0;
  overflow: auto;
}

.catalog-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--mg-space-2);
  margin-bottom: var(--mg-space-3);
}

.catalog-card {
  cursor: pointer;
  height: 100%;
  transition: box-shadow var(--mg-transition-base), border-color var(--mg-transition-base);
}

.catalog-card:hover {
  border-color: var(--mg-brand-soft-border);
  box-shadow: var(--mg-shadow-md);
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--mg-space-2);
}

.card-desc {
  margin: var(--mg-space-1) 0 var(--mg-space-2);
  font-size: var(--mg-font-size-xs);
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
  gap: var(--mg-space-1);
  font-size: var(--mg-font-size-xs);
}

.card-effect {
  margin-top: var(--mg-space-1);
  font-size: var(--mg-font-size-xs);
}

.footnote {
  margin-top: var(--mg-space-3);
  font-size: var(--mg-font-size-xs);
}
</style>
