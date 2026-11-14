<script setup lang="ts">
import { t } from '@/composables/i18n';
import { h, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { NAlert, NCard, NDataTable, NEmpty, NSpin, NTag, NSpace } from 'naive-ui';
import {
  fetchApprovalTodos,
  type ApprovalSourceType,
  type ApprovalTodo,
} from '@/api/approvals';

const router = useRouter();
const loading = ref(false);
const errorMsg = ref('');
const items = ref<ApprovalTodo[]>([]);
const kernelEnabled = ref(false);
const shadowOnly = ref(false);

const sourceTypeLabel: Record<ApprovalSourceType, string> = {
  tool: '工具审批',
  portal: '申领审批',
  sop: 'SOP 运行',
};
const sourceTypeType: Record<ApprovalSourceType, 'info' | 'warning' | 'success'> = {
  tool: 'info',
  portal: 'warning',
  sop: 'success',
};
const stateLabel: Record<string, string> = {
  pending: '待审批',
  approved: '已批准',
  denied: '已驳回',
  cancelled: '已取消',
};

const columns = [
  {
    title: '来源',
    key: 'sourceType',
    render: (row: ApprovalTodo) =>
      h(
        NTag,
        { size: 'small', bordered: false, type: sourceTypeType[row.sourceType] || 'default' },
        { default: () => sourceTypeLabel[row.sourceType] || row.sourceType },
      ),
  },
  { title: '来源 ID', key: 'sourceId' },
  { title: '审批人', key: 'approverId' },
  { title: '截止时间', key: 'deadline' },
  {
    title: '状态',
    key: 'state',
    render: (row: ApprovalTodo) =>
      h(NTag, { size: 'small', bordered: false }, { default: () => stateLabel[row.state] || row.state }),
  },
  {
    title: '操作',
    key: 'actions',
    render: (row: ApprovalTodo) =>
      h(NSpace, { size: 4 }, { default: () => [h('a', { onClick: () => openDetail(row) }, '查看')] }),
  },
];

async function load() {
  loading.value = true;
  errorMsg.value = '';
  try {
    const res = await fetchApprovalTodos({ status: 'all' });
    items.value = res.items || [];
    kernelEnabled.value = res.kernelEnabled;
    shadowOnly.value = res.shadowOnly;
  } catch (e: any) {
    errorMsg.value = e?.message || '加载失败';
  } finally {
    loading.value = false;
  }
}

function openDetail(row: ApprovalTodo) {
  if (row.runId) {
    router.push({ path: '/orchestration/runs', query: { runId: row.runId } });
  } else if (row.sourceType === 'portal') {
    router.push('/assets/approvals');
  }
}

onMounted(load);
</script>

<template>
  <div class="approval-center">
    <NAlert
      v-if="!kernelEnabled"
      type="info"
      :show-icon="true"
      style="margin-bottom: 12px"
    >{{ t('统一审批内核（056）当前为灰度只读视图：开关') }}<code>APPROVAL_KERNEL_ENABLED</code>{{ t('已开启，待办由 R-7 旁路双写产生；若列表为空，说明暂无影子票据。') }}</NAlert>
    <NCard :title="t('审批中心 · 统一待办')" :bordered="false">
      <NSpin :show="loading">
        <NDataTable
          :columns="columns"
          :data="items"
          :row-key="(row: ApprovalTodo) => row.ticketId"
          :pagination="{ pageSize: 20 }"
          :bordered="false"
        />
        <NEmpty
          v-if="!loading && items.length === 0"
          description="暂无待办"
          style="padding: 32px 0"
        />
      </NSpin>
      <p v-if="errorMsg" class="mg-error">{{ errorMsg }}</p>
    </NCard>
  </div>
</template>
