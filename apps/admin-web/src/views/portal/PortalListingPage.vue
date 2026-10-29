<script setup lang="ts">
import { t } from '@/composables/i18n';
import { computed, h, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
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

const message = useMessage();
const dialog = useDialog();
const route = useRoute();

const loading = ref(false);
const errorMsg = ref('');
const rows = ref<PortalListing[]>([]);
const showUnpublished = ref(false);
const publishing = ref(false);

const form = ref({
  assetType: 'skill' as PortalAssetType,
  assetKey: '',
  category: '',
});

const assetTypeOptions = [
  { label: t('技能'), value: 'skill' },
  { label: t('能力资产'), value: 'capability_asset' },
];

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

async function submitPublish() {
  const assetKey = form.value.assetKey.trim();
  if (!assetKey) {
    message.warning(t('请填写资产标识'));
    return;
  }
  publishing.value = true;
  try {
    await publishPortalListing({
      assetType: form.value.assetType,
      assetKey,
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
    render: (row) =>
      h(
        NTag,
        { size: 'small', bordered: false, type: row.is_active_asset === false ? 'warning' : 'success' },
        { default: () => (row.is_active_asset === false ? t('已停用') : t('正常')) },
      ),
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

onMounted(load);
</script>

<template>
  <div class="mg-page">
    <PageIntro
      :title="t('门户上架')"
      :description="t('把本租户的技能 / 能力资产上架到用户侧资产门户，员工可自助申领。上架即时生效，下架不撤销存量授权。')"
    />

    <NAlert v-if="errorMsg" type="error" :bordered="false">{{ errorMsg }}</NAlert>

    <NCard :bordered="false" size="small" :title="t('上架资产')">
      <NSpace align="center" :size="12" wrap>
        <NSelect v-model:value="form.assetType" :options="assetTypeOptions" style="width: 160px" />
        <NInput v-model:value="form.assetKey" :placeholder="t('资产标识（技能 _id / 能力 asset_id）')" style="width: 320px" />
        <NInput v-model:value="form.category" :placeholder="t('分类（可选，缺省 uncategorized）')" style="width: 220px" />
        <NButton type="primary" :loading="publishing" @click="submitPublish">{{ t('上架') }}</NButton>
      </NSpace>
      <p class="mg-caption form-hint">
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
