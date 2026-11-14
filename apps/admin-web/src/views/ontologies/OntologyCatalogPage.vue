<script setup lang="ts">
import { t } from '@/composables/i18n';
import { computed, h, onMounted, ref } from 'vue';
import { NAlert, NButton, NTag, useDialog, useMessage, type DataTableColumns } from 'naive-ui';
import PageIntro from '@/components/PageIntro.vue';
import {
  fetchOntologyCatalog,
  fetchOntologyPermissionConfig,
  fetchUserOntologyGrantSummaries,
  syncOntologies,
  updateOntologyPermissionConfig,
  type OntologyCatalogItem,
  type OntologyGrant,
  type OntologyPermissionConfig,
  type UserOntologyGrantSummary,
} from '@/api/ontologies';
import { fetchUsers, type DirectoryUserItem } from '@/api/directory';

const message = useMessage();
const dialog = useDialog();
const loading = ref(false);
const syncing = ref(false);
const toggling = ref(false);
/** 默认落在「本体清单」：全量清单迁移后以展示本体为主（030）。 */
const tab = ref<'catalog' | 'users'>('catalog');
const catalog = ref<OntologyCatalogItem[]>([]);
const config = ref<OntologyPermissionConfig | null>(null);
const userSummaries = ref<UserOntologyGrantSummary[]>([]);
const userNameById = ref<Record<string, string>>({});

const enforcing = computed(() => Boolean(config.value?.enforce));

const modeTagType = (mode: OntologyGrant['accessMode']) =>
  mode === 'none' ? 'default' : mode === 'write' ? 'warning' : 'success';

const userDisplayName = (userId: string) =>
  userNameById.value[userId] || userId || t('未知用户');

async function load() {
  loading.value = true;
  try {
    const [rows, cfg, summaries, users] = await Promise.all([
      fetchOntologyCatalog(),
      fetchOntologyPermissionConfig(),
      fetchUserOntologyGrantSummaries(),
      fetchUsers({}).catch(() => [] as DirectoryUserItem[]),
    ]);
    catalog.value = rows;
    config.value = cfg;
    userSummaries.value = summaries;
    userNameById.value = Object.fromEntries(users.map(user => [user.id, user.name || user.loginName || user.id]));
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

const userSummaryColumns: DataTableColumns<UserOntologyGrantSummary> = [
  {
    title: t('用户'),
    key: 'userId',
    render: row => h('strong', userDisplayName(row.userId)),
  },
  {
    title: t('已授予本体'),
    key: 'grants',
    render: row =>
      row.grants.length
        ? h(
            'div',
            { class: 'tag-row' },
            row.grants.map(grant =>
              h(
                NTag,
                {
                  key: grant.ontologyId,
                  size: 'small',
                  bordered: false,
                  type: grant.visible ? modeTagType(grant.accessMode) : 'default',
                },
                { default: () => `${grant.ontologyId} · ${grant.accessMode}` },
              ),
            ),
          )
        : h('span', { class: 'muted' }, t('仅继承租户兜底')),
  },
  { title: t('授权条数'), key: 'grantCount', width: 110 },
  {
    title: t('其中可见'),
    key: 'visibleCount',
    width: 110,
  },
  {
    title: t('已停用'),
    key: 'disabledCount',
    width: 110,
    render: row =>
      row.disabledCount
        ? h(NTag, { size: 'small', type: 'warning', bordered: false }, { default: () => row.disabledCount })
        : h('span', { class: 'muted' }, '—'),
  },
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
          <n-tab-pane name="catalog" :tab="t('本体清单')">
            <div class="table-card">
              <n-data-table :columns="catalogColumns" :data="catalog" :loading="loading" :bordered="false" />
            </div>
            <p class="muted hint">
              {{ t('清单聚合自 MOGO 侧业务实体索引的 ontology_id，并补上已授权但索引未出现的本体；本体 CRUD 不在 MOGO 侧。') }}
            </p>
          </n-tab-pane>
          <n-tab-pane name="users" :tab="t('用户本体授权')">
            <n-alert type="info" :bordered="false">
              {{ t('按用户汇总 subject_type=user 的本体授权；租户兜底授权不归属任何用户。同一本体按优先级高者胜、同优先级取更严格模式。单个用户的授予与撤销在「用户管理」的用户行操作。') }}
            </n-alert>
            <div class="table-card">
              <n-data-table
                :columns="userSummaryColumns"
                :data="userSummaries"
                :loading="loading"
                :bordered="false"
              />
            </div>
          </n-tab-pane>
        </n-tabs>
      </div>
    </n-card>
  </div>
</template>

<style scoped>
.ontology-page { height: 100%; min-height: 0; display: flex; flex-direction: column; }
.ontology-content { display: grid; gap: 16px; min-width: 0; }
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.table-card { overflow: hidden; border: 1px solid var(--mg-border); border-radius: 10px; }
.tag-row { display: flex; flex-wrap: wrap; gap: 6px; }
.muted { color: var(--mg-text-2); font-weight: 400; }
.hint { margin: 12px 0 0; font-size: 12px; }
@media (max-width: 860px) {
  .page-head { align-items: flex-start; flex-direction: column; }
}
</style>
