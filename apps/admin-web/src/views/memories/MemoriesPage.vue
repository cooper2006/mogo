<script setup lang="ts">
/**
 * 017 T026 — admin 跨范围记忆治理主页面（参考 SkillsPage / SystemAuditPage 范式）。
 * 指标卡 + 跨三范围列表 + 筛选/分页 + 批量 + 详情抽屉 + 提升审批 + T027 治理区块。
 * 不可见一律 404：加载/治理动作失败统一用 memoryErrorText 显示，不泄露内容（T030）。
 */
import { t } from '@/composables/i18n';
import { computed, h, onMounted, ref, watch } from 'vue';
import { NButton, NSpace, NTag, useDialog, useMessage, type DataTableColumns } from 'naive-ui';
import PageIntro from '@/components/PageIntro.vue';
import { formatAdminDateTime } from '@/composables/adminTimezone';
import MemoryDetailDrawer from './MemoryDetailDrawer.vue';
import MemoryApprovalDialog from './MemoryApprovalDialog.vue';
import MemoryGovernancePanels from './MemoryGovernancePanels.vue';
import {
  MEMORY_SCOPES,
  type MemoryItem,
  type MemoryScope,
  type MemoryStatus,
  type MemoryStats,
  type MemoryProjectView,
  fetchAdminMemories,
  fetchAdminMemoryStats,
  listAdminProjects,
  archiveAdminMemory,
  restoreAdminMemory,
  deleteAdminMemory,
  batchArchiveAdminMemories,
  memoryErrorText,
  normalizeMemoryError,
} from '@/api/memories';

const message = useMessage();
const dialog = useDialog();

const loading = ref(false);
const rows = ref<MemoryItem[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = 20;
const stats = ref<MemoryStats>({ total: 0, by_scope: {}, recent_added: 0, pending_approval: 0 });
const projects = ref<MemoryProjectView[]>([]);

const filters = ref<{ keyword: string; scope: MemoryScope | ''; tenant_id: string; status: MemoryStatus | '' }>({
  keyword: '', scope: '', tenant_id: '', status: '',
});
const checkedRowKeys = ref<string[]>([]);

const detailVisible = ref(false);
const detailRecord = ref<MemoryItem | null>(null);
const approvalVisible = ref(false);
const approvalRecord = ref<MemoryItem | null>(null);

const scopeOptions = [
  { label: t('全部范围'), value: '' },
  ...MEMORY_SCOPES.map((value) => ({ label: scopeLabel(value), value })),
];
const statusOptions = [
  { label: t('全部状态'), value: '' },
  { label: t('正常'), value: 'active' },
  { label: t('已归档'), value: 'archived' },
];

function scopeLabel(scope: MemoryScope | string): string {
  return ({ personal: t('个人'), project: t('项目'), department: t('部门') } as Record<string, string>)[scope] || scope;
}
function scopeTagType(scope: MemoryScope): 'default' | 'info' | 'warning' {
  return scope === 'department' ? 'warning' : scope === 'project' ? 'info' : 'default';
}

const metrics = computed(() => {
  const by = stats.value.by_scope || {};
  return [
    { label: t('记忆总量'), value: stats.value.total, hint: t('跨三范围') },
    { label: t('按范围分布'), value: `${by.personal ?? 0} / ${by.project ?? 0} / ${by.department ?? 0}`, hint: t('个人 / 项目 / 部门') },
    { label: t('近日新增'), value: stats.value.recent_added, hint: t('近 7 天') },
    { label: t('待审批'), value: stats.value.pending_approval, hint: t('范围提升申请'), danger: stats.value.pending_approval > 0 },
  ];
});

function openDetail(row: MemoryItem) { detailRecord.value = row; detailVisible.value = true; }
function openApproval(row: MemoryItem) { approvalRecord.value = row; approvalVisible.value = true; }

const columns: DataTableColumns<MemoryItem> = [
  { type: 'selection' },
  { title: t('范围'), key: 'scope', width: 100, render: (row) => h(NTag, { bordered: false, size: 'small', type: scopeTagType(row.scope) }, { default: () => scopeLabel(row.scope) }) },
  { title: t('内容摘要'), key: 'content', ellipsis: { tooltip: true }, render: (row) => row.l0_summary || row.content || '-' },
  { title: t('实际范围'), key: 'actual_scope', width: 110, render: (row) => row.actual_scope ? scopeLabel(row.actual_scope) : '-' },
  { title: t('解析来源'), key: 'resolved_from', width: 130, render: (row) => row.resolved_from || '-' },
  {
    title: t('项目 / 部门归属'), key: 'project', width: 180, ellipsis: { tooltip: true },
    render: (row) => {
      if (row.scope === 'project' && !row.project_owner_id) {
        return h(NTag, { bordered: false, size: 'small', type: 'error' }, { default: () => t('缺少 project_owner_id') });
      }
      return row.project_id ? `${row.project_id}${row.project_owner_id ? ` (${row.project_owner_id})` : ''}` : (row.department_id || '-');
    },
  },
  { title: t('来源'), key: 'source_type', width: 110, render: (row) => row.source_type || (row.source_session_id ? t('会话沉淀') : t('手动')) },
  { title: t('状态'), key: 'status', width: 100, render: (row) => {
      const archived = row.archived || row.status === 'archived';
      return h(NTag, { bordered: false, size: 'small', type: archived ? 'default' : 'success' }, { default: () => archived ? t('已归档') : t('正常') });
    } },
  { title: t('创建时间'), key: 'created_at', width: 170, render: (row) => formatAdminDateTime(row.created_at, '-') },
  {
    title: t('操作'), key: 'actions', width: 260,
    render: (row) => h(NSpace, { size: 4, wrap: false }, { default: () => [
      h(NButton, { text: true, type: 'primary', size: 'tiny', onClick: () => openDetail(row) }, { default: () => t('详情') }),
      h(NButton, { text: true, type: 'primary', size: 'tiny', onClick: () => openApproval(row) }, { default: () => t('提升审批') }),
      row.archived || row.status === 'archived'
        ? h(NButton, { text: true, size: 'tiny', onClick: () => runAction(() => restoreAdminMemory(row.memory_id, t('恢复')), t('已恢复')) }, { default: () => t('恢复') })
        : h(NButton, { text: true, size: 'tiny', onClick: () => runAction(() => archiveAdminMemory(row.memory_id, t('归档')), t('已归档')) }, { default: () => t('归档') }),
      h(NButton, { text: true, type: 'error', size: 'tiny', onClick: () => askDelete(row) }, { default: () => t('删除') }),
    ] }),
  },
];

async function load() {
  loading.value = true;
  try {
    const [list, summary, projectList] = await Promise.all([
      fetchAdminMemories({
        page: page.value,
        page_size: pageSize,
        keyword: filters.value.keyword.trim(),
        scope: filters.value.scope,
        tenant_id: filters.value.tenant_id.trim(),
        status: filters.value.status,
      }),
      fetchAdminMemoryStats(),
      listAdminProjects(),
    ]);
    rows.value = list.items;
    total.value = list.total;
    stats.value = summary;
    projects.value = projectList;
  } catch (error: any) {
    // T030：不可见 / 治理端点未提供（404）统一按「无权限 / 不存在」显示，不回显后端内容。
    const e = normalizeMemoryError(error);
    message.error(e.notFound ? memoryErrorText(error) : memoryErrorText(error, t('加载失败')));
    rows.value = []; total.value = 0;
  } finally { loading.value = false; }
}

function applyFilters() { page.value = 1; void load(); }
watch(page, load);
onMounted(load);

async function runAction(action: () => Promise<unknown>, successText: string) {
  try {
    await action();
    message.success(successText);
    await load();
  } catch (error: any) {
    message.error(memoryErrorText(error, t('操作失败')));
  }
}

function askDelete(row: MemoryItem) {
  dialog.warning({
    title: t('删除记忆'),
    content: t('删除需 full_access_admin 权限并落审计，且不可恢复。确认删除？'),
    positiveText: t('确认删除'),
    negativeText: t('取消'),
    onPositiveClick: () => runAction(() => deleteAdminMemory(row.memory_id, t('治理删除')), t('已删除')),
  });
}

function batchArchive() {
  if (!checkedRowKeys.value.length) return;
  dialog.warning({
    title: t('批量归档'),
    content: t('共 {count} 条，确认归档？', { count: checkedRowKeys.value.length }),
    positiveText: t('确认'),
    negativeText: t('取消'),
    onPositiveClick: async () => {
      await runAction(() => batchArchiveAdminMemories(checkedRowKeys.value, t('批量归档')), t('已批量归档'));
      checkedRowKeys.value = [];
    },
  });
}
</script>

<template>
  <div class="page-stack memories-page">
    <n-card class="memories-card" :bordered="false" size="large">
      <div class="memories-content">
        <div class="page-head">
          <PageIntro :title="t('记忆管理')" :description="t('跨个人 / 项目 / 部门三范围治理记忆：查看分层内容、归属与来源，执行归档、提升审批与策略配置。')" :tags="[t('三范围'), t('统一治理')]" />
          <n-button type="primary" secondary :loading="loading" @click="load">{{ t('刷新') }}</n-button>
        </div>

        <div class="metric-grid">
          <div v-for="item in metrics" :key="item.label" class="metric-card">
            <span>{{ item.label }}</span>
            <strong :class="{ danger: item.danger }">{{ item.value }}</strong>
            <small>{{ item.hint }}</small>
          </div>
        </div>

        <div class="list-card">
          <div class="toolbar">
            <n-space :size="10" wrap>
              <n-select v-model:value="filters.scope" :options="scopeOptions" style="width: 150px" @update:value="applyFilters" />
              <n-input v-model:value="filters.tenant_id" clearable :placeholder="t('租户 ID')" style="width: 180px" @keyup.enter="applyFilters" />
              <n-select v-model:value="filters.status" :options="statusOptions" style="width: 140px" @update:value="applyFilters" />
              <n-input v-model:value="filters.keyword" clearable :placeholder="t('搜索内容 / 项目 / 来源')" style="width: 240px" @keyup.enter="applyFilters" />
              <n-button @click="applyFilters">{{ t('查询') }}</n-button>
              <n-button :disabled="!checkedRowKeys.length" @click="batchArchive">{{ t('批量归档') }}{{ checkedRowKeys.length ? ` (${checkedRowKeys.length})` : '' }}</n-button>
            </n-space>
          </div>
          <n-data-table
            :columns="columns"
            :data="rows"
            :loading="loading"
            :bordered="false"
            :pagination="false"
            :row-key="(row: MemoryItem) => row.memory_id"
            v-model:checked-row-keys="checkedRowKeys"
          />
          <div class="pager-row">
            <span>{{ t('共 {count} 条', { count: total }) }}</span>
            <n-pagination v-model:page="page" :page-size="pageSize" :item-count="total" />
          </div>
        </div>

        <!-- T027：可见范围 / 策略 / 配额配置（页面内折叠区块） -->
        <n-collapse>
          <n-collapse-item :title="t('可见范围 / 策略 / 配额配置')" name="governance">
            <MemoryGovernancePanels />
          </n-collapse-item>
        </n-collapse>
      </div>
    </n-card>

    <MemoryDetailDrawer v-model:show="detailVisible" :record="detailRecord" :projects="projects" />
    <MemoryApprovalDialog v-model:show="approvalVisible" :record="approvalRecord" @submitted="load" />
  </div>
</template>

<style scoped>
.memories-page { height: 100%; min-height: 0; display: flex; flex-direction: column; }
.memories-card { min-width: 0; border-radius: 8px; }
.memories-content { display: grid; gap: 18px; min-width: 0; }
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
.metric-card { display: grid; gap: 4px; padding: 16px 18px; border: 1px solid var(--mg-border); border-radius: 10px; background: var(--mg-bg-surface); }
.metric-card span, .metric-card small, .pager-row { color: var(--mg-text-2); }
.metric-card strong { color: var(--mg-text-1); font-size: 24px; line-height: 1.2; }
.metric-card strong.danger { color: var(--mg-danger-text); }
.list-card { overflow: hidden; border: 1px solid var(--mg-border); border-radius: 10px; }
.toolbar, .pager-row { padding: 14px 16px; }
.toolbar { border-bottom: 1px solid var(--mg-border); }
.pager-row { display: flex; align-items: center; justify-content: space-between; border-top: 1px solid var(--mg-border); }
@media (max-width: 980px) { .metric-grid { grid-template-columns: repeat(2, 1fr); } .page-head { align-items: flex-start; flex-direction: column; } }
</style>
