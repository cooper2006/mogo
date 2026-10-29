<template>
  <div class="page-stack traffic-page">
    <div class="metrics-row">
      <n-card v-for="item in metricCards" :key="item.key" class="metric-card" :bordered="false" size="small">
        <div class="metric-main">
          <span class="metric-icon" :class="`metric-icon-${item.key}`" v-html="item.icon"></span>
          <div class="metric-body">
            <div class="metric-label">{{ item.label }}</div>
            <div class="metric-value">{{ item.value }}</div>
          </div>
        </div>
        <div class="metric-note">{{ item.note }}</div>
      </n-card>
    </div>

    <n-card class="list-card shell-card" :bordered="false" size="large">
      <div class="list-filter-row">
        <div class="filter-toolbar">
          <n-space align="center" :size="10" class="filter-left">
            <n-input v-model:value="filters.keyword" :placeholder="t('搜索姓名 / 手机号 / 邮箱')" clearable class="keyword-input" />
          </n-space>
          <n-space :size="10" class="filter-right">
            <n-button secondary :loading="loading" @click="reload">{{ t('刷新') }}</n-button>
            <n-button secondary @click="openSettings">{{ t('设置企业额度') }}</n-button>
            <n-button secondary @click="openLogs">{{ t('分配记录') }}</n-button>
            <n-button secondary @click="openScopes">{{ t('团队 / 项目额度') }}</n-button>
          </n-space>
        </div>
      </div>

      <div class="table-shell">
        <n-spin :show="loading" class="table-spin">
          <n-data-table
            class="allocation-table"
            flex-height
            :columns="columns"
            :data="users"
            :bordered="false"
            :pagination="pagination"
          />
        </n-spin>
      </div>
    </n-card>
  </div>

  <n-modal v-model:show="settingsVisible" preset="card" :title="t('额度设置')" style="width: 760px">
    <n-form class="settings-form" label-placement="top">
      <n-grid :cols="2" :x-gap="14" :y-gap="10" responsive="screen">
        <n-grid-item>
          <n-form-item :label="t('企业本周期总额度')">
            <n-input-number
              v-model:value="orgForm.totalTokens"
              :min="0"
              :disabled="orgForm.unlimited"
              :show-button="false"
              class="wide-input"
            />
          </n-form-item>
          <n-checkbox v-model:checked="orgForm.unlimited">{{ t('不限额（不做限制）') }}</n-checkbox>
        </n-grid-item>
        <n-grid-item>
          <n-form-item :label="t('企业重置周期')">
            <n-select v-model:value="orgForm.period" :options="periodOptions" />
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item :label="t('新成员默认额度')">
            <n-input-number
              v-model:value="defaultForm.quotaTokens"
              :min="0"
              :max="orgForm.unlimited ? undefined : orgForm.totalTokens || 0"
              :disabled="defaultForm.unlimited"
              :show-button="false"
              class="wide-input"
            />
          </n-form-item>
          <n-checkbox v-model:checked="defaultForm.unlimited">{{ t('不限额（不做限制）') }}</n-checkbox>
        </n-grid-item>
        <n-grid-item>
          <n-form-item :label="t('成员重置周期')">
            <n-select v-model:value="defaultForm.period" :options="periodOptions" />
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item :label="t('额度告警阈值（剩余占比，%）')">
            <n-input-number
              v-model:value="alertThresholdPercent"
              :min="1"
              :max="100"
              :show-button="false"
              class="wide-input"
            />
          </n-form-item>
        </n-grid-item>
      </n-grid>
      <div class="period-hint">
        {{ t('企业重置周期用于企业共享总额度；成员重置周期用于每位成员的个人额度，并同步应用到已有成员。') }}
        <br />
        {{ t('周期按企业时区的自然时间计算：自然月为每月 1 日 00:00 至下月 1 日 00:00，自然日为当天 00:00 至次日 00:00，自然小时为整点到下一整点。') }}
        <span v-if="overview?.orgPolicy.periodStartAt">
          {{ t('当前周期') }}：{{ formatDateTime(overview.orgPolicy.periodStartAt) }} - {{ formatDateTime(overview.orgPolicy.resetAt) }}
        </span>
      </div>
    </n-form>
    <template #footer>
      <n-space justify="end">
        <n-button @click="settingsVisible = false">{{ t('取消') }}</n-button>
        <n-button type="primary" :loading="savingPolicy" @click="savePolicies">{{ t('保存设置') }}</n-button>
      </n-space>
    </template>
  </n-modal>

  <n-modal v-model:show="editorVisible" preset="card" :title="t('设置用户额度')" style="width: 560px">
    <n-form :model="userForm" label-placement="left" label-width="110">
      <n-form-item :label="t('用户')">
        <div class="user-inline">
          <strong>{{ currentUser?.name || currentUser?.loginName }}</strong>
          <span>{{ currentUser?.departmentName || t('未分配部门') }}</span>
        </div>
      </n-form-item>
      <n-form-item :label="t('本周期额度')">
        <n-space vertical :size="6" style="width: 100%">
          <n-input-number
            v-model:value="userForm.quotaTokens"
            :min="0"
            :max="quotaLimit(overview?.orgPolicy.totalTokens || 0)"
            :disabled="userForm.unlimited"
            :show-button="false"
            class="wide-input"
          />
          <n-checkbox v-model:checked="userForm.unlimited">{{ t('不限额（不做限制）') }}</n-checkbox>
        </n-space>
      </n-form-item>
      <n-form-item :label="t('重置周期')">
        <n-select v-model:value="userForm.period" :options="periodOptions" />
      </n-form-item>
      <n-form-item :label="t('备注')">
        <n-input v-model:value="userForm.reason" type="textarea" :rows="3" :placeholder="t('记录本次调整原因')" />
      </n-form-item>
    </n-form>
    <template #footer>
      <n-space justify="end">
        <n-button @click="editorVisible = false">{{ t('取消') }}</n-button>
        <n-button type="primary" :loading="savingUser" @click="saveUserPolicy">{{ t('保存') }}</n-button>
      </n-space>
    </template>
  </n-modal>

  <n-drawer v-model:show="logsVisible" :width="620" placement="right">
    <n-drawer-content :title="t('分配记录')" closable>
      <n-spin :show="logsLoading">
        <n-timeline>
          <n-timeline-item
            v-for="log in logs"
            :key="log.id"
            type="info"
            :title="`${log.userName || log.userId} ${formatDelta(log.deltaTokens)}`"
            :content="log.reason || t('无备注')"
            :time="formatDateTime(log.createdAt)"
          />
        </n-timeline>
        <n-empty v-if="!logs.length" :description="t('暂无分配记录')" />
      </n-spin>
      <div v-if="logsTotal > logsPageSize" class="logs-pagination">
        <span>{{ t('共 {count} 条记录', { count: logsTotal }) }}</span>
        <n-pagination
          v-model:page="logsPage"
          :page-size="logsPageSize"
          :item-count="logsTotal"
          size="small"
          @update:page="loadLogs"
        />
      </div>
    </n-drawer-content>
  </n-drawer>

  <n-modal v-model:show="scopeVisible" preset="card" :title="t('团队 / 项目额度')" style="width: 860px">
    <n-tabs v-model:value="scopeTab" type="line">
      <n-tab-pane name="team" :tab="t('团队额度')">
        <n-form label-placement="top" class="settings-form">
          <n-grid :cols="3" :x-gap="12" :y-gap="10" responsive="screen">
            <n-grid-item>
              <n-form-item :label="t('选择部门')">
                <n-select v-model:value="teamForm.orgUnitId" :options="departmentOptions" filterable :placeholder="t('请选择部门')" />
              </n-form-item>
            </n-grid-item>
            <n-grid-item>
              <n-form-item :label="t('周期额度')">
                <n-input-number v-model:value="teamForm.quotaTokens" :min="0" :show-button="false" style="width: 100%" />
              </n-form-item>
            </n-grid-item>
            <n-grid-item>
              <n-form-item :label="t('重置周期')">
                <n-select v-model:value="teamForm.period" :options="periodOptions" />
              </n-form-item>
            </n-grid-item>
          </n-grid>
          <n-space justify="end">
            <n-button type="primary" :loading="savingScope" @click="saveTeamPolicy">{{ t('保存团队额度') }}</n-button>
          </n-space>
        </n-form>
        <n-empty v-if="!teamPolicies.length" :description="t('暂无团队额度')" />
        <div v-else class="scope-list">
          <div v-for="item in teamPolicies" :key="item.scopeId" class="scope-row">
            <div class="scope-main">
              <strong>{{ item.name || item.scopeId }}</strong>
              <span class="scope-meta">{{ formatQuota(item.quotaTokens) }} · {{ periodLabel(item.period) }} · {{ item.status === 'active' ? t('启用') : t('禁用') }}</span>
            </div>
            <n-space :size="8">
              <n-button size="small" secondary @click="editTeamPolicy(item)">{{ t('编辑') }}</n-button>
              <n-button size="small" secondary type="error" @click="removeTeamPolicy(item.scopeId)">{{ t('清除') }}</n-button>
            </n-space>
          </div>
        </div>
      </n-tab-pane>

      <n-tab-pane name="project" :tab="t('项目额度')">
        <n-form label-placement="top" class="settings-form">
          <n-grid :cols="2" :x-gap="12" :y-gap="10" responsive="screen">
            <n-grid-item>
              <n-form-item :label="t('项目名称')">
                <n-input v-model:value="projectForm.name" :placeholder="t('例如：专项攻坚')" />
              </n-form-item>
            </n-grid-item>
            <n-grid-item>
              <n-form-item :label="t('成员（可多选）')">
                <n-select
                  v-model:value="projectForm.memberUserIds"
                  multiple
                  filterable
                  :options="memberOptions"
                  :placeholder="t('选择项目成员')"
                />
              </n-form-item>
            </n-grid-item>
          </n-grid>
          <n-space justify="end">
            <n-button type="primary" :loading="savingScope" @click="createProject">{{ t('新建项目') }}</n-button>
          </n-space>
        </n-form>

        <n-form label-placement="top" class="settings-form">
          <n-grid :cols="3" :x-gap="12" :y-gap="10" responsive="screen">
            <n-grid-item>
              <n-form-item :label="t('目标项目')">
                <n-select v-model:value="projectPolicy.projectId" :options="projectOptions" filterable :placeholder="t('请选择项目')" />
              </n-form-item>
            </n-grid-item>
            <n-grid-item>
              <n-form-item :label="t('周期额度')">
                <n-input-number v-model:value="projectPolicy.quotaTokens" :min="0" :show-button="false" style="width: 100%" />
              </n-form-item>
            </n-grid-item>
            <n-grid-item>
              <n-form-item :label="t('重置周期')">
                <n-select v-model:value="projectPolicy.period" :options="periodOptions" />
              </n-form-item>
            </n-grid-item>
          </n-grid>
          <n-space justify="end">
            <n-button type="primary" :loading="savingScope" @click="saveProjectPolicy">{{ t('保存项目额度') }}</n-button>
          </n-space>
        </n-form>

        <n-empty v-if="!projects.length" :description="t('暂无项目分组')" />
        <div v-else class="scope-list">
          <div v-for="item in projects" :key="item.id" class="scope-row">
            <div class="scope-main">
              <strong>{{ item.name }}</strong>
              <span class="scope-meta">{{ t('{count} 位成员', { count: item.memberCount }) }} · {{ projectPolicyText(item) }}</span>
            </div>
            <n-space :size="8">
              <n-button size="small" secondary @click="editProject(item)">{{ t('编辑') }}</n-button>
              <n-button size="small" secondary type="error" @click="removeProject(item.id)">{{ t('删除') }}</n-button>
            </n-space>
          </div>
        </div>
      </n-tab-pane>
    </n-tabs>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, h, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { NButton, NPagination, NProgress, NSpace, NSpin, NTimeline, NTimelineItem, useMessage, type DataTableColumns } from 'naive-ui';
import { t } from '@/composables/i18n';
import { formatAdminShortDateTime } from '@/composables/adminTimezone';
import {
  createQuotaProject,
  deleteQuotaProject,
  deleteTeamQuotaPolicy,
  fetchAllocationLogs,
  fetchQuotaProjects,
  fetchTeamQuotaPolicies,
  fetchTrafficAllocationOverview,
  fetchUserAllocations,
  updateDefaultQuotaPolicy,
  updateOrgQuotaPolicy,
  updateProjectQuotaPolicy,
  updateQuotaProject,
  updateTeamQuotaPolicy,
  updateUserQuotaPolicy,
  type AllocationLogItem,
  type QuotaPeriod,
  type QuotaProject,
  type QuotaStatus,
  type ScopedQuotaPolicy,
  type TrafficAllocationOverview,
  type UserAllocationItem,
} from '@/api/traffic-allocations';
import { fetchDepartmentTree, type DepartmentNode } from '@/api/directory';

const message = useMessage();
const route = useRoute();
const router = useRouter();
const loading = ref(false);
const savingPolicy = ref(false);
const savingUser = ref(false);
const settingsVisible = ref(false);
const editorVisible = ref(false);
const logsVisible = ref(false);
const overview = ref<TrafficAllocationOverview | null>(null);
const users = ref<UserAllocationItem[]>([]);
const logs = ref<AllocationLogItem[]>([]);
const logsLoading = ref(false);
const logsPage = ref(1);
const logsPageSize = 20;
const logsTotal = ref(0);
const currentUser = ref<UserAllocationItem | null>(null);
// 042 三层配额：团队（部门树）/ 项目分组
const scopeVisible = ref(false);
const scopeTab = ref<'team' | 'project'>('team');
const savingScope = ref(false);
const teamPolicies = ref<ScopedQuotaPolicy[]>([]);
const projects = ref<QuotaProject[]>([]);
const departments = ref<DepartmentNode[]>([]);

const filters = reactive({ keyword: '' });
const orgForm = reactive({
  totalTokens: 0,
  unlimited: false,
  period: 'monthly' as QuotaPeriod,
  timezone: 'Asia/Shanghai',
  status: 'active' as QuotaStatus,
  alertThresholdRatio: 0.2,
});
// 告警阈值以百分比呈现（后端存 0~1 小数）
const alertThresholdPercent = ref(20);
const defaultForm = reactive({ quotaTokens: 0, unlimited: false, period: 'monthly' as QuotaPeriod, status: 'active' as QuotaStatus });
const userForm = reactive({ quotaTokens: 0, unlimited: false, period: 'monthly' as QuotaPeriod, reason: '' });
const teamForm = reactive({ orgUnitId: '', quotaTokens: 0, period: 'monthly' as QuotaPeriod });
const projectForm = reactive({ name: '', note: '', memberUserIds: [] as string[] });
const projectPolicy = reactive({ projectId: '', quotaTokens: 0, period: 'monthly' as QuotaPeriod });

function flattenDepartments(nodes: DepartmentNode[], out: DepartmentNode[] = []): DepartmentNode[] {
  for (const node of nodes) {
    out.push(node);
    if (node.children?.length) flattenDepartments(node.children, out);
  }
  return out;
}

const departmentOptions = computed(() =>
  flattenDepartments(departments.value).map(node => ({ label: node.name, value: node.id })),
);
const projectOptions = computed(() => projects.value.map(item => ({ label: item.name, value: item.id })));
const memberOptions = computed(() =>
  users.value.map(item => ({ label: item.name || item.loginName || item.userId, value: item.userId })),
);

function projectPolicyText(project: QuotaProject) {
  if (!project.quotaTokens) return t('未设置额度');
  return `${formatQuota(project.quotaTokens)} · ${periodLabel(project.period || 'monthly')}`;
}

// T038 / 决策 12：``unlimited`` 为真时额度不做限制，前端不得对额度做算术运算。
function formatQuota(value: number, unlimited?: boolean) {
  if (unlimited) return t('不限额');
  return `${formatTokens(value)} Token`;
}

function unlimitedOf() {
  return Boolean(overview.value?.orgPolicy.unlimited);
}

function quotaLimit(value: number) {
  return unlimitedOf() ? undefined : Number(value || 0);
}

const periodOptions = computed(() => [
  { label: t('自然月重置（每月 1 日 00:00）'), value: 'monthly' },
  { label: t('自然日重置（每天 00:00）'), value: 'daily' },
  { label: t('自然小时重置（每小时整点）'), value: 'hourly' },
]);
function formatTokens(value: number) {
  const amount = Number(value || 0);
  if (amount >= 100000000) return `${(amount / 100000000).toFixed(1)} 亿`;
  if (amount >= 10000) return `${(amount / 10000).toFixed(1)} 万`;
  return amount.toLocaleString('zh-CN');
}

function periodLabel(value: string) {
  if (value === 'daily') return t('自然日');
  if (value === 'hourly') return t('自然小时');
  return t('自然月');
}

function formatDateTime(value?: string) {
  return formatAdminShortDateTime(value, '-');
}

function percent(row: UserAllocationItem) {
  if (!row.quotaTokens) return 0;
  return Math.max(0, Math.min(100, Math.round((row.usedTokens / row.quotaTokens) * 100)));
}

function formatDelta(value: number) {
  const amount = Number(value || 0);
  if (amount === 0) return t('额度未变化');
  return `${amount > 0 ? '+' : ''}${formatTokens(amount)} Token`;
}

function isQuotaBlank(value: unknown) {
  return value === null || value === undefined || value === '';
}

function userContactParts(row: UserAllocationItem) {
  return [row.email, row.mobile].filter((item) => String(item || '').trim());
}

function userContactText(row: UserAllocationItem) {
  const parts = userContactParts(row);
  return parts.length ? parts.join(' / ') : '-';
}

/** 指标卡片结构：模板按 key / label / value / note / icon 渲染。 */
interface MetricCard {
  key: string;
  label: string;
  value: string;
  note: string;
  icon: string;
}

/** 企业总额度卡片：不限额时展示不限额文案。 */
function buildPoolMetricCard(org?: TrafficAllocationOverview['orgPolicy']): MetricCard {
  return {
    key: 'pool',
    label: t('企业总额度'),
    value: org?.unlimited ? t('不限额') : formatTokens(org?.totalTokens || 0),
    note: org?.unlimited
      ? t('企业本周期额度不限额')
      : `${periodLabel(org?.period || 'monthly')} · ${t('下次重置')} ${formatDateTime(org?.resetAt)}`,
    icon: '<svg viewBox="0 0 24 24"><path d="M4 19h16M6 17V9m6 8V5m6 12v-6" /></svg>',
  };
}

/** 本周期已用卡片。 */
function buildUsedMetricCard(org?: TrafficAllocationOverview['orgPolicy']): MetricCard {
  return {
    key: 'used',
    label: t('本周期已用'),
    value: formatTokens(org?.usedTokens || 0),
    note: org?.unlimited ? t('不限额度') : `${t('剩余')} ${formatTokens(org?.remainingTokens || 0)} Token`,
    icon: '<svg viewBox="0 0 24 24"><path d="M12 3v18M6 8h9a3 3 0 0 1 0 6H9" /></svg>',
  };
}

/** 默认成员额度卡片。 */
function buildDefaultMetricCard(def?: TrafficAllocationOverview['defaultPolicy']): MetricCard {
  return {
    key: 'default',
    label: t('默认成员额度'),
    value: def?.unlimited ? t('不限额') : formatTokens(def?.quotaTokens || 0),
    note: `${periodLabel(def?.period || 'monthly')} · ${def?.status === 'active' ? t('启用') : t('禁用')}`,
    icon: '<svg viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm13 10v-2a4 4 0 0 0-3-3.87" /></svg>',
  };
}

/** 自定义额度用户卡片。 */
function buildAssignedMetricCard(overviewDoc?: TrafficAllocationOverview | null): MetricCard {
  return {
    key: 'policy',
    label: t('自定义额度用户'),
    value: String(overviewDoc?.assignedPolicyCount || 0),
    note: `${t('已分配专属额度')} ${formatTokens(overviewDoc?.assignedTokens || 0)} Token`,
    icon: '<svg viewBox="0 0 24 24"><path d="m9 12 2 2 4-5M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" /></svg>',
  };
}

const metricCards = computed(() => [
  buildPoolMetricCard(overview.value?.orgPolicy),
  buildUsedMetricCard(overview.value?.orgPolicy),
  buildDefaultMetricCard(overview.value?.defaultPolicy),
  buildAssignedMetricCard(overview.value),
]);

const columns: DataTableColumns<UserAllocationItem> = [
  {
    title: t('用户'),
    key: 'name',
    render(row) {
      return h('div', { class: 'user-cell' }, [
        h('div', { class: 'user-main-line', style: 'display:flex;align-items:center;gap:8px;min-width:0;' }, [
          h(
            'strong',
            {
              style: 'color:#0f172a;font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;',
            },
            row.name || row.loginName || '-',
          ),
          row.loginName && row.loginName !== row.name
            ? h('span', { class: 'login-name', style: 'flex:0 0 auto;color:#a3adbd;font-size:14px;' }, row.loginName)
            : null,
        ]),
        h(
          'div',
          {
            class: 'user-contact-line',
            style: 'color:#8b97a8;font-size:14px;line-height:20px;word-break:break-all;',
          },
          userContactText(row),
        ),
        h(
          'span',
          {
            class: 'user-department',
            style:
              'width:fit-content;max-width:100%;border-radius:4px;background:#f6f8fb;color:#8b97a8;font-size:14px;line-height:22px;padding:0 6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;',
          },
          row.departmentName || t('未分配部门'),
        ),
      ]);
    },
  },
  {
    title: t('分配额度'),
    key: 'quotaTokens',
    render: (row) => formatQuota(row.quotaTokens, row.unlimited),
  },
  {
    title: t('已用 / 剩余'),
    key: 'usage',
    render(row) {
      if (row.unlimited) {
        return h('div', { class: 'usage-cell' }, [
          h(NProgress, { type: 'line', percentage: 0, height: 6, showIndicator: false, borderRadius: 4 }),
          h('span', `${formatTokens(row.usedTokens)} / ${t('不限额度')}`),
        ]);
      }
      return h('div', { class: 'usage-cell' }, [
        h(NProgress, { type: 'line', percentage: percent(row), height: 6, showIndicator: false, borderRadius: 4 }),
        h('span', `${formatTokens(row.usedTokens)} / ${formatTokens(row.remainingTokens)}`),
      ]);
    },
  },
  {
    title: t('周期'),
    key: 'period',
    render: (row) => periodLabel(row.period),
  },
  {
    title: t('操作'),
    key: 'actions',
    width: 120,
    render(row) {
      return h(NSpace, { size: 8 }, () => [
        h(NButton, { size: 'small', tertiary: true, onClick: () => openEditor(row) }, () => t('设置个人额度')),
      ]);
    },
  },
];

const pagination = { pageSize: 12 };

function syncForms() {
  if (!overview.value) return;
  Object.assign(orgForm, overview.value.orgPolicy);
  Object.assign(defaultForm, overview.value.defaultPolicy);
  orgForm.alertThresholdRatio = overview.value.alertThresholdRatio ?? 0.2;
  alertThresholdPercent.value = Math.round(orgForm.alertThresholdRatio * 100);
}

async function reload() {
  loading.value = true;
  try {
    const [nextOverview, nextUsers] = await Promise.all([
      fetchTrafficAllocationOverview(),
      fetchUserAllocations({ keyword: filters.keyword }),
    ]);
    overview.value = nextOverview;
    users.value = nextUsers;
    syncForms();
  } finally {
    loading.value = false;
  }
}

function consumeOpenQuotaQuery() {
  if (route.query.open !== 'quota') return;
  openSettings();
  const nextQuery = { ...route.query };
  delete nextQuery.open;
  router.replace({ path: route.path, query: nextQuery });
}

async function loadScopes() {
  const [departmentsTree, teamResult, projectResult] = await Promise.all([
    fetchDepartmentTree(),
    fetchTeamQuotaPolicies(),
    fetchQuotaProjects(),
  ]);
  departments.value = departmentsTree;
  teamPolicies.value = teamResult.items;
  projects.value = projectResult.items;
}

async function openScopes() {
  scopeVisible.value = true;
  try {
    await loadScopes();
  } catch (error) {
    message.error((error as Error).message || t('加载团队 / 项目额度失败'));
  }
}

function editTeamPolicy(item: ScopedQuotaPolicy) {
  teamForm.orgUnitId = item.scopeId;
  teamForm.quotaTokens = item.quotaTokens;
  teamForm.period = item.period;
}

async function saveTeamPolicy() {
  if (!teamForm.orgUnitId) {
    message.warning(t('请选择部门'));
    return;
  }
  savingScope.value = true;
  try {
    await updateTeamQuotaPolicy(teamForm.orgUnitId, {
      quotaTokens: Number(teamForm.quotaTokens || 0),
      period: teamForm.period,
      status: 'active',
    });
    message.success(t('保存成功'));
    await loadScopes();
  } catch (error) {
    message.error((error as Error).message || t('保存失败'));
  } finally {
    savingScope.value = false;
  }
}

async function removeTeamPolicy(orgUnitId: string) {
  savingScope.value = true;
  try {
    await deleteTeamQuotaPolicy(orgUnitId);
    message.success(t('已清除该团队额度'));
    await loadScopes();
  } catch (error) {
    message.error((error as Error).message || t('清除失败'));
  } finally {
    savingScope.value = false;
  }
}

async function createProject() {
  if (!projectForm.name.trim()) {
    message.warning(t('请填写项目名称'));
    return;
  }
  savingScope.value = true;
  try {
    const created = await createQuotaProject({
      name: projectForm.name.trim(),
      note: projectForm.note,
      memberUserIds: projectForm.memberUserIds,
    });
    message.success(t('项目已创建'));
    projectForm.name = '';
    projectForm.note = '';
    projectForm.memberUserIds = [];
    projectPolicy.projectId = created.id;
    await loadScopes();
  } catch (error) {
    message.error((error as Error).message || t('创建失败'));
  } finally {
    savingScope.value = false;
  }
}

function editProject(item: QuotaProject) {
  projectPolicy.projectId = item.id;
  projectPolicy.quotaTokens = Number(item.quotaTokens || 0);
  projectPolicy.period = item.period || 'monthly';
  projectForm.name = item.name;
  projectForm.note = item.note;
  projectForm.memberUserIds = [...item.memberUserIds];
}

async function saveProjectPolicy() {
  if (!projectPolicy.projectId) {
    message.warning(t('请选择项目'));
    return;
  }
  savingScope.value = true;
  try {
    await updateProjectQuotaPolicy(projectPolicy.projectId, {
      quotaTokens: Number(projectPolicy.quotaTokens || 0),
      period: projectPolicy.period,
      status: 'active',
    });
    message.success(t('保存成功'));
    await loadScopes();
  } catch (error) {
    message.error((error as Error).message || t('保存失败'));
  } finally {
    savingScope.value = false;
  }
}

async function removeProject(projectId: string) {
  savingScope.value = true;
  try {
    await deleteQuotaProject(projectId);
    message.success(t('项目已删除'));
    await loadScopes();
  } catch (error) {
    message.error((error as Error).message || t('删除失败'));
  } finally {
    savingScope.value = false;
  }
}

async function savePolicies() {
  if (isQuotaBlank(orgForm.totalTokens)) {
    message.warning(t('请填写企业本周期总额度'));
    return;
  }
  if (isQuotaBlank(defaultForm.quotaTokens)) {
    message.warning(t('请填写新成员默认额度'));
    return;
  }
  if (!orgForm.unlimited && !orgForm.totalTokens && defaultForm.quotaTokens > 0) {
    message.warning(t('企业总额度为 0，不能为成员分配额度'));
    return;
  }
  savingPolicy.value = true;
  try {
    // 百分比 → 小数；后端约束 (0,1]
    orgForm.alertThresholdRatio = Math.min(1, Math.max(0.01, alertThresholdPercent.value / 100));
    await updateOrgQuotaPolicy({ ...orgForm, alertThresholdRatio: orgForm.alertThresholdRatio });
    await updateDefaultQuotaPolicy(defaultForm);
    message.success(t('保存成功'));
    settingsVisible.value = false;
    await reload();
  } finally {
    savingPolicy.value = false;
  }
}

function openSettings() {
  syncForms();
  settingsVisible.value = true;
}

function openEditor(row: UserAllocationItem) {
  if (!unlimitedOf() && !overview.value?.orgPolicy.totalTokens) {
    message.warning(t('企业总额度为 0，不能为用户分配额度'));
    return;
  }
  currentUser.value = row;
  Object.assign(userForm, {
    quotaTokens: row.quotaTokens,
    unlimited: row.unlimited,
    period: row.period,
    reason: '',
  });
  editorVisible.value = true;
}

async function saveUserPolicy() {
  if (!currentUser.value) return;
  if (isQuotaBlank(userForm.quotaTokens)) {
    message.warning(t('请填写本周期额度'));
    return;
  }
  if (!unlimitedOf() && !overview.value?.orgPolicy.totalTokens && userForm.quotaTokens > 0) {
    message.warning(t('企业总额度为 0，不能为用户分配额度'));
    return;
  }
  savingUser.value = true;
  try {
    await updateUserQuotaPolicy(currentUser.value.userId, {
      userId: currentUser.value.userId,
      quotaTokens: userForm.quotaTokens,
      unlimited: userForm.unlimited,
      period: userForm.period,
      reason: userForm.reason,
    });
    message.success(t('保存成功'));
    editorVisible.value = false;
    await reload();
  } finally {
    savingUser.value = false;
  }
}

async function openLogs() {
  logsVisible.value = true;
  logsPage.value = 1;
  await loadLogs();
}

async function loadLogs() {
  logsLoading.value = true;
  try {
    const result = await fetchAllocationLogs({ page: logsPage.value, pageSize: logsPageSize });
    logs.value = result.items;
    logsTotal.value = result.total;
  } finally {
    logsLoading.value = false;
  }
}

watch(() => filters.keyword, () => reload());
watch(
  () => route.query.open,
  () => consumeOpenQuotaQuery(),
);
onMounted(async () => {
  await reload();
  consumeOpenQuotaQuery();
});
</script>

<style scoped>
.traffic-page {
  height: 100%;
  min-height: 0;
  gap: 16px;
  overflow: hidden;
}

.metrics-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  padding: 12px;
}

.metric-card {
  border: 1px solid var(--mg-border);
  background: var(--mg-bg-surface);
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(29, 54, 110, 0.04);
}

.metric-main {
  display: flex;
  gap: 12px;
  align-items: center;
}

.metric-icon {
  display: inline-flex;
  width: 42px;
  height: 42px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  color: var(--mg-brand);
  background: var(--mg-info-bg);
}

.metric-icon :deep(svg),
.metric-icon svg {
  width: 22px;
  height: 22px;
  stroke: currentColor;
  fill: none;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.metric-label,
.metric-note {
  color: var(--mg-text-2);
  font-size: 12px;
}

.metric-value {
  margin-top: 4px;
  color: var(--mg-text-1);
  font-size: 24px;
  font-weight: 700;
}

.list-card {
  width: calc(100% - 24px);
  margin: -16px 12px 0;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(29, 54, 110, 0.04);
}

.list-card :deep(.n-card__content) {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.settings-form {
  padding-top: 2px;
}

.period-hint {
  margin-top: 2px;
  color: var(--mg-text-2);
  font-size: 12px;
  line-height: 1.6;
}

.period-hint span {
  display: block;
  color: var(--mg-text-1);
}

.wide-input {
  width: 100%;
}

.list-filter-row {
  padding: 16px 0 12px;
  border-bottom: 1px solid var(--mg-border);
  margin-bottom: 12px;
}

.table-shell {
  height: max(360px, calc(100vh - 250px));
  min-height: 0;
  overflow: hidden;
}

.table-spin,
.table-spin :deep(.n-spin-content),
.scope-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}

.scope-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--mg-border);
  border-radius: 10px;
  background: var(--mg-bg-surface);
}

.scope-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.scope-meta {
  color: var(--mg-text-3);
  font-size: 12px;
}

.allocation-table {
  height: 100%;
}

.filter-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.keyword-input {
  width: 280px;
}

.user-cell {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 260px;
}

.user-main-line {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.user-main-line strong {
  color: var(--mg-text-1);
  font-weight: 650;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.login-name {
  flex: 0 0 auto;
  color: var(--mg-text-3);
  font-size: 14px;
}

.user-contact-line {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  min-width: 0;
}

.user-contact-item {
  color: var(--mg-text-3);
  font-size: 14px;
  line-height: 20px;
  word-break: break-all;
}

.user-department {
  width: fit-content;
  max-width: 100%;
  border-radius: 4px;
  background: var(--mg-bg-subtle);
  color: var(--mg-text-3);
  font-size: 14px;
  line-height: 22px;
  padding: 0 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.usage-cell span {
  color: var(--mg-text-2);
  font-size: 12px;
}

.usage-cell {
  display: grid;
  gap: 6px;
  min-width: 180px;
}

.user-inline {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.user-inline span {
  color: var(--mg-text-2);
  font-size: 12px;
}

.logs-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-top: 14px;
  border-top: 1px solid var(--mg-border);
  color: var(--mg-text-2);
  font-size: 12px;
}

@media (max-width: 1100px) {
  .metrics-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .filter-toolbar {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
