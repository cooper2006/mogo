<script setup lang="ts">
import { t } from '@/composables/i18n';
import { computed, h, onMounted, reactive, ref } from 'vue';
import { NButton, NCard, NDataTable, NInput, NSelect, NSpace, NTag, type DataTableColumns } from 'naive-ui';
import PageIntro from '@/components/PageIntro.vue';
import { formatAdminDateTime } from '@/composables/adminTimezone';
import {
  fetchSandboxExecutions,
  type SandboxExecutionRecord,
} from '@/api/sandboxExecutions';

const loading = ref(false);
const rows = ref<SandboxExecutionRecord[]>([]);
const errorMsg = ref('');
const degraded = ref(false);

const filters = reactive({
  agent_id: '',
  status: '',
  page: 1,
  pageSize: 20,
});
const total = ref(0);

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: 'success（成功）', value: 'success' },
  { label: 'rejected（拒绝）', value: 'rejected' },
  { label: 'error（失败）', value: 'error' },
];

async function load() {
  loading.value = true;
  errorMsg.value = '';
  degraded.value = false;
  try {
    const data = await fetchSandboxExecutions({
      page: filters.page,
      page_size: filters.pageSize,
      agent_id: filters.agent_id.trim() || undefined,
      status: filters.status || undefined,
    });
    rows.value = data.items;
    total.value = data.total;
    degraded.value = Boolean(data.degraded);
  } catch (e) {
    errorMsg.value = String(e);
  } finally {
    loading.value = false;
  }
}

function search() {
  filters.page = 1;
  void load();
}

function statusType(row: SandboxExecutionRecord) {
  if (row.rejected) return 'warning';
  if (row.status === 'success') return 'success';
  if (row.status === 'error') return 'error';
  return 'default';
}

function statusLabel(row: SandboxExecutionRecord) {
  if (row.rejected) return 'rejected';
  return row.status || '—';
}

function durationOf(row: SandboxExecutionRecord) {
  const ms = row.duration_ms || 0;
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`;
}

const pagination = computed(() => ({
  page: filters.page,
  pageSize: filters.pageSize,
  itemCount: total.value,
  showSizePicker: true,
  pageSizes: [20, 50, 100],
}));

function onPageChange(page: number) {
  filters.page = page;
  void load();
}

function onPageSizeChange(pageSize: number) {
  filters.pageSize = pageSize;
  filters.page = 1;
  void load();
}

const columns = computed<DataTableColumns<SandboxExecutionRecord>>(() => [
  {
    title: t('完成时间'),
    key: 'finished_at',
    width: 175,
    render: (row) => formatAdminDateTime(row.finished_at, '-'),
  },
  {
    title: t('Agent'),
    key: 'agent_id',
    width: 130,
    render: (row) => row.agent_id || '—',
  },
  {
    title: t('状态'),
    key: 'status',
    width: 120,
    render: (row) =>
      h(NTag, { size: 'small', type: statusType(row) }, () => statusLabel(row)),
  },
  {
    title: t('退出码'),
    key: 'exit_code',
    width: 90,
    render: (row) => (row.exit_code === null || row.exit_code === undefined ? '—' : String(row.exit_code)),
  },
  {
    title: t('耗时'),
    key: 'duration_ms',
    width: 100,
    render: (row) => durationOf(row),
  },
  {
    title: t('镜像'),
    key: 'image_ref',
    minWidth: 220,
    render: (row) => row.image_ref || '—',
  },
  {
    title: t('调用 ID'),
    key: 'call_id',
    width: 160,
    render: (row) => row.call_id || '—',
  },
]);

onMounted(load);
</script>

<template>
  <div class="page-container">
    <PageIntro
      :title="t('Sandbox 执行记录')"
      description="运行时沙箱代码执行（每一步 call）的审计轨迹：agent、退出码、耗时、镜像与拒绝状态。"
      :tags="['③ 执行隔离', '审计']"
    />
    <NCard size="small">
      <NSpace align="center" style="margin-bottom: 12px">
        <NInput
          v-model:value="filters.agent_id"
          :placeholder="t('按 Agent ID 过滤')"
          style="width: 220px"
          clearable
          @keyup.enter="search"
          @clear="search"
        />
        <NSelect v-model:value="filters.status" :options="statusOptions" style="width: 170px" @update:value="search" />
        <NButton size="small" type="primary" @click="search">{{ t('查询') }}</NButton>
      </NSpace>

      <p v-if="errorMsg" style="color: #d03050">{{ errorMsg }}</p>
      <p v-else-if="degraded" style="color: #f0a020">
        {{ t('数据库暂不可用，以下为降级空视图（非真实无记录）。') }}
      </p>

      <NDataTable
        :columns="columns"
        :data="rows"
        :loading="loading"
        :row-key="(row: SandboxExecutionRecord) => row.record_id"
        :pagination="pagination"
        :remote="true"
        size="small"
        @update:page="onPageChange"
        @update:page-size="onPageSizeChange"
      />
      <p v-if="!loading && !errorMsg && !degraded && rows.length === 0" style="color: #888">
        {{ t('暂无执行记录。') }}
      </p>
    </NCard>
  </div>
</template>
<style scoped>
.page-container {
  height: 100%;
  min-height: 0;
}
</style>
