<script setup lang="ts">
import { t } from '@/composables/i18n';
import { computed, h, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { NButton, NCard, NDataTable, NInput, NInputNumber, NSelect, NSpace, NTag, NEmpty, useMessage, type DataTableColumns } from 'naive-ui';
import PageIntro from '@/components/PageIntro.vue';
import {
  fetchProjectsWithUsage,
  updateProjectQuotaPolicy,
  deleteProjectQuotaPolicy,
  type ProjectWithUsage,
} from '@/api/projects';
import type { QuotaPeriod } from '@/api/traffic-allocations';

const message = useMessage();
const route = useRoute();
const router = useRouter();
const loading = ref(false);
const rows = ref<ProjectWithUsage[]>([]);

// 额度编辑弹窗
const editingProject = ref<ProjectWithUsage | null>(null);
const editQuotaTokens = ref<number>(0);
const editPeriod = ref<QuotaPeriod>('monthly');
const saving = ref(false);

const periodOptions = [
  { label: t('每月'), value: 'monthly' },
  { label: t('每周'), value: 'weekly' },
  { label: t('每日'), value: 'daily' },
];

const activeRows = computed(() => rows.value.filter((r) => r.status === 'active'));
const archivedRows = computed(() => rows.value.filter((r) => r.status !== 'active'));

async function load() {
  loading.value = true;
  try {
    const res = await fetchProjectsWithUsage();
    rows.value = res.items;
  } catch (e) {
    message.error(String(e));
  } finally {
    loading.value = false;
  }
}

function formatTokens(n: number | undefined): string {
  if (n === undefined || n === null) return '-';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function formatCost(n: number | undefined): string {
  if (n === undefined || n === null) return '-';
  return `$${n.toFixed(4)}`;
}

function quotaDisplay(row: ProjectWithUsage): string {
  if (!row.quotaTokens) return t('未设置额度');
  const periodMap: Record<string, string> = { monthly: t('每月'), weekly: t('每周'), daily: t('每日') };
  return `${formatTokens(row.quotaTokens)} / ${periodMap[row.period || 'monthly'] || row.period}`;
}

function openEdit(row: ProjectWithUsage) {
  editingProject.value = row;
  editQuotaTokens.value = row.quotaTokens || 0;
  editPeriod.value = row.period || 'monthly';
}

async function saveQuota() {
  if (!editingProject.value) return;
  saving.value = true;
  try {
    await updateProjectQuotaPolicy(editingProject.value.id, {
      quotaTokens: editQuotaTokens.value,
      period: editPeriod.value,
    });
    message.success(t('已保存'));
    editingProject.value = null;
    await load();
  } catch (e) {
    message.error(String(e));
  } finally {
    saving.value = false;
  }
}

async function removeQuota(row: ProjectWithUsage) {
  try {
    await deleteProjectQuotaPolicy(row.id);
    message.success(t('已清除'));
    await load();
  } catch (e) {
    message.error(String(e));
  }
}

function createColumns(): DataTableColumns<ProjectWithUsage> {
  return [
    { title: t('项目名称'), key: 'name', width: 200 },
    {
      title: t('状态'), key: 'status', width: 80,
      render(row) {
        const typeMap: Record<string, string> = { active: 'success', disabled: 'warning', archived: 'default' };
        const labelMap: Record<string, string> = { active: t('正常'), disabled: t('停用'), archived: t('已归档') };
        return h(NTag, { size: 'small', type: (typeMap[row.status] || 'default') as any }, { default: () => labelMap[row.status] || row.status });
      },
    },
    {
      title: t('成员数'), key: 'memberCount', width: 80,
      render(row) { return String(row.memberCount ?? 0); },
    },
    {
      title: t('额度'), key: 'quotaTokens', width: 180,
      render(row) { return quotaDisplay(row); },
    },
    {
      title: t('用量 (tokens)'), key: 'usage.totalTokens', width: 120,
      render(row) { return formatTokens(row.usage?.totalTokens); },
    },
    {
      title: t('成本 (USD)'), key: 'usage.totalCostUsd', width: 120,
      render(row) { return formatCost(row.usage?.totalCostUsd); },
    },
    {
      title: t('操作'), key: 'actions', width: 160,
      render(row) {
        return h(NSpace, { size: 4 }, {
          default: () => [
            h(NButton, { size: 'tiny', onClick: () => openEdit(row) }, { default: () => t('编辑额度') }),
            row.quotaTokens
              ? h(NButton, { size: 'tiny', type: 'error', ghost: true, onClick: () => removeQuota(row) }, { default: () => t('清除') })
              : null,
          ],
        });
      },
    },
  ];
}

const columns = createColumns();

function consumeOpenQuery() {
  if (route.query.open === 'quota') {
    // 047-quota-discoverability: 深链进入时提示选择项目
    message.info(t('请选择要配置额度的项目'));
    const nextQuery = { ...route.query };
    delete nextQuery.open;
    router.replace({ path: route.path, query: nextQuery });
  }
}

onMounted(async () => {
  await load();
  consumeOpenQuery();
});
</script>

<template>
  <div class="projects-page">
    <PageIntro :title="t('项目管理')" :description="t('查看项目用量、成本与配额配置')" />

    <!-- 项目列表 -->
    <n-card :title="t('项目列表')" style="margin-bottom: 16px">
      <n-data-table
        :columns="columns"
        :data="activeRows"
        :loading="loading"
        :pagination="{ pageSize: 20 }"
        size="small"
      />
      <n-empty v-if="!loading && !activeRows.length">
        <template #default>
          <div style="text-align: center">
            <p>{{ t('暂无项目') }}</p>
            <p style="color: #64748b; font-size: 13px">
              {{ t('项目在 user-web 里选本地目录创建') }}
            </p>
          </div>
        </template>
      </n-empty>
    </n-card>

    <!-- 已归档 -->
    <n-card v-if="archivedRows.length" :title="t('已归档')" style="margin-bottom: 16px">
      <n-data-table
        :columns="columns.slice(0, -1)"
        :data="archivedRows"
        :pagination="{ pageSize: 10 }"
        size="small"
      />
    </n-card>

    <!-- 编辑额度弹窗 -->
    <n-modal v-model:show="editingProject" preset="card" :title="t('编辑项目额度')" style="width: 480px">
      <template v-if="editingProject">
        <n-space vertical :size="16">
          <div>
            <label>{{ t('项目名称') }}</label>
            <div style="font-weight: 600; margin-top: 4px">{{ editingProject.name }}</div>
          </div>
          <div>
            <label>{{ t('额度 (tokens)') }}</label>
            <n-input-number v-model:value="editQuotaTokens" :min="0" style="width: 100%; margin-top: 4px" />
          </div>
          <div>
            <label>{{ t('周期') }}</label>
            <n-select v-model:value="editPeriod" :options="periodOptions" style="margin-top: 4px" />
          </div>
          <n-space justify="end">
            <n-button @click="editingProject = null">{{ t('取消') }}</n-button>
            <n-button type="primary" :loading="saving" @click="saveQuota">{{ t('保存') }}</n-button>
          </n-space>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.projects-page {
  padding: 24px;
}
</style>
