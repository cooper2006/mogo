<script setup lang="ts">
import { t } from '@/composables/i18n';
import { computed, h, onMounted, ref, type VNodeChild } from 'vue';
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NEmpty,
  NInput,
  NModal,
  NSelect,
  NSpace,
  NTabPane,
  NTabs,
  NTag,
  useMessage,
  type DataTableColumns,
} from 'naive-ui';
import PageIntro from '@/components/PageIntro.vue';
import {
  decidePortalApproval,
  fetchPortalApprovals,
  portalStatusLabel,
  revokePortalGrant,
  type PortalApprovalItem,
  type PortalRequestStatus,
} from '@/api/portal';

const message = useMessage();

const tab = ref<'applied' | 'all'>('applied');
const loading = ref(false);
const errorMsg = ref('');
const rows = ref<PortalApprovalItem[]>([]);

// 决策弹层（批准 / 拒绝 / 回收共用 reason 输入）
const modalVisible = ref(false);
const modalMode = ref<'approve' | 'reject' | 'revoke'>('approve');
const target = ref<PortalApprovalItem | null>(null);
const reason = ref('');
const submitting = ref(false);

const statusOptions = [
  { label: t('全部'), value: 'all' },
  ...(['applied', 'granted', 'rejected', 'revoked', 'expired'] as PortalRequestStatus[]).map((value) => ({
    label: portalStatusLabel(value),
    value,
  })),
];
const filterStatus = ref<PortalRequestStatus | 'all'>('all');

const pendingCount = computed(() => rows.value.filter((row) => row.status === 'applied').length);

async function load() {
  loading.value = true;
  errorMsg.value = '';
  try {
    rows.value = await fetchPortalApprovals({ status: tab.value === 'applied' ? 'applied' : filterStatus.value });
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.detail || String(e);
  } finally {
    loading.value = false;
  }
}

function openModal(row: PortalApprovalItem, mode: 'approve' | 'reject' | 'revoke') {
  target.value = row;
  modalMode.value = mode;
  reason.value = '';
  modalVisible.value = true;
}

const modalTitle = computed(() => {
  if (modalMode.value === 'approve') return t('批准申领并开通');
  if (modalMode.value === 'reject') return t('拒绝申领');
  return t('回收已开通授权');
});

async function submit() {
  const row = target.value;
  if (!row) return;
  submitting.value = true;
  try {
    if (modalMode.value === 'revoke') {
      await revokePortalGrant(row.request_id, reason.value.trim());
      message.success(t('已回收，授权即时失效'));
    } else {
      const result = await decidePortalApproval(row.request_id, {
        approved: modalMode.value === 'approve',
        reason: reason.value.trim(),
      });
      if (!result.changed) {
        message.warning(t('该申领单已被处理，未重复执行'));
      } else if (result.status === 'granted') {
        message.success(t('已批准并开通 asset:use 授权'));
      } else if (result.status === 'rejected') {
        message.success(t('已拒绝申领'));
      }
    }
    modalVisible.value = false;
    await load();
  } catch (e: any) {
    const status = e?.response?.status;
    const detail = e?.response?.data?.detail;
    if (status === 403 && detail === 'self_approval_forbidden') message.error(t('不能审批自己提交的申领（防自审）'));
    else if (status === 403) message.error(t('缺少权限：需要 portal:approve'));
    else message.error(detail || t('操作失败'));
  } finally {
    submitting.value = false;
  }
}

const statusTagType = (status: string) => {
  if (status === 'granted') return 'success';
  if (status === 'applied' || status === 'approved') return 'info';
  if (status === 'rejected') return 'error';
  if (status === 'revoked') return 'warning';
  return 'default';
};

const columns: DataTableColumns<PortalApprovalItem> = [
  {
    title: t('资产'),
    key: 'asset_name',
    render: (row) => h('div', [h('strong', row.asset_name || row.asset_key), h('div', { class: 'text-xs text-gray-400' }, row.asset_key)]),
  },
  { title: t('申请人'), key: 'requester_id', width: 140 },
  {
    title: t('状态'),
    key: 'status',
    width: 110,
    render: (row) => h(NTag, { size: 'small', bordered: false, type: statusTagType(row.status) }, { default: () => portalStatusLabel(row.status) }),
  },
  { title: t('申领理由'), key: 'reason', render: (row) => row.reason || '--' },
  {
    title: t('申请时间'),
    key: 'applied_at',
    width: 180,
    render: (row) => (row.applied_at ? new Date(row.applied_at).toLocaleString() : '--'),
  },
  {
    title: t('到期时间'),
    key: 'expires_at',
    width: 180,
    render: (row) => (row.expires_at ? new Date(row.expires_at).toLocaleString() : '--'),
  },
  {
    title: t('操作'),
    key: 'actions',
    width: 200,
    render: (row) => {
      const actions: VNodeChild[] = [];
      if (row.status === 'applied' && row.can_decide) {
        actions.push(h(NButton, { size: 'tiny', type: 'primary', quaternary: true, onClick: () => openModal(row, 'approve') }, { default: () => t('批准') }));
        actions.push(h(NButton, { size: 'tiny', type: 'error', quaternary: true, onClick: () => openModal(row, 'reject') }, { default: () => t('拒绝') }));
      } else if (row.status === 'granted') {
        actions.push(h(NButton, { size: 'tiny', type: 'warning', quaternary: true, onClick: () => openModal(row, 'revoke') }, { default: () => t('回收') }));
      } else if (row.status === 'applied') {
        actions.push(h('span', { class: 'text-xs text-gray-400' }, t('不可审批（本人或权限不足）')));
      }
      return h(NSpace, { size: 4 }, { default: () => actions });
    },
  },
];

onMounted(load);
</script>

<template>
  <div class="p-4 space-y-4">
    <PageIntro
      :title="t('门户审批')"
      :description="t('审批员工的门户申领：批准即写入用户级 asset:use 授权并即时生效；拒绝 / 回收均留审计。不能审批自己提交的申领单。')"
    />

    <NAlert v-if="errorMsg" type="error" :bordered="false">{{ errorMsg }}</NAlert>

    <NCard :bordered="false" size="small">
      <template #header>
        <NSpace align="center" justify="space-between">
          <span>{{ t('审批队列') }}</span>
          <NSpace align="center" :size="8">
            <span class="text-xs text-gray-400">{{ t('待审批') }} {{ pendingCount }}</span>
            <NSelect v-if="tab === 'all'" v-model:value="filterStatus" :options="statusOptions" size="small" style="width: 150px" @update:value="load" />
            <NButton size="small" quaternary :loading="loading" @click="load">{{ t('刷新') }}</NButton>
          </NSpace>
        </NSpace>
      </template>

      <NTabs v-model:value="tab" type="line" animated @update:value="load">
        <NTabPane name="applied" :tab="t('待审批')" />
        <NTabPane name="all" :tab="t('全部申领单')" />
      </NTabs>

      <NDataTable v-if="rows.length" :columns="columns" :data="rows" :loading="loading" :bordered="false" size="small" :pagination="{ pageSize: 20 }" />
      <NEmpty v-else :description="tab === 'applied' ? t('没有待审批的申领') : t('没有申领记录')" />
    </NCard>

    <NModal v-model:show="modalVisible" preset="card" :title="modalTitle" style="width: 480px">
      <NSpace vertical :size="12">
        <div v-if="target" class="text-sm text-gray-600">
          {{ target.asset_name || target.asset_key }} · {{ target.requester_id }}
        </div>
        <NInput
          v-model:value="reason"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 4 }"
          maxlength="200"
          show-count
          :placeholder="modalMode === 'reject' || modalMode === 'revoke' ? t('填写原因（可选）') : t('审批备注（可选）')"
        />
        <NSpace justify="end">
          <NButton quaternary @click="modalVisible = false">{{ t('取消') }}</NButton>
          <NButton type="primary" :loading="submitting" @click="submit">{{ t('确认') }}</NButton>
        </NSpace>
      </NSpace>
    </NModal>
  </div>
</template>
