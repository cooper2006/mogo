<script setup lang="ts">
import { computed, h, onMounted, reactive, ref } from 'vue';
import { NButton, NCard, NDataTable, NInput, NSelect, NSpace, NTag, type DataTableColumns } from 'naive-ui';
import PageIntro from '@/components/PageIntro.vue';
import { formatAdminDateTime } from '@/composables/adminTimezone';
import { fetchEgressLogs, type EgressLogEntry } from '@/api/egress';

const loading = ref(false);
const rows = ref<EgressLogEntry[]>([]);
const errorMsg = ref('');

const filters = reactive({
  event: '',
  domain: '',
  page: 1,
  pageSize: 20,
});
const total = ref(0);

const eventOptions = [
  { label: '全部判定', value: '' },
  { label: 'allowed（放行）', value: 'egress.allowed' },
  { label: 'denied（拒绝）', value: 'egress.denied' },
];

async function load() {
  loading.value = true;
  errorMsg.value = '';
  try {
    const data = await fetchEgressLogs({
      page: filters.page,
      page_size: filters.pageSize,
      event: filters.event || undefined,
      domain: filters.domain.trim() || undefined,
    });
    rows.value = data.items;
    total.value = data.total;
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

function urlOf(row: EgressLogEntry) {
  return row.details?.url_safe || row.details?.domain || '—';
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

const columns = computed<DataTableColumns<EgressLogEntry>>(() => [
  {
    title: '时间',
    key: 'occurred_at',
    width: 175,
    render: (row) => formatAdminDateTime(row.occurred_at, '-'),
  },
  {
    title: '租户',
    key: 'tenant_id',
    width: 100,
    render: (row) => row.tenant_id,
  },
  {
    title: '工具/能力',
    key: 'capability',
    width: 140,
    render: (row) => row.details?.capability || '—',
  },
  {
    title: '目标 URL',
    key: 'url',
    minWidth: 200,
    render: (row) => urlOf(row),
  },
  {
    title: '判定结果',
    key: 'event',
    width: 130,
    render: (row) =>
      h(
        NTag,
        { size: 'small', type: row.event === 'egress.allowed' ? 'success' : 'error' },
        () => (row.event === 'egress.allowed' ? 'allowed' : 'denied'),
      ),
  },
  {
    title: '原因',
    key: 'reason',
    minWidth: 200,
    render: (row) => row.details?.reason || '—',
  },
]);

onMounted(load);
</script>

<template>
  <div class="page-container">
    <PageIntro
      title="出站审计日志"
      description="运行时出站判定（egress.allowed / egress.denied）的审计轨迹：未命中白名单的出站调用被拒并落此记录。"
      :tags="['038 出站沙箱', '审计']"
    />
    <NCard size="small">
      <NSpace align="center" style="margin-bottom: 12px">
        <NSelect v-model:value="filters.event" :options="eventOptions" style="width: 160px" @update:value="search" />
        <NInput
          v-model:value="filters.domain"
          placeholder="按域名过滤"
          style="width: 220px"
          clearable
          @keyup.enter="search"
          @clear="search"
        />
        <NButton size="small" type="primary" @click="search">查询</NButton>
      </NSpace>

      <p v-if="errorMsg" style="color: #d03050">{{ errorMsg }}</p>

      <NDataTable
        :columns="columns"
        :data="rows"
        :loading="loading"
        :row-key="(row: EgressLogEntry) => row.action_id || row.occurred_at"
        :pagination="pagination"
        :remote="true"
        size="small"
        @update:page="onPageChange"
        @update:page-size="onPageSizeChange"
      />
      <p v-if="!loading && !errorMsg && rows.length === 0" style="color: #888">暂无审计记录。</p>
    </NCard>
  </div>
</template>
<style scoped>
.page-container {
  height: 100%;
  min-height: 0;
}
</style>
