<template>
  <div class="mg-page--flush">
    <PageIntro :title="t('资产评级')" :description="t('L1–L4 资产评级与变更管理')">
      <template #actions>
        <n-button secondary :loading="loading" @click="loadAll">{{ t('刷新') }}</n-button>
        <n-button secondary @click="openSettings">{{ t('降级设置') }}</n-button>
      </template>
    </PageIntro>

    <n-card class="shell-card" :bordered="false" size="small">
      <div class="mg-level-grid">
        <div
          v-for="item in distributionCards"
          :key="item.level"
          class="mg-level-cell"
          :class="`mg-level-cell--${item.level.toLowerCase()}`"
        >
          <div class="mg-level-cell__level">{{ item.level }}</div>
          <div class="mg-level-cell__count">{{ item.count }}</div>
          <div class="mg-level-cell__label">{{ item.label }}</div>
        </div>
      </div>
    </n-card>

    <n-card class="list-card shell-card" :bordered="false" size="large">
      <div class="list-filter-row">
        <div class="filter-toolbar">
          <n-space align="center" :size="10" class="filter-left">
            <n-select
              v-model:value="filters.assetType"
              clearable
              :options="assetTypeOptions"
              :placeholder="t('资产类型')"
              style="width: 160px"
              @update:value="loadList"
            />
            <n-select
              v-model:value="filters.level"
              clearable
              :options="levelOptions"
              :placeholder="t('级别')"
              style="width: 140px"
            />
          </n-space>
        </div>
      </div>

      <div class="table-shell">
        <n-spin :show="loading" class="table-spin">
          <n-data-table
            class="trust-table"
            flex-height
            :columns="columns"
            :data="filteredRows"
            :bordered="false"
            :pagination="pagination"
            :row-key="rowKey"
          />
        </n-spin>
      </div>
    </n-card>
  </div>

  <n-modal v-model:show="changeVisible" preset="card" :title="t('变更评级')" style="width: 620px">
    <div v-if="changeTarget" class="change-meta">
      <div class="change-meta-row">
        <span>{{ t('资产') }}</span>
        <strong>{{ assetDisplayName(changeTarget) }}</strong>
      </div>
      <div class="change-meta-row">
        <span>{{ t('当前级别') }}</span>
        <n-tag size="small" :bordered="false" :type="levelTagType(changeTarget.level)">{{ changeTarget.level }}</n-tag>
        <span class="change-hint" v-if="changeTarget.previous_level">{{ t('上次级别') }} {{ changeTarget.previous_level }}</span>
      </div>
    </div>

    <n-form ref="changeFormRef" :model="changeForm" :rules="changeRules" label-placement="left" label-width="110">
      <n-form-item :label="t('目标级别')" path="targetLevel">
        <n-select v-model:value="changeForm.targetLevel" :options="levelOptions" />
      </n-form-item>
      <n-form-item :label="t('变更原因')" path="reason">
        <n-select v-model:value="changeForm.reason" :options="reasonOptions" />
      </n-form-item>
      <n-form-item v-if="needsEvidence" :label="t('质量证据')" path="evidence">
        <n-input
          v-model:value="changeForm.evidence"
          type="textarea"
          :rows="3"
          :placeholder="t('升级至 L2 及以上需提供质量证据；升级至 L3/L4 必须通过质量检查（quality_passed）')"
        />
      </n-form-item>
    </n-form>

    <div v-if="changeTarget" class="change-history">
      <div class="change-history-title">{{ t('最近变更') }}</div>
      <div class="change-history-row"><span>{{ t('变更原因') }}</span><span>{{ changeTarget.reason || '—' }}</span></div>
      <div class="change-history-row"><span>{{ t('上次级别') }}</span><span>{{ changeTarget.previous_level || '—' }}</span></div>
      <div class="change-history-row"><span>{{ t('操作人') }}</span><span>{{ changeTarget.updated_by || '—' }}</span></div>
      <div class="change-history-row"><span>{{ t('更新时间') }}</span><span>{{ formatAdminDateTime(changeTarget.updated_at, t('暂无')) }}</span></div>
      <div class="change-history-row"><span>{{ t('不达标天数') }}</span><span>{{ changeTarget.below_streak_days }}</span></div>
      <div class="change-history-row"><span>{{ t('待弃用') }}</span><span>{{ changeTarget.deprecate_pending ? t('是') : t('否') }}</span></div>
    </div>

    <template #footer>
      <n-space justify="end">
        <n-button @click="changeVisible = false">{{ t('取消') }}</n-button>
        <n-button secondary :loading="recomputing" @click="recomputeCurrent">{{ t('重新计算') }}</n-button>
        <n-button type="primary" :loading="changing" @click="submitChange">{{ t('确认变更') }}</n-button>
      </n-space>
    </template>
  </n-modal>

  <n-modal v-model:show="settingsVisible" preset="card" :title="t('降级设置')" style="width: 560px">
    <n-form label-placement="left" label-width="110">
      <n-form-item :label="t('启用自动降级')">
        <n-switch v-model:value="settingsForm.enabled" />
      </n-form-item>
      <n-form-item :label="t('降级观察窗口（天）')">
        <n-input-number v-model:value="settingsForm.windowDays" :min="1" :max="365" :show-button="false" style="width: 200px" />
      </n-form-item>
    </n-form>
    <div class="settings-hint">{{ t('开启后，连续 N 天质量不达标的资产将按评级自动降一级；关闭时保留已累计天数。') }}</div>
    <template #footer>
      <n-space justify="end">
        <n-button @click="settingsVisible = false">{{ t('取消') }}</n-button>
        <n-button type="primary" :loading="savingSettings" @click="saveSettings">{{ t('保存设置') }}</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, h, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useMessage, NButton, NSpace, NTag, type DataTableColumns, type FormInst, type FormRules } from 'naive-ui';
import { useAssetCatalog } from '@/composables/useAssetCatalog';
import { fetchPortalApprovals, type PortalApprovalItem } from '@/api/portal';
import { t } from '@/composables/i18n';
import PageIntro from '@/components/PageIntro.vue';
import { formatAdminDateTime } from '@/composables/adminTimezone';
import {
  changeTrustRating,
  fetchTrustRatingDistribution,
  fetchTrustRatingSettings,
  fetchTrustRatings,
  recomputeTrustRating,
  updateTrustRatingSettings,
  type TrustAssetType,
  type TrustLevel,
  type TrustRating,
  type TrustRatingSettings,
} from '@/api/trustRatings';

const message = useMessage();
const route = useRoute();
const router = useRouter();

// 045 资产中心共享数据源（§4 同一 join）：评级列表与门户上架共用一份资产视图。
const catalog = useAssetCatalog();

const loading = ref(false);
const rows = ref<TrustRating[]>([]);
const distribution = ref<Record<TrustLevel, number> | null>(null);
const settings = ref<TrustRatingSettings | null>(null);
const approvalRows = ref<PortalApprovalItem[]>([]);

/** 045 FR-10：按 `asset_type:asset_key` 聚合最近申领（申请数 + 最近申请时间）。 */
const approvalStats = computed(() => {
  const map = new Map<string, { count: number; recent: string | null }>();
  for (const item of approvalRows.value) {
    const key = `${item.asset_type}:${item.asset_key}`;
    const cur = map.get(key) ?? { count: 0, recent: null };
    cur.count += 1;
    if (item.applied_at && (!cur.recent || item.applied_at > cur.recent)) {
      cur.recent = item.applied_at;
    }
    map.set(key, cur);
  }
  return map;
});

/** 技能名称：取自共享数据源，避免单独再发一次 /skills。 */
const skillNames = computed(() => {
  const map: Record<string, string> = {};
  catalog.skills.value.forEach((item) => { map[item.id] = item.name; });
  return map;
});

const filters = ref<{ assetType: TrustAssetType | null; level: TrustLevel | null }>({
  assetType: null,
  level: null,
});
const recomputingIds = ref<Set<string>>(new Set());
const recomputing = computed(() => recomputingIds.value.size > 0);

const rowKey = (row: TrustRating) => `${row.asset_type}:${row.asset_key}`;

const LEVELS: TrustLevel[] = ['L1', 'L2', 'L3', 'L4'];

const assetTypeOptions = computed(() => [
  { label: t('Skill'), value: 'skill' },
  { label: t('Agent'), value: 'agent' },
  { label: t('工作流'), value: 'workflow' },
]);

const levelOptions = computed(() => LEVELS.map((level) => ({ label: level, value: level })));

const reasonOptions = computed(() => [
  { label: t('人工升级'), value: 'manual_promote' },
  { label: t('人工降级'), value: 'manual_demote' },
]);

function levelIndex(level: string): number {
  return LEVELS.indexOf(level as TrustLevel);
}

function levelTagType(level: string): 'default' | 'info' | 'warning' | 'success' {
  // L1 灰 / L2 蓝 / L3 橙 / L4 绿
  if (level === 'L4') return 'success';
  if (level === 'L3') return 'warning';
  if (level === 'L2') return 'info';
  return 'default';
}

function assetTypeText(type: TrustAssetType): string {
  if (type === 'skill') return t('Skill');
  if (type === 'agent') return t('Agent');
  return t('工作流');
}

/** 045 FR-10：资产类型徽标配色。 */
function assetTypeTagType(type: TrustAssetType): 'info' | 'success' | 'warning' {
  if (type === 'skill') return 'info';
  if (type === 'agent') return 'success';
  return 'warning';
}

function assetDisplayName(row: TrustRating): string {
  const name = row.asset_type === 'skill' ? skillNames.value[row.asset_key] : '';
  return name ? `${name}（${row.asset_key}）` : row.asset_key;
}

const distributionCards = computed(() =>
  LEVELS.map((level) => ({
    level,
    count: distribution.value?.[level] ?? 0,
    label: levelLabel(level),
  })),
);

function levelLabel(level: string): string {
  if (level === 'L4') return t('高可信');
  if (level === 'L3') return t('较可信');
  if (level === 'L2') return t('试用');
  return t('初始');
}

/** 045 FR-9：`?asset=<type>:<key>` 单参数（如 `skill:<id>`）拆成类型 + key。 */
function parseAssetParam(raw: unknown): { type?: string; key?: string } {
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (typeof value !== 'string' || !value) return {};
  const idx = value.indexOf(':');
  if (idx <= 0 || idx === value.length - 1) return {};
  return { type: value.slice(0, idx), key: value.slice(idx + 1) };
}

/** 045 互链：从 query 取定位坐标，兼容 `asset` 与 `asset_type`/`asset_key` 两种写法。 */
function queryAssetFocus(): { type?: string; key?: string } {
  const single = parseAssetParam(route.query.asset);
  return {
    type: (route.query.asset_type as string | undefined) ?? single.type,
    key: (route.query.asset_key as string | undefined) ?? single.key,
  };
}

const filteredRows = computed(() => {
  let result = rows.value;
  if (filters.value.level) {
    result = result.filter((row) => row.level === filters.value.level);
  }
  // 045 互链：聚焦到 query 指定的资产
  const focus = queryAssetFocus();
  if (focus.type && focus.key) {
    result = result.filter((row) => row.asset_type === focus.type && row.asset_key === focus.key);
  }
  return result;
});

const columns: DataTableColumns<TrustRating> = [
  {
    title: t('资产类型'),
    key: 'asset_type',
    width: 110,
    render: (row) =>
      h(
        NTag,
        { size: 'small', bordered: false, type: assetTypeTagType(row.asset_type) },
        { default: () => assetTypeText(row.asset_type) },
      ),
  },
  {
    title: t('资产 Key'),
    key: 'asset_key',
    render: (row) => h('span', { class: 'key-cell', title: row.asset_key }, row.asset_key),
  },
  {
    title: t('名称'),
    key: 'name',
    render: (row) => assetDisplayName(row),
  },
  {
    title: t('级别'),
    key: 'level',
    width: 90,
    render: (row) => h(NTag, { size: 'small', bordered: false, type: levelTagType(row.level) }, { default: () => row.level }),
  },
  {
    title: t('上架'),
    key: 'listed',
    width: 100,
    render: (row) => {
      // 门户上架仅覆盖 skill / capability_asset；agent / workflow 无门户入口。
      if (row.asset_type !== 'skill') return h('span', { class: 'mg-caption' }, '—');
      const listed = catalog.byKey.value.get(`skill:${row.asset_key}`)?.listed ?? false;
      return h(
        NTag,
        { size: 'small', bordered: false, type: listed ? 'success' : 'default' },
        { default: () => (listed ? t('已上架') : t('未上架')) },
      );
    },
  },
  {
    title: t('最近申领'),
    key: 'approval',
    width: 180,
    render: (row) => {
      // 045 FR-10：最近申领统计（申请数 + 最近申请时间），无申领显示 —。
      const stat = approvalStats.value.get(`${row.asset_type}:${row.asset_key}`);
      if (!stat) return h('span', { class: 'mg-caption' }, '—');
      return h('div', { class: 'approval-stat' }, [
        h('span', {}, `${stat.count} ${t('次')}`),
        stat.recent ? h('span', { class: 'mg-caption' }, ` · ${formatAdminDateTime(stat.recent, '—')}`) : null,
      ]);
    },
  },
  {
    title: t('变更原因'),
    key: 'reason',
    width: 130,
    render: (row) => row.reason || '—',
  },
  {
    title: t('Owner'),
    key: 'owner_id',
    width: 120,
    render: (row) => row.owner_id || row.created_by || '—',
  },
  {
    title: t('更新时间'),
    key: 'updated_at',
    width: 170,
    render: (row) => formatAdminDateTime(row.updated_at, t('暂无')),
  },
  {
    title: t('操作'),
    key: 'actions',
    width: 240,
    render(row) {
      return h(NSpace, { size: 8 }, () => [
        h(NButton, { size: 'small', tertiary: true, onClick: () => openChange(row) }, () => t('变更')),
        h(NButton, { size: 'small', tertiary: true, loading: recomputingIds.value.has(`${row.asset_type}:${row.asset_key}`), onClick: () => recomputeRow(row) }, () => t('重新计算')),
        h(NButton, { size: 'small', tertiary: true, onClick: () => manageAsset(row) }, () => t('管理')),
      ]);
    },
  },
];

const pagination = { pageSize: 12 };

/** 「管理」入口：技能跳技能配置页，其余跳资产中心。 */
function manageAsset(row: TrustRating): void {
  if (row.asset_type === 'skill') {
    router.push({ path: `/skills/${encodeURIComponent(row.asset_key)}/config` });
    return;
  }
  router.push({ path: '/assets', query: { asset_type: row.asset_type, asset_key: row.asset_key } });
}

async function loadList() {
  try {
    // 045 互链：仅对合法 TrustAssetType 设置 API 过滤；capability_asset 等取全部后客户端过滤
    const qType = queryAssetFocus().type;
    if (qType && ['skill', 'agent', 'workflow'].includes(qType)) {
      filters.value.assetType = qType as TrustAssetType;
    } else {
      filters.value.assetType = null;
    }
    rows.value = await fetchTrustRatings({ assetType: filters.value.assetType ?? undefined });
  } catch (err: any) {
    message.error(err?.response?.data?.detail || t('加载评级失败'));
  }
}

async function loadDistribution() {
  try {
    distribution.value = await fetchTrustRatingDistribution();
  } catch {
    distribution.value = null;
  }
}

async function loadSettings() {
  try {
    settings.value = await fetchTrustRatingSettings();
  } catch {
    settings.value = null;
  }
}

/** 045 FR-10：拉全部门户申领，供评级页「最近申领」统计列使用。 */
async function loadApprovals() {
  try {
    approvalRows.value = await fetchPortalApprovals({ status: 'all' });
  } catch {
    approvalRows.value = [];
  }
}

async function loadAll() {
  loading.value = true;
  try {
    await Promise.all([loadList(), loadDistribution(), loadSettings(), loadApprovals()]);
  } finally {
    loading.value = false;
  }
  // 045 FR-9：从技能页带 `?asset=skill:<id>` 进来时，定位后直接打开变更弹层。
  focusAssetFromQuery();
}

/** 045 FR-9：query 指向的资产若存在，自动打开变更弹层。 */
function focusAssetFromQuery(): void {
  const focus = queryAssetFocus();
  if (!focus.type || !focus.key) return;
  if (changeVisible.value) return;
  const row = rows.value.find((item) => item.asset_type === focus.type && item.asset_key === focus.key);
  if (row) openChange(row);
}

// 045 互链：路由 query 变化时重载评级列表（资产中心 / 技能页切换资产）
watch(
  () => route.query,
  () => {
    const focus = queryAssetFocus();
    if (focus.type || focus.key) {
      loadList().then(() => focusAssetFromQuery());
    }
  },
);

// --- change modal ----------------------------------------------------------

const changeVisible = ref(false);
const changing = ref(false);
const changeTarget = ref<TrustRating | null>(null);
const changeFormRef = ref<FormInst | null>(null);
const changeForm = reactive<{ targetLevel: TrustLevel | null; reason: string | null; evidence: string }>({
  targetLevel: null,
  reason: null,
  evidence: '',
});

const needsEvidence = computed(() => {
  const current = changeTarget.value?.level;
  const target = changeForm.targetLevel;
  if (!current || !target) return false;
  return levelIndex(target) > levelIndex(current) && levelIndex(target) >= 1;
});

const changeRules: FormRules = {
  targetLevel: [{ required: true, message: t('请选择目标级别'), trigger: ['change', 'blur'] }],
  reason: [{ required: true, message: t('请选择变更原因'), trigger: ['change', 'blur'] }],
  evidence: [
    {
      validator: () => !needsEvidence.value || changeForm.evidence.trim().length > 0,
      message: t('请填写质量证据'),
      trigger: ['input', 'blur'],
    },
  ],
};

function openChange(row: TrustRating) {
  changeTarget.value = row;
  changeForm.targetLevel = row.level;
  changeForm.reason = null;
  changeForm.evidence = '';
  changeVisible.value = true;
}

async function recomputeCurrent() {
  if (!changeTarget.value) return;
  await doRecompute(changeTarget.value);
}

async function recomputeRow(row: TrustRating) {
  await doRecompute(row);
}

async function doRecompute(row: TrustRating) {
  const key = `${row.asset_type}:${row.asset_key}`;
  recomputingIds.value.add(key);
  try {
    const result = await recomputeTrustRating(row.asset_type, row.asset_key);
    const latest = result.rating;
    if (changeTarget.value?.asset_key === row.asset_key) {
      changeTarget.value = latest;
    }
    message.success(t('重新计算完成：{level}', { level: latest.level }));
    await Promise.all([loadList(), loadDistribution()]);
  } catch (err: any) {
    message.error(err?.response?.data?.detail || t('重新计算失败'));
  } finally {
    recomputingIds.value.delete(key);
  }
}

async function submitChange() {
  const target = changeTarget.value;
  if (!target) return;
  try {
    await changeFormRef.value?.validate();
  } catch {
    return;
  }
  changing.value = true;
  try {
    await changeTrustRating(target.asset_type, target.asset_key, {
      targetLevel: changeForm.targetLevel!,
      reason: changeForm.reason!,
      evidence: needsEvidence.value ? { quality_passed: true, note: changeForm.evidence.trim() } : undefined,
    });
    message.success(t('变更已提交'));
    changeVisible.value = false;
    await Promise.all([loadList(), loadDistribution()]);
  } catch (err: any) {
    message.error(err?.response?.data?.detail || t('变更失败'));
  } finally {
    changing.value = false;
  }
}

// --- settings modal --------------------------------------------------------

const settingsVisible = ref(false);
const savingSettings = ref(false);
const settingsForm = reactive<{ enabled: boolean; windowDays: number }>({ enabled: true, windowDays: 21 });

function openSettings() {
  const current = settings.value;
  settingsForm.enabled = current?.enabled ?? true;
  settingsForm.windowDays = current?.window_days ?? 21;
  settingsVisible.value = true;
}

async function saveSettings() {
  savingSettings.value = true;
  try {
    settings.value = await updateTrustRatingSettings({
      enabled: settingsForm.enabled,
      windowDays: settingsForm.windowDays,
    });
    message.success(t('设置已保存'));
    settingsVisible.value = false;
  } catch (err: any) {
    message.error(err?.response?.data?.detail || t('设置保存失败'));
  } finally {
    savingSettings.value = false;
  }
}

onMounted(() => {
  loadAll();
  catalog.load();
});
</script>

<style scoped>
/* 页面骨架由 .mg-page--flush + .mg-level-grid 提供（见 styles/base.css），
   此处只保留本页特有的布局，颜色一律引用设计令牌。 */
.list-card {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.list-filter-row {
  display: flex;
  align-items: center;
  margin-bottom: var(--mg-space-3);
}

.filter-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.filter-left {
  flex-wrap: wrap;
}

.table-shell {
  flex: 1;
  min-height: 0;
}

.table-spin {
  height: 100%;
}

.trust-table {
  height: 100%;
}

.key-cell {
  color: var(--mg-text-1);
  font-family: var(--mg-font-mono);
  font-size: var(--mg-font-size-sm);
  word-break: break-all;
}

.change-meta {
  background: var(--mg-bg-subtle);
  border-radius: var(--mg-radius-md);
  padding: var(--mg-space-3) var(--mg-space-4);
  margin-bottom: var(--mg-space-4);
  display: flex;
  flex-direction: column;
  gap: var(--mg-space-2);
}

.change-meta-row {
  display: flex;
  align-items: center;
  gap: var(--mg-space-3);
  font-size: var(--mg-font-size-base);
  color: var(--mg-text-2);
}

.change-meta-row > span:first-child {
  width: 70px;
  color: var(--mg-text-3);
}

.change-meta-row strong {
  color: var(--mg-text-1);
  word-break: break-all;
}

.change-hint {
  color: var(--mg-text-3);
  font-size: var(--mg-font-size-sm);
}

.change-history {
  margin-top: var(--mg-space-4);
  border-top: 1px solid var(--mg-divider);
  padding-top: var(--mg-space-3);
}

.change-history-title {
  font-size: var(--mg-font-size-sm);
  font-weight: var(--mg-weight-semibold);
  color: var(--mg-text-3);
  margin-bottom: var(--mg-space-2);
}

.change-history-row {
  display: flex;
  align-items: center;
  gap: var(--mg-space-3);
  font-size: var(--mg-font-size-sm);
  color: var(--mg-text-2);
  line-height: 26px;
}

.change-history-row > span:first-child {
  width: 90px;
  color: var(--mg-text-3);
}

.settings-hint {
  margin-top: var(--mg-space-3);
  color: var(--mg-text-3);
  font-size: var(--mg-font-size-sm);
  line-height: 20px;
}
</style>
