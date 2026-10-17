<template>
  <div class="page-stack ontology-page">
    <header class="page-head">
      <div class="head-text">
        <h1>{{ t('ontology_grant.title') }}</h1>
        <p class="muted">{{ t('ontology_grant.subtitle') }}</p>
      </div>
      <n-button quaternary :loading="loading" @click="load">
        <template #icon>
          <n-icon><RefreshOutline /></n-icon>
        </template>
        {{ t('ontology_grant.refresh') }}
      </n-button>
    </header>

    <n-alert v-if="degraded" type="warning" :bordered="false" closable>
      {{ t('ontology_grant.degraded') }}
    </n-alert>

    <n-alert v-else-if="!loading && !grants.length" type="info" :bordered="false">
      {{ t('ontology_grant.empty') }}
    </n-alert>

    <n-alert v-else-if="disabledCount > 0" type="warning" :bordered="false">
      {{ t('ontology_grant.disabled_hint', { count: disabledCount }) }}
    </n-alert>

    <n-card :bordered="false" embedded>
      <n-spin :show="loading">
        <n-data-table
          v-if="grants.length"
          :columns="columns"
          :data="grants"
          :bordered="false"
          size="small"
          :paginate-single-page="false"
          :pagination="pagination"
        />
        <n-empty v-else-if="!loading && !degraded" :description="t('ontology_grant.empty')" />
      </n-spin>
    </n-card>

    <p class="footnote muted">
      {{ t('ontology_grant.footnote') }}
    </p>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { NAlert, NButton, NCard, NDataTable, NEmpty, NIcon, NSpin, NTag, useMessage, type DataTableColumns } from 'naive-ui'
import RefreshOutline from '@vicons/ionicons5/es/RefreshOutline'
import { t } from '../composables/i18n'
import {
  fetchMyOntologyGrants,
  type MyOntologyGrant,
  type OntologyAccessMode,
} from '../api/ontologyGrants'

const props = defineProps<{ back?: () => void }>()
defineEmits<{ back: [] }>()

const message = useMessage()
const loading = ref(false)
const grants = ref<MyOntologyGrant[]>([])
const degraded = ref(false)
const disabledCount = ref(0)

const pagination = { pageSize: 20, showSizePicker: true, pageSizes: [10, 20, 50] }

const modeLabel = (mode: OntologyAccessMode) => {
  if (mode === 'write') return t('ontology_grant.mode_write')
  if (mode === 'read') return t('ontology_grant.mode_read')
  return t('ontology_grant.mode_none')
}

const modeTagType = (mode: OntologyAccessMode) => {
  if (mode === 'write') return 'warning'
  if (mode === 'read') return 'success'
  return 'default'
}

const columns: DataTableColumns<MyOntologyGrant> = [
  {
    title: t('ontology_grant.column_ontology'),
    key: 'ontologyId',
    render: row => h('strong', row.ontologyId),
  },
  {
    title: t('ontology_grant.column_mode'),
    key: 'accessMode',
    width: 140,
    render: row =>
      h(NTag, { type: modeTagType(row.accessMode), size: 'small', bordered: false }, { default: () => modeLabel(row.accessMode) }),
  },
  {
    title: t('ontology_grant.column_source'),
    key: 'subjectType',
    width: 160,
    render: row =>
      row.subjectType === 'tenant' ? t('ontology_grant.source_tenant') : t('ontology_grant.source_user'),
  },
  {
    title: t('ontology_grant.column_visible'),
    key: 'visible',
    width: 110,
    render: row => (row.visible ? t('ontology_grant.yes') : t('ontology_grant.no')),
  },
  {
    title: t('ontology_grant.column_priority'),
    key: 'priority',
    width: 100,
  },
  {
    title: t('ontology_grant.column_updated'),
    key: 'updatedAt',
    width: 190,
    render: row => (row.updatedAt ? new Date(row.updatedAt).toLocaleString() : '--'),
  },
]

async function load() {
  loading.value = true
  try {
    const data = await fetchMyOntologyGrants()
    grants.value = data.ontologies
    degraded.value = data.degraded
    disabledCount.value = data.disabledCount
  } catch (error: any) {
    degraded.value = true
    grants.value = []
    message.error(error?.response?.data?.detail || error?.message || t('ontology_grant.load_failed'))
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.ontology-page {
  display: grid;
  gap: 14px;
  align-content: start;
  padding: 20px;
  height: 100%;
  overflow: auto;
}
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.head-text h1 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}
.head-text p {
  margin: 4px 0 0;
  font-size: 12px;
}
.muted {
  color: #667085;
}
.footnote {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
}
@media (max-width: 860px) {
  .page-head {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
