<template>
  <div class="page-stack trust-page">
    <div class="trust-head">
      <div class="trust-head-title">
        <h2>{{ t('资产评级') }}</h2>
        <span class="trust-head-sub">{{ t('L1–L4 资产评级与变更管理') }}</span>
      </div>
      <n-space :size="10">
        <n-button secondary :loading="loading" @click="loadAll">{{ t('刷新') }}</n-button>
        <n-button secondary @click="openSettings">{{ t('降级设置') }}</n-button>
      </n-space>
    </div>

    <n-card class="shell-card" :bordered="false" size="small">
      <div class="dist-row">
        <div v-for="item in distributionCards" :key="item.level" class="dist-cell" :class="`dist-cell-${item.level.toLowerCase()}`">
          <div class="dist-level">{{ item.level }}</div>
          <div class="dist-count">{{ item.count }}</div>
          <div class="dist-label">{{ item.label }}</div>
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
import { computed, h, onMounted, reactive, ref } from 'vue';
import { useMessage, NButton, NSpace, NTag, type DataTableColumns, type FormInst, type FormRules } from 'naive-ui';
import { t } from '@/composables/i18n';
import { formatAdminDateTime } from '@/composables/adminTimezone';
import { fetchSkills, type SkillItem } from '@/api/skills';
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

const loading = ref(false);
const rows = ref<TrustRating[]>([]);
const distribution = ref<Record<TrustLevel, number> | null>(null);
const settings = ref<TrustRatingSettings | null>(null);
const skillNames = ref<Record<string, string>>({});

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

const filteredRows = computed(() => {
  const keyword = filters.value.level;
  if (!keyword) return rows.value;
  return rows.value.filter((row) => row.level === keyword);
});

const columns: DataTableColumns<TrustRating> = [
  {
    title: t('资产类型'),
    key: 'asset_type',
    width: 110,
    render: (row) => assetTypeText(row.asset_type),
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
    width: 170,
    render(row) {
      return h(NSpace, { size: 8 }, () => [
        h(NButton, { size: 'small', tertiary: true, onClick: () => openChange(row) }, () => t('变更')),
        h(NButton, { size: 'small', tertiary: true, loading: recomputingIds.value.has(`${row.asset_type}:${row.asset_key}`), onClick: () => recomputeRow(row) }, () => t('重新计算')),
      ]);
    },
  },
];

const pagination = { pageSize: 12 };

async function loadSkillNames() {
  try {
    const list: SkillItem[] = await fetchSkills();
    skillNames.value = Object.fromEntries(list.map((item) => [item.id, item.name]));
  } catch {
    // 名称解析失败时列表仅显示 asset_key，不阻塞评级展示。
    skillNames.value = {};
  }
}

async function loadList() {
  try {
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

async function loadAll() {
  loading.value = true;
  try {
    await Promise.all([loadList(), loadDistribution(), loadSettings()]);
  } finally {
    loading.value = false;
  }
}

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
  loadSkillNames();
});
</script>

<style scoped>
.trust-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
  min-height: 0;
}
.trust-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.trust-head-title h2 {
  margin: 0 0 4px;
  font-size: 20px;
  font-weight: 650;
  color: #0f172a;
}
.trust-head-sub {
  color: #8b97a8;
  font-size: 13px;
}
.shell-card {
  flex-shrink: 0;
}
.list-card {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.list-filter-row {
  display: flex;
  align-items: center;
  margin-bottom: 14px;
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
  color: #0f172a;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
  word-break: break-all;
}
.dist-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.dist-cell {
  border-radius: 8px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.dist-level {
  font-size: 12px;
  font-weight: 650;
  letter-spacing: 0.04em;
}
.dist-count {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.2;
}
.dist-label {
  font-size: 12px;
  opacity: 0.75;
}
.dist-cell-l1 {
  background: #f1f3f7;
  color: #5b6472;
}
.dist-cell-l2 {
  background: #e8f1fd;
  color: #2f6fd6;
}
.dist-cell-l3 {
  background: #fdf1e3;
  color: #d9821f;
}
.dist-cell-l4 {
  background: #e7f6ec;
  color: #1f9d57;
}
.change-meta {
  background: #f8fafc;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.change-meta-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  color: #475569;
}
.change-meta-row > span:first-child {
  width: 70px;
  color: #8b97a8;
}
.change-meta-row strong {
  color: #0f172a;
  word-break: break-all;
}
.change-hint {
  color: #8b97a8;
  font-size: 13px;
}
.change-history {
  margin-top: 16px;
  border-top: 1px solid #eef1f5;
  padding-top: 12px;
}
.change-history-title {
  font-size: 13px;
  font-weight: 650;
  color: #8b97a8;
  margin-bottom: 8px;
}
.change-history-row {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
  color: #475569;
  line-height: 26px;
}
.change-history-row > span:first-child {
  width: 90px;
  color: #8b97a8;
}
.settings-hint {
  margin-top: 12px;
  color: #8b97a8;
  font-size: 13px;
  line-height: 20px;
}
</style>