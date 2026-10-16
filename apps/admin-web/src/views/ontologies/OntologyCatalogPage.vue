<script setup lang="ts">
import { t } from '@/composables/i18n';
import { computed, h, onMounted, ref } from 'vue';
import { NAlert, NTag, useDialog, useMessage, type DataTableColumns } from 'naive-ui';
import PageIntro from '@/components/PageIntro.vue';
import {
  fetchMyOntologies,
  fetchOntologyCatalog,
  fetchOntologyPermissionConfig,
  syncOntologies,
  updateOntologyPermissionConfig,
  type MyOntologyScope,
  type OntologyCatalogItem,
  type OntologyPermissionConfig,
} from '@/api/ontologies';

const message = useMessage();
const dialog = useDialog();
const loading = ref(false);
const syncing = ref(false);
const toggling = ref(false);
const tab = ref<'mine' | 'all'>('mine');
const mine = ref<MyOntologyScope>({ tenantId: '', userId: '', ontologies: [], count: 0 });
const catalog = ref<OntologyCatalogItem[]>([]);
const config = ref<OntologyPermissionConfig | null>(null);

const enforcing = computed(() => Boolean(config.value?.enforce));

async function load() {
  loading.value = true;
  try {
    const [myScope, rows, cfg] = await Promise.all([
      fetchMyOntologies(),
      fetchOntologyCatalog(),
      fetchOntologyPermissionConfig(),
    ]);
    mine.value = myScope;
    catalog.value = rows;
    config.value = cfg;
  } catch (error: any) {
    message.error(error?.response?.data?.detail || error?.message || t('本体清单加载失败'));
  } finally {
    loading.value = false;
  }
}

async function runSync() {
  syncing.value = true;
  try {
    const result = await syncOntologies();
    message.success(t('已同步 {count} 个本体', { count: result.synced }));
    await load();
  } catch (error: any) {
    message.error(error?.response?.data?.detail || error?.message || t('同步失败'));
  } finally {
    syncing.value = false;
  }
}

function confirmToggle() {
  const next = !enforcing.value;
  dialog.warning({
    title: next ? t('开启本体数据权限拦截') : t('关闭本体数据权限拦截'),
    content: next
      ? t('开启后未匹配到授权的主体将按 fail-closed 判定为不可见（deny）。请确认已完成授权配置。')
      : t('关闭后本体数据权限仅做配置与预演，不拦截任何查询。'),
    positiveText: next ? t('开启拦截') : t('关闭拦截'),
    negativeText: t('取消'),
    async onPositiveClick() {
      toggling.value = true;
      try {
        config.value = await updateOntologyPermissionConfig({ enforce: next });
        message.success(next ? t('已开启本体数据权限拦截') : t('已关闭本体数据权限拦截'));
      } catch (error: any) {
        message.error(error?.response?.data?.detail || error?.message || t('开关更新失败'));
      } finally {
        toggling.value = false;
      }
    },
  });
}

const catalogColumns: DataTableColumns<OntologyCatalogItem> = [
  { title: t('本体标识'), key: 'ontologyId', render: row => h('strong', row.ontologyId) },
  {
    title: t('类型标签'),
    key: 'entityTypes',
    render: row =>
      row.entityTypes.length
        ? h(
            'div',
            { class: 'tag-row' },
            row.entityTypes.map(type => h(NTag, { size: 'small', bordered: false }, { default: () => type })),
          )
        : h('span', { class: 'muted' }, t('未标注')),
  },
  { title: t('索引实体数'), key: 'entityCount', width: 120 },
  { title: t('已配置授权'), key: 'grantCount', width: 120 },
];

onMounted(load);
</script>

<template>
  <div class="page-stack ontology-page">
    <n-card :bordered="false" size="large">
      <div class="ontology-content">
        <div class="page-head">
          <PageIntro
            :title="t('本体清单')"
            :description="t('本体定义与数据都在业务系统，MOGO 侧只做只读展示与数据范围授权。')"
          />
          <n-space>
            <n-button :loading="syncing" @click="runSync">{{ t('同步清单') }}</n-button>
            <n-button :type="enforcing ? 'warning' : 'primary'" :loading="toggling" @click="confirmToggle">
              {{ enforcing ? t('关闭拦截') : t('开启拦截') }}
            </n-button>
          </n-space>
        </div>

        <n-alert v-if="config" :type="enforcing ? 'success' : 'warning'" :bordered="false">
          <template v-if="enforcing">
            {{ t('本体数据权限已开启：未匹配到授权的主体按 fail-closed 判定为不可见（deny）。') }}
          </template>
          <template v-else>
            {{ t('当前为预演模式（enforce=false）：授权只做配置与展示，不拦截任何查询。') }}
          </template>
          <span class="muted"> · {{ t('配置版本 rev={rev}', { rev: config?.rev ?? 0 }) }}</span>
        </n-alert>

        <n-tabs v-model:value="tab" type="line" animated>
          <n-tab-pane name="mine" :tab="t('我的可见本体')">
            <n-spin :show="loading">
              <n-empty v-if="!mine.count" :description="t('当前账号暂无可见本体')" />
              <div v-else class="tag-row">
                <n-tag v-for="item in mine.ontologies" :key="item" type="info" :bordered="false">{{ item }}</n-tag>
              </div>
              <p class="muted hint">
                {{ t('展示口径：租户兜底授权 + 当前账号自身授权（授权管理在「用户管理」中按用户配置）。') }}
              </p>
            </n-spin>
          </n-tab-pane>
          <n-tab-pane name="all" :tab="t('全量清单')">
            <div class="table-card">
              <n-data-table :columns="catalogColumns" :data="catalog" :loading="loading" :bordered="false" />
            </div>
          </n-tab-pane>
        </n-tabs>
      </div>
    </n-card>
  </div>
</template>

<style scoped>
.ontology-page { min-height: 100%; }
.ontology-content { display: grid; gap: 16px; min-width: 0; }
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.table-card { overflow: hidden; border: 1px solid #edf0f5; border-radius: 10px; }
.tag-row { display: flex; flex-wrap: wrap; gap: 6px; }
.muted { color: #667085; font-weight: 400; }
.hint { margin: 12px 0 0; font-size: 12px; }
@media (max-width: 860px) {
  .page-head { align-items: flex-start; flex-direction: column; }
}
</style>
