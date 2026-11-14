<script setup lang="ts">
import { t } from '@/composables/i18n';
import { computed, h, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NEmpty,
  NInput,
  NSelect,
  NSpace,
  NSwitch,
  NTag,
  useDialog,
  useMessage,
  type DataTableColumns,
} from 'naive-ui';
import PageIntro from '@/components/PageIntro.vue';
import {
  fetchPortalListings,
  publishPortalListing,
  unpublishPortalListing,
  type PortalAssetType,
  type PortalListing,
} from '@/api/portal';
import type { AssetCategory } from '@/api/capabilities';
import { useAssetCatalog } from '@/composables/useAssetCatalog';

const message = useMessage();
const dialog = useDialog();
const route = useRoute();
const router = useRouter();

const catalog = useAssetCatalog();

const loading = ref(false);
const errorMsg = ref('');
const rows = ref<PortalListing[]>([]);
const showUnpublished = ref(false);
const publishing = ref(false);

const form = ref({
  // 资产类别（FR-4 四类）：skill / mcp / tool / connector
  assetCategory: 'skill' as AssetCategory,
  assetKey: '',
  // 门户分类（可选，缺省 uncategorized）
  category: '',
});

/** 资产类别下拉 4 项（FR-4）。 */
const categoryOptions = [
  { label: t('技能'), value: 'skill' },
  { label: t('MCP 能力'), value: 'mcp' },
  { label: t('工具'), value: 'tool' },
  { label: t('连接器'), value: 'connector' },
];

/** 资产类别 → 后端 asset_type。 */
function assetTypeForCategory(category: AssetCategory): PortalAssetType {
  return category === 'skill' ? 'skill' : 'capability_asset';
}

/** 当前类别下已登记资产的下拉项。 */
const assetOptions = computed(() =>
  catalog.assets.value
    .filter((a) => a.category === form.value.assetCategory)
    .map((a) => ({
      label: `${a.name}（${a.assetKey}）${a.active ? '' : ` · ${t('不可用')}`}${a.listed ? ` · ${t('已上架')}` : ''}`,
      value: a.assetKey,
    })),
);

/** 选中的资产行（带出评级 + 启用状态 + owner）。 */
const selectedAsset = computed(
  () =>
    catalog.assets.value.find(
      (a) => a.assetType === assetTypeForCategory(form.value.assetCategory) && a.assetKey === form.value.assetKey,
    ) ?? null,
);

/** 资产不可用或已上架时禁止上架（对齐后端 409 / 403）。 */
const publishDisabledReason = computed(() => {
  if (!selectedAsset.value) return '';
  if (!selectedAsset.value.active) return t('该资产当前不可用，无法上架');
  if (selectedAsset.value.listed) return t('该资产已上架，无需重复操作');
  return '';
});

const publishedCount = computed(() => rows.value.filter((row) => row.published).length);

// 045 互链：资产中心带入 asset_type/asset_key 时聚焦到该资产
const filteredRows = computed(() => {
  const qType = route.query.asset_type as string | undefined;
  const qKey = route.query.asset_key as string | undefined;
  if (qType && qKey) {
    return rows.value.filter((row) => row.asset_type === qType && row.asset_key === qKey);
  }
  return rows.value;
});

/** 045 FR-11：回跳资产中心，查看资产的评级 / 上架 / 申领全局视图。 */
function goAssetCenter() {
  router.push('/assets');
}

async function load() {
  loading.value = true;
  errorMsg.value = '';
  try {
    rows.value = await fetchPortalListings({ publishedOnly: !showUnpublished.value });
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.detail || String(e);
  } finally {
    loading.value = false;
  }
}

/** 资产中心互链：按 asset_type/asset_key 预选资产类别与资产。 */
function applyQuerySelection() {
  const qType = route.query.asset_type as string | undefined;
  const qKey = route.query.asset_key as string | undefined;
  if (!qType || !qKey) return;
  const found = catalog.assets.value.find((a) => a.assetType === qType && a.assetKey === qKey);
  if (!found) return;
  form.value.assetCategory = found.category;
  form.value.assetKey = found.assetKey;
}

onMounted(async () => {
  await catalog.load();
  applyQuerySelection();
  await load();
});

function onCategoryChange(value: AssetCategory) {
  form.value.assetCategory = value;
  form.value.assetKey = '';
}

async function submitPublish() {
  const asset = selectedAsset.value;
  if (!asset) {
    message.warning(t('请选择要上架的资产'));
    return;
  }
  if (!asset.active) {
    message.warning(t('该资产当前不可用，无法上架'));
    return;
  }
  publishing.value = true;
  try {
    await publishPortalListing({
      assetType: asset.assetType,
      assetKey: asset.assetKey,
      category: form.value.category.trim(),
    });
    message.success(t('上架成功，门户目录即时生效'));
    form.value.assetKey = '';
    form.value.category = '';
    await load();
  } catch (e: any) {
    const status = e?.response?.status;
    const detail = e?.response?.data?.detail;
    if (status === 404) message.error(t('资产不存在'));
    else if (status === 409) message.error(t('资产当前不可用（未发布 / 非 active），无法上架'));
    else if (status === 403) message.error(t('无权上架该资产（仅 owner 或门户管理员）'));
    else message.error(detail || t('上架失败'));
  } finally {
    publishing.value = false;
  }
}

function confirmUnpublish(row: PortalListing) {
  dialog.warning({
    title: t('下架确认'),
    content: t('下架后该资产将从门户目录消失，但已开通的授权不会被撤销（需单独回收）。'),
    positiveText: t('确认下架'),
    negativeText: t('取消'),
    onPositiveClick: async () => {
      try {
        await unpublishPortalListing(row.asset_type, row.asset_key);
        message.success(t('已下架'));
        await load();
      } catch (e: any) {
        message.error(e?.response?.data?.detail || t('下架失败'));
      }
    },
  });
}

const columns = computed<DataTableColumns<PortalListing>>(() => [
  {
    title: t('资产'),
    key: 'asset_key',
    render: (row) => h('div', [h('strong', row.name || row.asset_key), h('div', { class: 'mg-caption' }, row.asset_key)]),
  },
  {
    title: t('类型'),
    key: 'asset_type',
    width: 110,
    render: (row) => h(NTag, { size: 'small', bordered: false }, { default: () => (row.asset_type === 'skill' ? t('技能') : t('能力资产')) }),
  },
  { title: t('分类'), key: 'category', width: 130 },
  {
    title: t('信任评级'),
    key: 'level',
    width: 110,
    render: (row) => {
      const asset = catalog.byKey.value.get(`${row.asset_type}:${row.asset_key}`);
      return asset?.level
        ? h(NTag, { size: 'small', bordered: false, type: 'info' }, { default: () => asset.level })
        : h('span', { class: 'mg-caption' }, '--');
    },
  },
  {
    title: t('状态'),
    key: 'published',
    width: 110,
    render: (row) =>
      h(
        NTag,
        { size: 'small', bordered: false, type: row.published ? 'success' : 'default' },
        { default: () => (row.published ? t('已上架') : t('已下架')) },
      ),
  },
  {
    title: t('资产可用性'),
    key: 'is_active_asset',
    width: 120,
    render: (row) => {
      const asset = catalog.byKey.value.get(`${row.asset_type}:${row.asset_key}`);
      const active = asset ? asset.active : row.is_active_asset !== false;
      return h(
        NTag,
        { size: 'small', bordered: false, type: active ? 'success' : 'warning' },
        { default: () => (active ? t('正常') : t('已停用')) },
      );
    },
  },
  { title: t('上架人'), key: 'published_by', width: 130 },
  {
    title: t('上架时间'),
    key: 'published_at',
    width: 180,
    render: (row) => (row.published_at ? new Date(row.published_at).toLocaleString() : '--'),
  },
  {
    title: t('操作'),
    key: 'actions',
    width: 110,
    render: (row) =>
      row.published
        ? h(NButton, { size: 'tiny', quaternary: true, type: 'warning', onClick: () => confirmUnpublish(row) }, { default: () => t('下架') })
        : null,
  },
]);
</script>

<template>
  <div class="mg-page">
    <PageIntro
      :title="t('资产上架')"
      :description="t('把本租户的技能 / 能力资产上架到用户侧资产门户，员工可自助申领。上架即时生效，下架不撤销存量授权。')"
    >
      <template #actions>
        <NButton size="small" quaternary @click="goAssetCenter">{{ t('资产中心') }}</NButton>
      </template>
    </PageIntro>

    <NAlert v-if="errorMsg || catalog.error.value" type="error" :bordered="false">
      {{ errorMsg || catalog.error.value }}
    </NAlert>

    <NCard :bordered="false" size="small" :title="t('上架资产')">
      <NSpace align="center" :size="12" wrap>
        <NSelect
          :value="form.assetCategory"
          :options="categoryOptions"
          style="width: 150px"
          @update:value="onCategoryChange"
        />
        <NSelect
          v-model:value="form.assetKey"
          :options="assetOptions"
          :placeholder="t('从已登记资产中选择')"
          :filterable="true"
          style="width: 340px"
        />
        <NInput v-model:value="form.category" :placeholder="t('分类（可选，缺省 uncategorized）')" style="width: 220px" />
        <NButton
          type="primary"
          :loading="publishing"
          :disabled="Boolean(publishDisabledReason)"
          @click="submitPublish"
        >
          {{ t('上架') }}
        </NButton>
      </NSpace>
      <p v-if="selectedAsset" class="mg-caption form-hint">
        {{ t('评级') }}：{{ selectedAsset.level || t('未评级') }} ·
        {{ t('启用状态') }}：{{ selectedAsset.active ? t('正常') : t('不可用') }} ·
        {{ t('owner') }}：{{ selectedAsset.owner || t('未指定') }}
      </p>
      <p v-else-if="publishDisabledReason" class="mg-caption form-hint">{{ publishDisabledReason }}</p>
      <p v-else class="mg-caption form-hint">
        {{ t('仅资产 owner 或持 portal:manage 权限的管理员可上架；资产必须处于可用状态。') }}
      </p>
    </NCard>

    <NCard :bordered="false" size="small">
      <template #header>
        <NSpace align="center" justify="space-between">
          <span>{{ t('已上架资产') }}</span>
          <NSpace align="center" :size="8">
            <span class="mg-caption">{{ t('共') }} {{ publishedCount }} {{ t('个已上架') }}</span>
            <NSwitch v-model:value="showUnpublished" size="small" @update:value="load">
              <template #checked>{{ t('含已下架') }}</template>
              <template #unchecked>{{ t('仅已上架') }}</template>
            </NSwitch>
            <NButton size="small" quaternary :loading="loading" @click="load">{{ t('刷新') }}</NButton>
          </NSpace>
        </NSpace>
      </template>

      <NDataTable v-if="filteredRows.length" :columns="columns" :data="filteredRows" :loading="loading" :bordered="false" size="small" :pagination="{ pageSize: 20 }" />
      <NEmpty v-else :description="rows.length ? t('该资产未上架') : t('还没有上架的资产')" />
    </NCard>
  </div>
</template>

<style scoped>
.form-hint {
  margin: var(--mg-space-2) 0 0;
}
</style>
