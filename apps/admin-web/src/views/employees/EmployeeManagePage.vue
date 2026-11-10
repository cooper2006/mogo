<template>
  <div class="page-stack employees-page">
    <n-card class="list-card shell-card" :bordered="false" size="large">
      <div class="list-filter-row">
        <n-space align="center" :size="10" class="filter-left">
          <n-input v-model:value="filters.keyword" clearable :placeholder="t('搜索员工名称或描述')" class="keyword-input" />
          <n-select v-model:value="filters.status" clearable :options="statusOptions" :placeholder="t('状态')" style="width: 140px" />
        </n-space>
        <n-space :size="10" class="filter-right">
          <n-button secondary @click="loadRows">{{ t('刷新') }}</n-button>
          <n-button type="primary" strong @click="goCreate">{{ t('新建数字员工') }}</n-button>
        </n-space>
      </div>

      <div class="list-body">
        <n-spin :show="loading">
          <div v-if="filteredRows.length" class="employee-grid">
            <div v-for="row in filteredRows" :key="row.id" class="employee-card" role="button" tabindex="0" @click="goEdit(row.id)" @keydown.enter="goEdit(row.id)">
              <div class="card-head">
                <n-tag :type="row.status === 'active' ? 'success' : row.status === 'disabled' ? 'warning' : 'default'" size="small" :bordered="false">
                  {{ statusLabel(row.status) }}
                </n-tag>
                <n-space align="center" :size="8">
                  <span class="status-switch-label">{{ row.status === 'active' ? t('启用') : t('停用') }}</span>
                  <n-switch
                    :value="row.status === 'active'"
                    size="small"
                    :disabled="row.status === 'archived'"
                    @click.stop
                    @update:value="(value: boolean) => toggleStatus(row, value)"
                  />
                </n-space>
              </div>

              <div class="card-title">{{ row.name || t('未命名员工') }}</div>
              <div class="card-desc">{{ row.description || t('未填写说明') }}</div>

              <div class="tag-row">
                <n-tag v-for="cap in enabledCapabilities(row)" :key="cap" size="small" :bordered="false" class="cap-tag">{{ cap }}</n-tag>
                <span v-if="!enabledCapabilities(row).length" class="no-tag">{{ t('未开启能力') }}</span>
              </div>

              <div class="card-footrow">
                <div class="card-footnote">{{ t('成员 {count} · {time}', { count: row.memberUserIds.length, time: formatAdminDateTime(row.updatedAt, t('暂无记录')) }) }}</div>
                <n-space :size="6">
                  <n-button size="small" tertiary @click.stop="goEdit(row.id)">{{ t('编辑') }}</n-button>
                  <n-button size="small" tertiary type="error" :disabled="row.status === 'archived'" @click.stop="askRemove(row)">{{ t('删除') }}</n-button>
                </n-space>
              </div>
            </div>
          </div>

          <div v-else class="empty-shell">
            <div class="empty-title">{{ t('暂未配置数字员工') }}</div>
            <div class="empty-desc">{{ t('创建第一个数字员工，为团队提供专属 Agent 能力。') }}</div>
            <n-space justify="center">
              <n-button type="primary" @click="goCreate">{{ t('新建数字员工') }}</n-button>
            </n-space>
          </div>
        </n-spin>
      </div>
    </n-card>

    <n-modal
      v-model:show="deleteConfirmVisible"
      preset="dialog"
      type="warning"
      :title="t('删除数字员工')"
      :positive-text="t('删除')"
      :negative-text="t('取消')"
      :positive-button-props="{ type: 'error', loading: deleting }"
      @positive-click="confirmRemove"
    >
      {{ t('确定删除「{name}」吗？删除后历史会话保留溯源，但员工将不可再被使用。', { name: pendingDeleteRow?.name || t('未命名员工') }) }}
    </n-modal>

    <n-modal
      v-model:show="statusConfirmVisible"
      preset="dialog"
      type="warning"
      :title="pendingStatusValue ? t('启用') : t('停用')"
      :positive-text="pendingStatusValue ? t('确认启用') : t('确认停用')"
      :negative-text="t('取消')"
      :positive-button-props="{ type: pendingStatusValue ? 'primary' : 'warning', loading: statusUpdating }"
      @positive-click="confirmToggleStatus"
    >
      {{ pendingStatusText }}
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { useMessage } from 'naive-ui';
import { t } from '@/composables/i18n';
import { formatAdminDateTime } from '@/composables/adminTimezone';
import {
  deleteEmployee,
  listEmployees,
  setEmployeeStatus,
  type EmployeeCapabilityKey,
  type EmployeeItem,
  type EmployeeStatus,
} from '@/api/employees';

const CAPABILITY_LABELS: Record<EmployeeCapabilityKey, string> = {
  content_generation: t('内容生成'),
  image_generation: t('图像生成'),
  code_generation: t('代码生成'),
  browser_automation: t('浏览器自动化'),
  internal_knowledge: t('内部知识'),
};

const router = useRouter();
const message = useMessage();
const rows = ref<EmployeeItem[]>([]);
const loading = ref(false);
const deleting = ref(false);
const statusUpdating = ref(false);
const deleteConfirmVisible = ref(false);
const pendingDeleteRow = ref<EmployeeItem | null>(null);
const statusConfirmVisible = ref(false);
const pendingStatusRow = ref<EmployeeItem | null>(null);
const pendingStatusValue = ref(false);
const pendingStatusText = ref('');

const filters = ref({
  keyword: '',
  status: null as EmployeeStatus | null,
});

const statusOptions = computed(() => [
  { label: t('启用'), value: 'active' },
  { label: t('停用'), value: 'disabled' },
  { label: t('已归档'), value: 'archived' },
]);

const filteredRows = computed(() => {
  const keyword = filters.value.keyword.trim().toLowerCase();
  return rows.value.filter((row) => {
    const keywordHit = !keyword
      || row.name.toLowerCase().includes(keyword)
      || row.description.toLowerCase().includes(keyword);
    const statusHit = !filters.value.status || row.status === filters.value.status;
    return keywordHit && statusHit;
  });
});

function statusLabel(status: EmployeeStatus): string {
  if (status === 'active') return t('启用');
  if (status === 'disabled') return t('停用');
  return t('已归档');
}

function enabledCapabilities(row: EmployeeItem): string[] {
  return (Object.entries(row.capabilities || {}) as Array<[EmployeeCapabilityKey, boolean]>)
    .filter(([, enabled]) => enabled)
    .map(([key]) => CAPABILITY_LABELS[key] || key);
}

function goCreate() {
  router.push('/employees/create');
}

function goEdit(id: string) {
  router.push(`/employees/edit/${id}`);
}

async function loadRows() {
  loading.value = true;
  try {
    const page = await listEmployees();
    rows.value = page.items;
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('加载数字员工失败'));
  } finally {
    loading.value = false;
  }
}

async function toggleStatus(row: EmployeeItem, enabled: boolean) {
  if (row.status === 'archived') return;
  pendingStatusRow.value = row;
  pendingStatusValue.value = enabled;
  pendingStatusText.value = enabled
    ? t('确定启用「{name}」吗？启用后该员工将可被成员选择使用。', { name: row.name || t('未命名员工') })
    : t('确定停用「{name}」吗？停用后该员工不可再被选择，已有会话保留。', { name: row.name || t('未命名员工') });
  statusConfirmVisible.value = true;
}

async function confirmToggleStatus() {
  if (!pendingStatusRow.value) return false;
  statusUpdating.value = true;
  try {
    await setEmployeeStatus(pendingStatusRow.value.id, pendingStatusValue.value ? 'active' : 'disabled');
    message.success(pendingStatusValue.value ? t('员工已启用') : t('员工已停用'));
    statusConfirmVisible.value = false;
    pendingStatusRow.value = null;
    await loadRows();
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('状态更新失败'));
    return false;
  } finally {
    statusUpdating.value = false;
  }
  return true;
}

function askRemove(row: EmployeeItem) {
  if (row.status === 'archived') return;
  pendingDeleteRow.value = row;
  deleteConfirmVisible.value = true;
}

async function confirmRemove() {
  if (!pendingDeleteRow.value) return false;
  deleting.value = true;
  try {
    await deleteEmployee(pendingDeleteRow.value.id);
    message.success(t('数字员工已删除'));
    deleteConfirmVisible.value = false;
    pendingDeleteRow.value = null;
    await loadRows();
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('删除失败'));
    return false;
  } finally {
    deleting.value = false;
  }
  return true;
}

onMounted(loadRows);
</script>

<style scoped>
.employees-page {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.shell-card {
  border-radius: 14px;
  border: 1px solid var(--mg-border);
  background: var(--mg-bg-surface);
  box-shadow: 0 6px 20px rgba(16, 38, 84, 0.05);
}

.list-card {
  width: 100%;
  margin: 0 0 0;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.list-card :deep(.n-card__content) {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.filter-left {
  flex-wrap: wrap;
}

.keyword-input {
  width: 360px;
}

.filter-right {
  flex-wrap: wrap;
}

.list-filter-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 0 32px 16px;
  margin: 0 -32px 16px;
  border-bottom: 1px solid var(--mg-border);
}

.list-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-gutter: stable;
}

.employee-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 12px;
}

.employee-card {
  min-height: 188px;
  padding: 14px;
  border: 1px solid rgba(28, 45, 82, 0.08);
  border-radius: 8px;
  background: var(--mg-bg-surface);
  box-shadow:
    0 8px 18px rgba(15, 31, 69, 0.06),
    0 1px 2px rgba(15, 31, 69, 0.04);
  display: flex;
  flex-direction: column;
  gap: 10px;
  cursor: pointer;
  outline: none;
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease,
    transform 0.2s ease;
}

.employee-card:hover,
.employee-card:focus-visible {
  border-color: rgba(54, 106, 255, 0.36);
  box-shadow:
    0 14px 34px rgba(33, 58, 126, 0.14),
    0 4px 10px rgba(33, 58, 126, 0.08);
  transform: translateY(-2px);
}

.card-head,
.card-footrow {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.card-title {
  color: var(--mg-text-1);
  font-size: 16px;
  font-weight: 800;
}

.card-desc {
  color: var(--mg-text-2);
  font-size: 13px;
  line-height: 1.55;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  overflow: hidden;
}

.card-footnote,
.no-tag {
  color: var(--mg-text-3);
  font-size: 12px;
}

.status-switch-label {
  color: var(--mg-text-2);
  font-size: 12px;
  white-space: nowrap;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-height: 24px;
}

.cap-tag {
  background: var(--mg-bg-subtle);
}

.card-footrow {
  margin-top: auto;
  min-height: 28px;
}

.card-footnote {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.empty-shell {
  min-height: 320px;
  border: 1px dashed var(--mg-border);
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  text-align: center;
  background: var(--mg-gradient-empty);
}

.empty-title {
  color: var(--mg-text-1);
  font-size: 24px;
  line-height: 1.2;
  font-weight: 800;
}

.empty-desc {
  color: var(--mg-text-2);
  font-size: 14px;
}

@media (max-width: 1200px) {
  .employee-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .employee-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .list-filter-row {
    flex-direction: column;
    align-items: stretch;
  }

  .keyword-input {
    width: 100%;
  }
}
</style>
