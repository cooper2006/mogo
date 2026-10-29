<template>
  <div class="portal-my-requests">
    <header class="list-head">
      <n-space align="center" :size="8">
        <n-select
          v-model:value="statusFilter"
          :options="statusOptions"
          size="small"
          style="width: 160px"
          :placeholder="t('portal.request.all_status')"
          clearable
          @update:value="load"
        />
        <span class="mg-caption">{{ t('portal.request.count', { count: total }) }}</span>
      </n-space>
      <n-button quaternary size="small" :loading="loading" @click="load">{{ t('ui.refresh') }}</n-button>
    </header>

    <n-alert v-if="error" type="error" :bordered="false">{{ error }}</n-alert>

    <n-spin :show="loading">
      <n-data-table
        v-if="items.length"
        :columns="columns"
        :data="items"
        :bordered="false"
        size="small"
        :pagination="false"
      />
      <n-empty v-else-if="!loading && !error" :description="t('portal.request.empty')" />
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import { NAlert, NButton, NDataTable, NEmpty, NSelect, NSpace, NSpin, NTag, useDialog, useMessage, type DataTableColumns } from 'naive-ui'
import { useI18n } from '@/composables/i18n'
import { formatAppDateTime } from '@/composables/appTimezone'
import {
  fetchMyPortalRequests,
  revokeMyPortalRequest,
  type PortalAssetType,
  type PortalMyRequest,
  type PortalRequestStatus,
} from '../../api/portal'

const emit = defineEmits<{ open: [assetType: PortalAssetType, assetKey: string]; changed: [] }>()

const { t } = useI18n()
const message = useMessage()
const dialog = useDialog()
const loading = ref(false)
const error = ref('')
const items = ref<PortalMyRequest[]>([])
const total = ref(0)
const statusFilter = ref<PortalRequestStatus | null>(null)

const statusOptions = (['applied', 'granted', 'rejected', 'revoked', 'expired'] as PortalRequestStatus[]).map(value => ({
  label: t(`portal.status.${value}`),
  value,
}))

const statusTagType = (status: string) => {
  if (status === 'granted') return 'success'
  if (status === 'applied' || status === 'approved') return 'info'
  if (status === 'rejected') return 'error'
  if (status === 'revoked') return 'warning'
  return 'default'
}

const formatTime = (value?: string | null) => (value ? formatAppDateTime(value) : t('portal.d.missing'))

function revoke(row: PortalMyRequest) {
  dialog.warning({
    title: t('portal.revoke'),
    content: t('portal.request.confirm_revoke', { name: row.asset_name || row.asset_key }),
    positiveText: t('portal.request.revoke_confirm'),
    negativeText: t('ui.cancel'),
    onPositiveClick: async () => {
      try {
        await revokeMyPortalRequest(row.request_id, t('portal.request.revoke_reason'))
        message.success(t('portal.request.revoke_success'))
        await load()
        emit('changed')
      } catch (err: any) {
        message.error(err?.response?.data?.detail || t('portal.operation_failed'))
      }
    },
  })
}

const columns: DataTableColumns<PortalMyRequest> = [
  {
    title: t('portal.request.column.asset'),
    key: 'asset_name',
    render: row =>
      h(
        NButton,
        { text: true, type: 'primary', onClick: () => emit('open', row.asset_type, row.asset_key) },
        { default: () => row.asset_name || row.asset_key },
      ),
  },
  {
    title: t('portal.request.column.status'),
    key: 'status',
    width: 130,
    render: row =>
      h(NTag, { type: statusTagType(row.status), size: 'small', bordered: false }, { default: () => t(`portal.status.${row.status}`) }),
  },
  { title: t('portal.request.column.applied'), key: 'applied_at', width: 180, render: row => formatTime(row.applied_at) },
  { title: t('portal.request.column.granted'), key: 'granted_at', width: 180, render: row => formatTime(row.granted_at) },
  { title: t('portal.request.column.expires'), key: 'expires_at', width: 180, render: row => formatTime(row.expires_at) },
  { title: t('portal.request.column.reason'), key: 'reason', render: row => row.decided_reason || row.reason || t('portal.d.missing') },
  {
    title: t('portal.request.column.actions'),
    key: 'actions',
    width: 100,
    render: row =>
      row.status === 'granted'
        ? h(NButton, { size: 'tiny', quaternary: true, type: 'warning', onClick: () => revoke(row) }, { default: () => t('portal.request.revoke_confirm') })
        : null,
  },
]

async function load() {
  loading.value = true
  error.value = ''
  try {
    const page = await fetchMyPortalRequests({ status: statusFilter.value || '', pageSize: 50 })
    items.value = page.items
    total.value = page.total
  } catch (err: any) {
    error.value = err?.response?.data?.detail || t('portal.request.load_failed')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--mg-space-3);
  margin-bottom: var(--mg-space-3);
}
</style>
