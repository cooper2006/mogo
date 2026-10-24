<template>
  <div class="portal-my-requests">
    <header class="list-head">
      <n-space align="center" :size="8">
        <n-select
          v-model:value="statusFilter"
          :options="statusOptions"
          size="small"
          style="width: 160px"
          placeholder="全部状态"
          clearable
          @update:value="load"
        />
        <span class="muted">{{ total }} 条申领记录</span>
      </n-space>
      <n-button quaternary size="small" :loading="loading" @click="load">刷新</n-button>
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
      <n-empty v-else-if="!loading && !error" description="还没有申领记录，去目录里挑一个资产吧" />
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import { NAlert, NButton, NDataTable, NEmpty, NSelect, NSpace, NSpin, NTag, useDialog, useMessage, type DataTableColumns } from 'naive-ui'
import {
  fetchMyPortalRequests,
  portalStatusLabel,
  revokeMyPortalRequest,
  type PortalAssetType,
  type PortalMyRequest,
  type PortalRequestStatus,
} from '../../api/portal'

const emit = defineEmits<{ open: [assetType: PortalAssetType, assetKey: string]; changed: [] }>()

const message = useMessage()
const dialog = useDialog()
const loading = ref(false)
const error = ref('')
const items = ref<PortalMyRequest[]>([])
const total = ref(0)
const statusFilter = ref<PortalRequestStatus | null>(null)

const statusOptions = (['applied', 'granted', 'rejected', 'revoked', 'expired'] as PortalRequestStatus[]).map(value => ({
  label: portalStatusLabel(value),
  value,
}))

const statusTagType = (status: string) => {
  if (status === 'granted') return 'success'
  if (status === 'applied' || status === 'approved') return 'info'
  if (status === 'rejected') return 'error'
  if (status === 'revoked') return 'warning'
  return 'default'
}

const formatTime = (value?: string | null) => (value ? new Date(value).toLocaleString() : '--')

function revoke(row: PortalMyRequest) {
  dialog.warning({
    title: '放弃使用',
    content: `确认放弃「${row.asset_name || row.asset_key}」的使用权限？放弃后需要重新申领。`,
    positiveText: '确认放弃',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await revokeMyPortalRequest(row.request_id, '用户主动放弃')
        message.success('已放弃使用权限。')
        await load()
        emit('changed')
      } catch (err: any) {
        message.error(err?.response?.data?.detail || '操作失败，请稍后重试。')
      }
    },
  })
}

const columns: DataTableColumns<PortalMyRequest> = [
  {
    title: '资产',
    key: 'asset_name',
    render: row =>
      h(
        NButton,
        { text: true, type: 'primary', onClick: () => emit('open', row.asset_type, row.asset_key) },
        { default: () => row.asset_name || row.asset_key },
      ),
  },
  {
    title: '状态',
    key: 'status',
    width: 130,
    render: row =>
      h(NTag, { type: statusTagType(row.status), size: 'small', bordered: false }, { default: () => portalStatusLabel(row.status) }),
  },
  { title: '申请时间', key: 'applied_at', width: 180, render: row => formatTime(row.applied_at) },
  { title: '开通时间', key: 'granted_at', width: 180, render: row => formatTime(row.granted_at) },
  { title: '到期时间', key: 'expires_at', width: 180, render: row => formatTime(row.expires_at) },
  { title: '备注', key: 'reason', render: row => row.decided_reason || row.reason || '--' },
  {
    title: '操作',
    key: 'actions',
    width: 100,
    render: row =>
      row.status === 'granted'
        ? h(NButton, { size: 'tiny', quaternary: true, type: 'warning', onClick: () => revoke(row) }, { default: () => '放弃' })
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
    error.value = err?.response?.data?.detail || '加载我的申领失败，请稍后重试。'
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
  gap: 12px;
  margin-bottom: 12px;
}
</style>
