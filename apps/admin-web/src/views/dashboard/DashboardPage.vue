<template>
  <div class="dashboard-page">
    <n-spin :show="loading">
      <n-tabs v-model:value="activeTab" type="line" class="dash-tabs">
        <n-tab-pane name="overview" :tab="t('总览')">
        <!-- 008 T003 / T008 — overview tab -->
        <div class="tab-body">
          <section class="metrics-grid">
            <article v-for="metric in metricCards" :key="metric.key" class="metric-card">
              <div class="metric-head">
                <span class="metric-icon" v-html="metric.icon"></span>
                <span class="metric-label">{{ metric.label }}</span>
              </div>
              <div class="metric-value">{{ metric.value }}</div>
              <div class="metric-note">{{ metric.note }}</div>
            </article>
          </section>
          <section class="content-grid observation-grid">
            <n-card class="panel-card span-8 activity-panel" :bordered="false" size="large">
              <template #header>
                <div class="panel-header">
                  <span>{{ t('最近运行观察') }}</span>
                  <n-button quaternary size="small" @click="go('/token-stats')">{{ t('查看全部') }}</n-button>
                </div>
              </template>
              <div v-if="recentActivity.length" class="activity-table">
                <div class="table-row table-head">
                  <span>{{ t('任务') }}</span>
                  <span>{{ t('模型') }}</span>
                  <span>{{ t('状态') }}</span>
                  <span>{{ t('Token') }}</span>
                  <span>{{ t('耗时') }}</span>
                </div>
                <div v-for="(item, index) in visibleRecentActivity" :key="item.requestId || item.sessionId || `activity-${index}`" class="table-row">
                  <div class="activity-main">
                    <strong>{{ item.title ? t(item.title) : t('LLM 调用') }}</strong>
                    <small>{{ item.userName || t('未知用户') }} · {{ item.departmentName || t('未分配部门') }} · {{ formatTime(item.createdAt) }}</small>
                  </div>
                  <span class="table-muted table-model" :title="item.modelName || t('默认模型')">{{ item.modelName || t('默认模型') }}</span>
                  <n-tag size="small" :type="item.status === 'failed' ? 'error' : 'success'" :bordered="false">
                    {{ item.status === 'failed' ? t('失败') : t('完成') }}
                  </n-tag>
                  <span>{{ formatNumber(item.totalTokens) }}</span>
                  <span>{{ formatDuration(item.durationMs) }}</span>
                </div>
              </div>
              <div v-else class="empty-state">
                <div class="empty-icon">
                  <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path d="M4 19V5" />
                    <path d="M4 19h16" />
                    <path d="M8 15v-4" />
                    <path d="M12 15V8" />
                    <path d="M16 15v-2" />
                  </svg>
                </div>
                <div class="empty-title">{{ t('暂无运行记录') }}</div>
                <div class="empty-copy">{{ t('当前组织还没有 LLM 调用数据，产生调用后会在这里展示最近活动。') }}</div>
              </div>
            </n-card>

            <div class="span-4 side-stack">
              <section class="deployment-card" :class="`health-${healthStatus}`">
                <div class="deployment-head">
                  <div class="deployment-title">
                    <span class="health-dot" aria-hidden="true"></span>
                    <strong>{{ overview?.billing.orgName || t('组织空间') }}</strong>
                  </div>
                  <n-tag v-if="tierLabel" size="small" :bordered="false" :type="isCommunity ? 'success' : 'info'">{{ tierLabel }}</n-tag>
                </div>
                <div class="deployment-status">
                  <strong>{{ healthLabel }}</strong>
                  <span>{{ healthNote }}</span>
                </div>
                <div class="deployment-facts">
                  <span><strong>{{ overview?.billing.currentMembersCount ?? 0 }}</strong> {{ memberCapacityLabel }}</span>
                  <span><strong>{{ overview?.billing.isOwnModel ? t('已开启') : t('未开启') }}</strong> {{ t('自有模型') }}</span>
                </div>
                <component
                  :is="ProductDashboardBillingActions"
                  v-if="ProductDashboardBillingActions && overview"
                  :billing="overview.billing"
                />
              </section>

              <n-card class="panel-card todo-panel" :bordered="false" size="large">
                <template #header>
                  <div class="panel-header">
                    <span>{{ t('待处理事项') }}</span>
                    <n-button quaternary size="small" @click="loadOverview">{{ t('刷新') }}</n-button>
                  </div>
                </template>
                <div v-if="todos.length" class="todo-list">
                  <button v-for="todo in todos" :key="todo.title" class="todo-item" type="button" @click="go(todo.route)">
                    <span class="todo-mark" :class="`todo-${todo.level}`"></span>
                    <span class="todo-copy">
                      <strong>{{ translateDashboardText(todo.title) }}</strong>
                      <small>{{ translateDashboardText(todo.description) }}</small>
                    </span>
                    <span class="todo-arrow">›</span>
                  </button>
                </div>
                <div v-else class="empty-state compact">
                  <div class="empty-title">{{ t('暂无待处理事项') }}</div>
                  <div class="empty-copy">{{ t('模型、Skill、工具与近 24 小时运行状态未发现需要立即处理的问题。') }}</div>
                </div>
              </n-card>
            </div>
          </section>

          <section class="content-grid">
            <n-card class="panel-card span-8" :bordered="false" size="large">
              <template #header>{{ t('核心资产状态') }}</template>
              <div class="asset-grid">
                <button v-for="asset in assetCards" :key="asset.key" class="asset-card" type="button" @click="go(asset.route)">
                  <div class="asset-title">{{ asset.title }}</div>
                  <div class="asset-value">{{ asset.value }}</div>
                  <div class="asset-lines">
                    <span v-for="line in asset.lines" :key="line">{{ line }}</span>
                  </div>
                </button>
              </div>
            </n-card>
            <n-card class="panel-card span-4" :bordered="false" size="large">
              <template #header>{{ t('快捷操作') }}</template>
              <div class="quick-grid">
                <n-button v-for="action in quickActions" :key="action.label" secondary @click="go(action.route)">
                  <template #icon>
                    <span class="button-icon" v-html="action.icon"></span>
                  </template>
                  {{ action.label }}
                </n-button>
              </div>
            </n-card>
          </section>
        </div>
        </n-tab-pane>
        <n-tab-pane name="cost" :tab="t('成本')">
        <!-- 008 T013 — cost tab -->
        <div class="tab-body">
          <section class="content-grid">
            <n-card class="panel-card span-8" :bordered="false" size="large">
              <template #header>
                <div class="panel-header">
                  <span>{{ t('成本维度') }}</span>
                  <n-button quaternary size="small" @click="loadOverview">{{ t('刷新') }}</n-button>
                </div>
              </template>
              <div v-if="costModels.length" class="cost-list">
                <div v-for="model in costModels" :key="model.model" class="cost-row">
                  <span class="cost-model">{{ model.model }}</span>
                  <span class="cost-share">{{ formatPercent(model.share) }}</span>
                  <span class="cost-value">¥{{ formatCost(model.cost) }}</span>
                </div>
              </div>
              <div v-else class="empty-state compact">
                <div class="empty-title">{{ t('暂无成本数据') }}</div>
                <div class="empty-copy">{{ t('产生 LLM 调用后，成本将按模型占比在这里展示。') }}</div>
              </div>
            </n-card>
            <n-card class="panel-card span-4" :bordered="false" size="large">
              <template #header>{{ t('成本合计与预测') }}</template>
              <div class="cost-summary">
                <div class="cost-summary-row">
                  <span>{{ t('总成本') }}</span>
                  <strong>¥{{ formatCost(costTotal) }}</strong>
                </div>
                <div class="cost-summary-row">
                  <span>{{ t('Token 总量') }}</span>
                  <strong>{{ formatCompact(costTokens) }}</strong>
                </div>
                <div class="cost-summary-row" v-if="costForecast !== null">
                  <span>{{ t('下期预测（近 4 期均值）') }}</span>
                  <strong>¥{{ formatCost(costForecast) }}</strong>
                </div>
                <div class="cost-summary-row" v-else>
                  <span>{{ t('下期预测') }}</span>
                  <strong>—</strong>
                </div>
              </div>
            </n-card>
          </section>
        </div>
        </n-tab-pane>
        <n-tab-pane name="usage" :tab="t('使用')">
        <!-- 008 T016 — usage tab -->
        <div class="tab-body">
          <n-select
            v-model:value="usageGrain"
            :options="grainOptions"
            size="small"
            class="grain-select"
            @update:value="onGrainChange"
          />
          <section class="content-grid">
            <n-card class="panel-card span-8" :bordered="false" size="large">
              <template #header>{{ t('调用量时间序列') }}</template>
              <div v-if="usageTimeSeries.length" class="series-bars">
                <div v-for="point in usageTimeSeries" :key="point.bucket" class="series-bar">
                  <span class="series-label">{{ point.bucket }}</span>
                  <div class="series-track">
                    <div class="series-fill" :style="{ width: seriesWidth(point.calls) + '%' }"></div>
                  </div>
                  <span class="series-value">{{ formatNumber(point.calls) }}</span>
                </div>
              </div>
              <div v-else class="empty-state compact">
                <div class="empty-title">{{ t('暂无调用数据') }}</div>
                <div class="empty-copy">{{ t('产生 LLM 调用后，将按当前时间粒度在这里展示调用量。') }}</div>
              </div>
            </n-card>
            <n-card class="panel-card span-4" :bordered="false" size="large">
              <template #header>{{ t('活跃用户与频次') }}</template>
              <div class="usage-facts">
                <div class="usage-fact-row"><span>{{ t('活跃用户') }}</span><strong>{{ activeUserCount }}</strong></div>
                <div class="usage-fact-row"><span>{{ t('Skill 调用 Top') }}</span><strong>{{ skillTopLabel }}</strong></div>
                <div class="usage-fact-row"><span>{{ t('检索类型 Top') }}</span><strong>{{ retrievalTopLabel }}</strong></div>
              </div>
            </n-card>
          </section>
        </div>
        </n-tab-pane>
        <n-tab-pane name="quality" :tab="t('质量')">
        <!-- 008 T020 — quality tab -->
        <div class="tab-body">
          <section class="metrics-grid quality-grid">
            <article v-for="metric in qualityCards" :key="metric.key" class="metric-card">
              <div class="metric-head">
                <span class="metric-icon" v-html="metric.icon"></span>
                <span class="metric-label">{{ metric.label }}</span>
              </div>
              <div class="metric-value">{{ metric.value }}</div>
              <div class="metric-note">{{ metric.note }}</div>
            </article>
          </section>
          <n-card class="panel-card" :bordered="false" size="large">
            <template #header>{{ t('异常下钻') }}</template>
            <div v-if="qualityAnomalies.length" class="anomaly-list">
              <div v-for="item in qualityAnomalies" :key="item.requestId || item.sessionId" class="anomaly-row">
                <span class="anomaly-id">{{ item.requestId || item.sessionId || '—' }}</span>
                <n-tag size="small" :bordered="false" type="error">{{ t('失败') }}</n-tag>
                <span class="anomaly-preview">{{ item.title || t('LLM 调用') }}</span>
              </div>
            </div>
            <div v-else class="empty-state compact">
              <div class="empty-title">{{ t('近期无异常调用') }}</div>
              <div class="empty-copy">{{ t('近 24 小时调用全部成功，或尚未产生调用。') }}</div>
            </div>
          </n-card>
        </div>
        </n-tab-pane>
        <n-tab-pane name="trend" :tab="t('趋势')">
        <!-- 008 T023 — trend tab -->
        <div class="tab-body">
          <section class="content-grid">
            <n-card class="panel-card span-8" :bordered="false" size="large">
              <template #header>{{ t('环比 / 同比') }}</template>
              <div class="trend-deltas">
                <div class="delta-row">
                  <span>{{ t('成本环比') }}</span>
                  <strong :class="deltaClass(qualityTrend.costMomPct)">{{ deltaText(qualityTrend.costMomPct) }}</strong>
                </div>
                <div class="delta-row">
                  <span>{{ t('调用量环比') }}</span>
                  <strong :class="deltaClass(qualityTrend.callsMomPct)">{{ deltaText(qualityTrend.callsMomPct) }}</strong>
                </div>
                <div class="delta-row" v-if="qualityTrend.costYoyPct !== null && qualityTrend.costYoyPct !== undefined">
                  <span>{{ t('成本同比') }}</span>
                  <strong :class="deltaClass(qualityTrend.costYoyPct)">{{ deltaText(qualityTrend.costYoyPct) }}</strong>
                </div>
              </div>
            </n-card>
            <n-card class="panel-card span-4" :bordered="false" size="large">
              <template #header>{{ t('瓶颈 Top 5') }}</template>
              <div v-if="bottlenecks.length" class="bottleneck-list">
                <div v-for="item in bottlenecks" :key="item.key" class="bottleneck-row">
                  <span class="bottleneck-key">{{ item.key }}</span>
                  <span class="bottleneck-cost">¥{{ formatCost(item.cost) }}</span>
                  <span class="bottleneck-duration">{{ formatDuration(item.avgDurationMs) }}</span>
                </div>
              </div>
              <div v-else class="empty-state compact">
                <div class="empty-title">{{ t('暂无瓶颈数据') }}</div>
                <div class="empty-copy">{{ t('产生调用后，将按成本/耗时排名展示瓶颈。') }}</div>
              </div>
            </n-card>
          </section>
        </div>
        </n-tab-pane>
      </n-tabs>

      <n-alert v-if="errorText" type="warning" :bordered="false" closable @close="errorText = ''">
        {{ errorText }}
      </n-alert>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { apiClient } from '@/api/client';
import { t, useLocale } from '@/composables/i18n';
import { formatAdminShortDateTime } from '@/composables/adminTimezone';
import { translateDashboardText } from './dashboardText';
import adminProductUiExtension from '@movo-admin-product-extension';

type HealthStatus = 'healthy' | 'warning' | 'critical';
type TodoLevel = 'error' | 'warning' | 'info';

interface DashboardOverview {
  billing: {
    orgName: string;
    edition: 'community' | 'cloud';
    tier: string;
    billingEnabled: boolean;
    currentMembersCount: number;
    userLimit: number | null;
    totalPoints: number;
    usedPoints: number;
    remainingPoints: number;
    isOwnModel: boolean;
  };
  health: {
    status: HealthStatus;
    warnings: string[];
  };
  metrics: {
    calls24h: number;
    tokens24h: number;
    cost24h: number;
    activeUsers24h: number;
    activeDepartments24h: number;
    failedCalls24h: number;
    successRate24h: number | null;
    avgDurationMs24h: number;
    lastCalledAt: string | null;
  };
  assets: {
    users: { total: number; disabled: number; departments: number };
    models: { total: number; active: number; failedHealth: number };
    skills: { total: number; enabled: number; workflow: number; writingStyle: number };
    tools: { total: number; active: number; mcp: number; failed: number; untested: number };
  };
  quality: {
    totalCalls: number;
    successRate: number | null;
    anomalyRate: number | null;
    manualInterventionRate: number | null;
    p50Ms: number | null;
    p95Ms: number | null;
    avgMs: number | null;
    approvalPending: number;
  };
  trend: {
    costMomPct: number | null;
    callsMomPct: number | null;
    costYoyPct: number | null;
    bottlenecks: Array<{ dimension: string; key: string; calls: number; cost: number; avgDurationMs: number }>;
  };
  usage: {
    calls: number;
    activeUsers: { day?: number; week?: number; month?: number };
    skillRanking: Array<{ key: string; count: number }>;
    retrievalRanking: Array<{ key: string; count: number }>;
    timeSeries: Array<{ bucket: string; calls: number; tokens: number; cost: number; active_users?: number }>;
  };
  todos: Array<{ level: TodoLevel; title: string; description: string; route: string }>;
  recentActivity: Array<{
    requestId: string;
    sessionId: string;
    userName: string;
    departmentName: string;
    modelName: string;
    title: string;
    status: string;
    totalTokens: number;
    durationMs: number;
    createdAt: string | null;
  }>;
}

const router = useRouter();
const { locale } = useLocale();
const ProductDashboardBillingActions = adminProductUiExtension.dashboardBillingActions;
const overview = ref<DashboardOverview | null>(null);
const loading = ref(false);
const errorText = ref('');

const emptyMetrics = {
  calls24h: 0,
  tokens24h: 0,
  cost24h: 0,
  activeUsers24h: 0,
  activeDepartments24h: 0,
  failedCalls24h: 0,
  successRate24h: null,
  avgDurationMs24h: 0,
  lastCalledAt: null,
};

const metrics = computed(() => overview.value?.metrics || emptyMetrics);
const assets = computed(() => overview.value?.assets);
const todos = computed(() => overview.value?.todos || []);
const recentActivity = computed(() => overview.value?.recentActivity || []);
const visibleRecentActivity = computed(() => recentActivity.value.slice(0, 4));
const healthStatus = computed<HealthStatus>(() => overview.value?.health.status || 'healthy');
const isCommunity = computed(() => overview.value?.billing.edition === 'community');
const tierLabel = computed(() => {
  // The community edition carries no tier label: it is the default self-hosted
  // deployment, and the tag read as noise in the dashboard header. Paid tiers
  // below keep their own labels.
  if (isCommunity.value) return '';
  const tier = overview.value?.billing.tier;
  if (tier === 'plus') return t('Plus 个人版');
  if (tier === 'pro') return t('专业团队版');
  if (tier === 'enterprise') return t('企业定制版');
  return t('免费版');
});
const memberCapacityLabel = computed(() => {
  const limit = overview.value?.billing.userLimit;
  return limit === null || limit === undefined ? t('名成员 · 不限人数') : t(' / {count} 名成员', { count: limit });
});
const healthLabel = computed(() => {
  if (healthStatus.value === 'critical') return t('需要处理');
  if (healthStatus.value === 'warning') return t('有待确认');
  return t('运行正常');
});
const healthNote = computed(() => {
  const warnings = overview.value?.health.warnings || [];
  if (!warnings.length) return t('模型、工具与近 24 小时调用未发现明显异常');
  return warnings.slice(0, 2).map(w => t(w)).join('、');
});

const icons = {
  calls: '<svg viewBox="0 0 24 24" fill="none"><path d="M4 5h16v14H4z"/><path d="M8 9h8"/><path d="M8 13h5"/></svg>',
  tokens: '<svg viewBox="0 0 24 24" fill="none"><path d="M12 3 4 7l8 4 8-4-8-4Z"/><path d="m4 12 8 4 8-4"/><path d="m4 17 8 4 8-4"/></svg>',
  users: '<svg viewBox="0 0 24 24" fill="none"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
  success: '<svg viewBox="0 0 24 24" fill="none"><path d="M20 6 9 17l-5-5"/><path d="M21 12a9 9 0 1 1-3-6.7"/></svg>',
  cost: '<svg viewBox="0 0 24 24" fill="none"><path d="M12 2v20"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>',
  speed: '<svg viewBox="0 0 24 24" fill="none"><path d="M12 14l4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/></svg>',
  plus: '<svg viewBox="0 0 24 24" fill="none"><path d="M12 5v14"/><path d="M5 12h14"/></svg>',
  chart: '<svg viewBox="0 0 24 24" fill="none"><path d="M4 19V5"/><path d="M4 19h16"/><path d="M8 16v-5"/><path d="M12 16V8"/><path d="M16 16v-3"/></svg>',
};

const metricCards = computed(() => [
  {
    key: 'calls',
    label: t('近 24h 调用'),
    value: formatNumber(metrics.value.calls24h),
    note: t('失败 {count} 次', { count: metrics.value.failedCalls24h }),
    icon: icons.calls,
  },
  {
    key: 'tokens',
    label: t('Token 消耗'),
    value: formatCompact(metrics.value.tokens24h),
    note: t('近 24 小时累计'),
    icon: icons.tokens,
  },
  {
    key: 'users',
    label: t('活跃用户'),
    value: formatNumber(metrics.value.activeUsers24h),
    note: t('{count} 个活跃部门', { count: metrics.value.activeDepartments24h }),
    icon: icons.users,
  },
  {
    key: 'success',
    label: t('成功率'),
    value: metrics.value.successRate24h === null ? '—' : `${metrics.value.successRate24h}%`,
    note: metrics.value.lastCalledAt ? t('最近 {time}', { time: formatTime(metrics.value.lastCalledAt) }) : t('暂无调用'),
    icon: icons.success,
  },
  {
    key: 'cost',
    label: t('近 24h 成本'),
    value: `¥${formatCost(metrics.value.cost24h)}`,
    note: t('按当前估算价计算'),
    icon: icons.cost,
  },
  {
    key: 'speed',
    label: t('平均耗时'),
    value: formatDuration(metrics.value.avgDurationMs24h),
    note: t('仅统计有起止时间的调用'),
    icon: icons.speed,
  },
]);

const assetCards = computed(() => {
  const current = assets.value;
  return [
    {
      key: 'models',
      title: t('模型中心'),
      value: current ? formatNumber(current.models.total) : '0',
      lines: current
        ? [t('企业模型') + ' ' + current.models.total, t('启用') + ' ' + current.models.active, t('异常') + ' ' + current.models.failedHealth]
        : [t('暂无数据')],
      route: '/models',
    },
    {
      key: 'skills',
      title: t('Skill管理'),
      value: current ? formatNumber(current.skills.total) : '0',
      lines: current
        ? [t('启用') + ' ' + current.skills.enabled, t('工作流') + ' ' + current.skills.workflow, t('写作规范') + ' ' + current.skills.writingStyle]
        : [t('暂无数据')],
      route: '/skills',
    },
    {
      key: 'tools',
      title: t('工具与 MCP'),
      value: current ? formatNumber(current.tools.total) : '0',
      lines: current
        ? [t('启用') + ' ' + current.tools.active, 'MCP ' + current.tools.mcp, t('失败') + ' ' + current.tools.failed + ' / ' + t('未设置') + ' ' + current.tools.untested]
        : [t('暂无数据')],
      route: '/tools',
    },
    {
      key: 'users',
      title: t('用户管理'),
      value: current ? formatNumber(current.users.total) : '0',
      lines: current ? [t('部门') + ' ' + current.users.departments, t('停用') + ' ' + current.users.disabled] : [t('暂无数据')],
      route: '/organizations/users',
    },
  ];
});

const quickActions = computed(() => [
  { label: t('新增模型'), route: '/models', icon: icons.plus },
  { label: t('添加 Skill'), route: '/skills', icon: icons.plus },
  { label: t('新增工具连接'), route: '/tools/new', icon: icons.plus },
  { label: t('用户管理'), route: '/organizations/users', icon: icons.users },
  { label: t('Token 统计'), route: '/token-stats', icon: icons.chart },
]);

const emptyUsage = {
  calls: 0,
  activeUsers: {} as { day?: number; week?: number; month?: number },
  skillRanking: [] as Array<{ key: string; count: number }>,
  retrievalRanking: [] as Array<{ key: string; count: number }>,
  timeSeries: [] as Array<{ bucket: string; calls: number; tokens: number; cost: number; active_users?: number }>,
};

// --- 008 T003/T008/T013/T016/T020/T023: four-dimension tabs ------------------
const activeTab = ref<'overview' | 'cost' | 'usage' | 'quality' | 'trend'>('overview');
const usageGrain = ref<'day' | 'week' | 'month'>('day');

const usage = computed(() => overview.value?.usage || emptyUsage);
const quality = computed(() => overview.value?.quality);
const trend = computed(() => overview.value?.trend);

const qualityCards = computed(() => {
  const q = quality.value;
  if (!q) return [];
  return [
    {
      key: 'success',
      label: t('成功率'),
      value: q.successRate === null ? '—' : `${q.successRate}%`,
      note: t('近 24h 成功 / 总调用'),
      icon: icons.success,
    },
    {
      key: 'p50',
      label: t('响应 P50'),
      value: q.p50Ms === null ? '—' : formatDuration(q.p50Ms),
      note: t('中位响应时长'),
      icon: icons.speed,
    },
    {
      key: 'p95',
      label: t('响应 P95'),
      value: q.p95Ms === null ? '—' : formatDuration(q.p95Ms),
      note: t('95 分位响应时长'),
      icon: icons.speed,
    },
    {
      key: 'anomaly',
      label: t('异常率'),
      value: q.anomalyRate === null ? '—' : `${q.anomalyRate}%`,
      note: t('失败 + 超时占比'),
      icon: icons.cost,
    },
    {
      key: 'manual',
      label: t('人工介入率'),
      value: q.manualInterventionRate === null ? '—' : `${q.manualInterventionRate}%`,
      note: t('审批挂起 / 总调用'),
      icon: icons.users,
    },
  ];
});

const qualityAnomalies = computed(() =>
  recentActivity.value.filter((item) => item.status === 'failed').slice(0, 10),
);

const qualityTrend = computed(() => trend.value || {
  costMomPct: null as number | null,
  callsMomPct: null as number | null,
  costYoyPct: null as number | null,
  bottlenecks: [] as Array<{ dimension: string; key: string; calls: number; cost: number; avgDurationMs: number }>,
});
const bottlenecks = computed(() => qualityTrend.value.bottlenecks || []);

// --- T013 cost tab: per-model cost share + forecast --------------------------
const costModels = computed(() => {
  // 008 cost tab: per-model rows come from the trend bottlenecks (dimension=model)
  const byModel = (qualityTrend.value.bottlenecks || []).filter((row) => row.dimension === 'model');
  const models = byModel.map((row) => ({ model: row.key, cost: row.cost, share: 0 }));
  const total = models.reduce((sum, row) => sum + row.cost, 0);
  for (const row of models) {
    row.share = total > 0 ? Math.round((row.cost / total) * 100) : 0;
  }
  return models.sort((a, b) => b.cost - a.cost);
});
const costTotal = computed(() => metrics.value.cost24h);
const costTokens = computed(() => metrics.value.tokens24h);
const costForecast = computed(() => {
  // T012 forecast: moving average of the last 4 periods (008 clarify OQ-5)
  const series = usage.value.timeSeries;
  if (series.length === 0) return null;
  const window = series.slice(-4);
  const average = window.reduce((sum, point) => sum + point.cost, 0) / window.length;
  return Math.round(average * 1000000) / 1000000;
});

// --- T016 usage tab: time series + dedup + ranking ----------------------------
const grainOptions = computed(() => [
  { label: t('日'), value: 'day' },
  { label: t('周'), value: 'week' },
  { label: t('月'), value: 'month' },
]);
function onGrainChange(_grain: 'day' | 'week' | 'month') {
  // Non-day grains merge day buckets client-side (the overview API returns day grain).
}
const usageTimeSeries = computed(() => {
  const points = usage.value.timeSeries;
  if (usageGrain.value === 'day') return points.slice(-14);
  const grouped: Record<string, number> = {};
  for (const point of points) {
    const groupKey = usageGrain.value === 'week' ? point.bucket.slice(0, 7) : point.bucket.slice(0, 7);
    grouped[groupKey] = (grouped[groupKey] || 0) + point.calls;
  }
  return Object.entries(grouped)
    .map(([bucket, calls]) => ({ bucket, calls }))
    .sort((a, b) => a.bucket.localeCompare(b.bucket));
});
const seriesMaxCalls = computed(() =>
  Math.max(1, ...usageTimeSeries.value.map((point) => point.calls)),
);
function seriesWidth(calls: number) {
  return Math.round((calls / seriesMaxCalls.value) * 100);
}
const activeUserCount = computed(() => {
  const active = usage.value.activeUsers;
  return active?.[usageGrain.value] ?? active?.day ?? 0;
});
const skillTopLabel = computed(() => {
  const top = usage.value.skillRanking[0];
  return top ? `${top.key} (${top.count})` : '—';
});
const retrievalTopLabel = computed(() => {
  const top = usage.value.retrievalRanking[0];
  return top ? `${top.key} (${top.count})` : '—';
});

// --- T020/T023 helpers: delta display -----------------------------------------
function deltaClass(pct: number | null | undefined) {
  if (pct === null || pct === undefined) return '';
  if (pct > 0) return 'delta-up';
  if (pct < 0) return 'delta-down';
  return '';
}
function deltaText(pct: number | null | undefined) {
  if (pct === null || pct === undefined) return '—';
  const sign = pct > 0 ? '+' : '';
  return `${sign}${pct.toFixed(1)}%`;
}

function formatPercent(value: number) {
  return `${Math.round(Number(value || 0))}%`;
}

async function loadOverview() {
  loading.value = true;
  errorText.value = '';
  try {
    const { data } = await apiClient.get<DashboardOverview>('/api/dashboard/overview');
    overview.value = data;
  } catch (err: any) {
    errorText.value = err?.response?.data?.detail || err?.message || t('工作台数据加载失败');
    overview.value = null;
  } finally {
    loading.value = false;
  }
}

function go(route: string) {
  router.push(route);
}

function formatNumber(value: number) {
  return new Intl.NumberFormat('zh-CN').format(Number(value || 0));
}

function formatCompact(value: number) {
  const amount = Number(value || 0);
  if (locale.value === 'en-US') {
    if (amount >= 1000000000) return `${(amount / 1000000000).toFixed(1)}B`;
    if (amount >= 1000000) return `${(amount / 1000000).toFixed(1)}M`;
    if (amount >= 1000) return `${(amount / 1000).toFixed(1)}K`;
    return formatNumber(amount);
  }
  if (amount >= 100000000) return `${(amount / 100000000).toFixed(1)} 亿`;
  if (amount >= 10000) return `${(amount / 10000).toFixed(1)} 万`;
  return formatNumber(amount);
}

function formatCost(value: number) {
  return Number(value || 0).toFixed(2);
}

function formatDuration(value: number) {
  const ms = Number(value || 0);
  if (!ms) return '—';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function formatTime(value: string | null) {
  return formatAdminShortDateTime(value, t('暂无'));
}

onMounted(loadOverview);
</script>

<style scoped>
.dashboard-page {
  height: calc(100vh - 64px);
  overflow-y: auto;
  padding: 18px;
  background: #f4f7fb;
}

/* 008 T003 — dashboard tab layout */
.dash-tabs {
  display: flex;
  flex-direction: column;
}
.dash-tabs :deep(.n-tabs-nav) {
  margin-bottom: 14px;
}
.tab-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.grain-select {
  width: 140px;
}
.cost-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.cost-row {
  display: grid;
  grid-template-columns: 1fr 70px 90px;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid #e6edf7;
  border-radius: 10px;
  background: #fbfdff;
  font-size: 13px;
  color: #33415c;
}
.cost-row .cost-model {
  font-weight: 600;
}
.cost-row .cost-share {
  color: #64748b;
  text-align: right;
}
.cost-row .cost-value {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.cost-summary {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.cost-summary-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid #eef2f9;
  font-size: 13px;
  color: #475569;
}
.cost-summary-row strong {
  color: #17366f;
  font-size: 15px;
}
.series-bars {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.series-bar {
  display: grid;
  grid-template-columns: 90px 1fr 60px;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: #475569;
}
.series-track {
  height: 10px;
  background: #eef2f9;
  border-radius: 999px;
  overflow: hidden;
}
.series-fill {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #06b6d4);
  border-radius: 999px;
}
.series-value {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.usage-facts {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.usage-fact-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  font-size: 13px;
  color: #475569;
  padding-bottom: 8px;
  border-bottom: 1px solid #eef2f9;
}
.usage-fact-row strong {
  color: #17366f;
  font-size: 15px;
}
.quality-grid {
  grid-template-columns: repeat(5, minmax(0, 1fr));
}
.anomaly-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.anomaly-row {
  display: grid;
  grid-template-columns: 180px auto 1fr;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid #fde2e2;
  background: #fff5f5;
  border-radius: 10px;
  font-size: 12px;
}
.anomaly-id {
  color: #b91c1c;
  font-family: ui-monospace, monospace;
}
.anomaly-preview {
  color: #475569;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.trend-deltas {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.delta-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid #eef2f9;
  font-size: 13px;
  color: #475569;
}
.delta-row strong {
  font-size: 15px;
  color: #17366f;
}
.delta-up {
  color: #16a34a !important;
}
.delta-down {
  color: #dc2626 !important;
}
.bottleneck-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.bottleneck-row {
  display: grid;
  grid-template-columns: 1fr 80px 80px;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid #e6edf7;
  border-radius: 10px;
  background: #fbfdff;
  font-size: 12px;
  color: #33415c;
}
.bottleneck-key {
  font-weight: 600;
}
.bottleneck-cost,
.bottleneck-duration {
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: #64748b;
}

.side-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.observation-grid {
  align-items: stretch;
}

.activity-panel,
.observation-grid .side-stack {
  height: clamp(380px, 38vh, 420px);
}

.activity-panel :deep(.n-card__content) {
  min-height: 0;
  overflow: hidden;
}

.todo-panel :deep(.n-card__content) {
  min-height: 0;
  overflow-y: auto;
}

.todo-panel {
  min-height: 0;
  flex: 1;
}

.todo-panel .empty-state.compact {
  min-height: 120px;
}

.deployment-card {
  padding: 14px 16px;
  border: 1px solid #dbe5f5;
  border-radius: 12px;
  background: linear-gradient(135deg, #ffffff 0%, #f5f8ff 100%);
  box-shadow: 0 8px 22px rgba(28, 55, 104, 0.06);
}

.deployment-head,
.deployment-title,
.deployment-facts {
  display: flex;
  align-items: center;
}

.deployment-head {
  justify-content: space-between;
  gap: 10px;
}

.deployment-title {
  min-width: 0;
  gap: 10px;
}

.deployment-title strong {
  overflow: hidden;
  color: #15213b;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.deployment-status {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-top: 9px;
}

.deployment-status strong {
  flex: 0 0 auto;
  color: #17366f;
  font-size: 13px;
}

.deployment-status span {
  overflow: hidden;
  color: #64748b;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.deployment-facts {
  flex-wrap: wrap;
  gap: 6px 16px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #e6edf7;
  color: #64748b;
  font-size: 12px;
}

.deployment-facts strong {
  color: #17366f;
}

.health-dot {
  flex: 0 0 auto;
  width: 9px;
  height: 9px;
  border-radius: 999px;
  background: #10b981;
  box-shadow: 0 0 0 4px rgba(16, 185, 129, 0.13);
}

.health-warning .health-dot {
  background: #f59e0b;
  box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.14);
}

.health-critical .health-dot {
  background: #ef4444;
  box-shadow: 0 0 0 4px rgba(239, 68, 68, 0.13);
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.metric-card,
.asset-card,
.todo-item {
  transition: border-color 0.2s ease, background-color 0.2s ease, box-shadow 0.2s ease;
}

.metric-card {
  min-height: 132px;
  padding: 14px;
  border: 1px solid #dfe7f3;
  border-radius: 12px;
  background: #ffffff;
}

.metric-head {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #64748b;
}

.metric-icon,
.button-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.metric-icon {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: #eef4ff;
  color: #2563eb;
}

.metric-icon :deep(svg),
.button-icon :deep(svg),
.empty-icon svg {
  width: 16px;
  height: 16px;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.metric-label {
  font-size: 13px;
  font-weight: 700;
}

.metric-value {
  margin-top: 16px;
  color: #0f172a;
  font-size: 25px;
  font-weight: 800;
  line-height: 1.1;
}

.metric-note {
  margin-top: 8px;
  color: #64748b;
  font-size: 12px;
}

.content-grid {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 14px;
}

.span-8 {
  grid-column: span 8;
}

.span-4 {
  grid-column: span 4;
}

.panel-card {
  border-radius: 12px;
  box-shadow: 0 8px 22px rgba(28, 55, 104, 0.06);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}

.activity-table {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.table-row {
  display: grid;
  grid-template-columns: minmax(240px, 1fr) 150px 74px 88px 70px;
  gap: 12px;
  align-items: center;
  min-height: 54px;
  padding: 10px 8px;
  border-bottom: 1px solid #eef2f7;
  color: #1f2a44;
  font-size: 13px;
}

.table-head {
  min-height: 34px;
  color: #64748b;
  font-size: 12px;
  font-weight: 800;
}

.activity-main {
  min-width: 0;
}

.activity-main strong,
.activity-main small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.activity-main strong {
  color: #13213d;
}

.activity-main small,
.table-muted {
  color: #64748b;
}

.table-model {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.todo-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.todo-item {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr) 18px;
  gap: 10px;
  align-items: center;
  width: 100%;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #ffffff;
  cursor: pointer;
  text-align: left;
}

.todo-item:hover,
.asset-card:hover {
  border-color: #9db8f8;
  background: #f8fbff;
  box-shadow: 0 8px 20px rgba(37, 99, 235, 0.08);
}

.todo-mark {
  width: 8px;
  height: 34px;
  border-radius: 999px;
  background: #3b82f6;
}

.todo-error {
  background: #ef4444;
}

.todo-warning {
  background: #f59e0b;
}

.todo-info {
  background: #3b82f6;
}

.todo-copy {
  min-width: 0;
}

.todo-copy strong,
.todo-copy small {
  display: block;
}

.todo-copy strong {
  color: #14213d;
  font-size: 13px;
}

.todo-copy small {
  margin-top: 2px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.4;
}

.todo-arrow {
  color: #94a3b8;
  font-size: 20px;
}

.asset-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.asset-card {
  min-height: 146px;
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #ffffff;
  cursor: pointer;
  text-align: left;
}

.asset-title {
  color: #64748b;
  font-size: 13px;
  font-weight: 700;
}

.asset-value {
  margin-top: 10px;
  color: #0f172a;
  font-size: 30px;
  font-weight: 800;
  line-height: 1;
}

.asset-lines {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-top: 14px;
  color: #64748b;
  font-size: 12px;
}

.quick-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
}

.button-icon {
  width: 16px;
  height: 16px;
}

.empty-state {
  display: grid;
  place-items: center;
  min-height: 260px;
  padding: 30px;
  color: #64748b;
  text-align: center;
}

.empty-state.compact {
  min-height: 220px;
}

.empty-icon {
  display: grid;
  place-items: center;
  width: 46px;
  height: 46px;
  border-radius: 10px;
  background: #eef4ff;
  color: #2563eb;
}

.empty-title {
  margin-top: 12px;
  color: #17233f;
  font-size: 15px;
  font-weight: 800;
}

.empty-copy {
  max-width: 360px;
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.5;
}

@media (max-width: 1400px) {
  .metrics-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .asset-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .dashboard-page {
    height: auto;
    min-height: calc(100vh - 64px);
    padding: 12px;
  }

  .metrics-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .span-8,
  .span-4 {
    grid-column: 1 / -1;
  }

  .activity-panel,
  .observation-grid .side-stack {
    height: auto;
  }

  .activity-panel :deep(.n-card__content),
  .todo-panel :deep(.n-card__content) {
    overflow-y: visible;
  }

  .table-head {
    display: none;
  }

  .table-row {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .table-row > :nth-child(2),
  .table-row > :nth-child(4),
  .table-row > :nth-child(5) {
    display: none;
  }
}

@media (max-width: 520px) {
  .metrics-grid,
  .asset-grid {
    grid-template-columns: 1fr;
  }

  .deployment-status span {
    white-space: normal;
  }
}

@media (prefers-reduced-motion: reduce) {
  .metric-card,
  .asset-card,
  .todo-item {
    transition: none;
  }
}
</style>
