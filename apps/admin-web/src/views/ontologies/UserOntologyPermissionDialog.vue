<script setup lang="ts">
import { t } from '@/composables/i18n';
import { computed, ref, watch } from 'vue';
import { NAlert, NTag, useMessage } from 'naive-ui';
import {
  fetchOntologyCatalog,
  fetchUserOntologyPermissions,
  grantUserOntologyPermissions,
  revokeUserOntologyPermission,
  type OntologyCatalogItem,
  type OntologyGrant,
} from '@/api/ontologies';
import { formatAdminDateTime } from '@/composables/adminTimezone';

const props = defineProps<{ show: boolean; userId: string; userName: string }>();
const emit = defineEmits<{ (event: 'update:show', value: boolean): void }>();
const message = useMessage();
const loading = ref(false);
const saving = ref(false);
const grants = ref<OntologyGrant[]>([]);
const catalog = ref<OntologyCatalogItem[]>([]);
const ontologyIds = ref<string[]>([]);
const accessMode = ref<'read' | 'write' | 'none'>('read');
const priority = ref(100);
const remark = ref('');

const grantedIds = computed(() => new Set(grants.value.map(row => row.ontologyId)));
const options = computed(() =>
  catalog.value
    .filter(item => !grantedIds.value.has(item.ontologyId))
    .map(item => ({
      label: item.entityTypes.length ? `${item.ontologyId} · ${item.entityTypes.join('/')}` : item.ontologyId,
      value: item.ontologyId,
    })),
);
const accessModeOptions = [
  { label: t('可读（read）'), value: 'read' },
  { label: t('可写（write）'), value: 'write' },
  { label: t('不可见（none）'), value: 'none' },
];

function resetDraft() {
  ontologyIds.value = [];
  accessMode.value = 'read';
  priority.value = 100;
  remark.value = '';
}

async function load() {
  if (!props.userId) return;
  loading.value = true;
  try {
    const [bundle, rows] = await Promise.all([
      fetchUserOntologyPermissions(props.userId),
      fetchOntologyCatalog(),
    ]);
    grants.value = bundle.grants;
    catalog.value = rows;
  } catch (error: any) {
    message.error(error?.response?.data?.detail || error?.message || t('本体权限加载失败'));
  } finally {
    loading.value = false;
  }
}

async function save() {
  if (!ontologyIds.value.length) return message.warning(t('请选择至少一个本体'));
  saving.value = true;
  try {
    await grantUserOntologyPermissions(props.userId, {
      ontologyIds: ontologyIds.value,
      accessMode: accessMode.value,
      priority: priority.value,
      remark: remark.value.trim(),
    });
    message.success(t('本体数据权限已保存'));
    resetDraft();
    await load();
  } catch (error: any) {
    message.error(error?.response?.data?.detail || error?.message || t('授权失败'));
  } finally {
    saving.value = false;
  }
}

async function revoke(row: OntologyGrant) {
  try {
    await revokeUserOntologyPermission(props.userId, row.ontologyId);
    message.success(t('已撤销 {name} 的本体权限', { name: row.ontologyId }));
    await load();
  } catch (error: any) {
    message.error(error?.response?.data?.detail || error?.message || t('撤销失败'));
  }
}

watch(() => props.show, visible => {
  if (visible) void load();
});
</script>

<template>
  <n-modal
    :show="show"
    preset="card"
    :title="t('{name} · 本体数据权限', { name: userName })"
    style="width: 760px"
    @update:show="(value: boolean) => emit('update:show', value)"
  >
    <n-spin :show="loading">
      <n-alert type="info" :bordered="false">
        {{ t('本体数据权限为数据范围层（看到哪些本体），与岗位角色的功能权限正交；本页为纯用户级、长期有效。') }}
      </n-alert>
      <n-form label-placement="top" class="grant-form">
        <n-grid :cols="2" :x-gap="14">
          <n-grid-item>
            <n-form-item :label="t('授予本体')" required>
              <n-select
                v-model:value="ontologyIds"
                multiple
                filterable
                max-tag-count="responsive"
                :options="options"
                :placeholder="t('选择要授予的本体')"
              />
            </n-form-item>
          </n-grid-item>
          <n-grid-item>
            <n-form-item :label="t('访问模式')">
              <n-select v-model:value="accessMode" :options="accessModeOptions" />
            </n-form-item>
          </n-grid-item>
        </n-grid>
        <n-grid :cols="2" :x-gap="14">
          <n-grid-item>
            <n-form-item :label="t('优先级')">
              <n-input-number v-model:value="priority" :min="0" :max="9999" style="width: 100%" />
            </n-form-item>
          </n-grid-item>
          <n-grid-item>
            <n-form-item :label="t('备注')">
              <n-input v-model:value="remark" maxlength="200" show-count />
            </n-form-item>
          </n-grid-item>
        </n-grid>
        <n-space justify="end">
          <n-button type="primary" :loading="saving" @click="save">{{ t('批量授予') }}</n-button>
        </n-space>
      </n-form>

      <n-divider>{{ t('已授予的本体') }}</n-divider>
      <n-empty v-if="!grants.length" :description="t('暂无本体授权')" />
      <div v-else class="grant-list">
        <div v-for="row in grants" :key="row.id" class="grant-row">
          <div>
            <strong>{{ row.ontologyId }}</strong>
            <small>
              {{ t('优先级 {priority}', { priority: row.priority }) }}
              <template v-if="row.remark"> · {{ row.remark }}</template>
              <template v-if="row.updatedAt"> · {{ formatAdminDateTime(row.updatedAt, '-') }}</template>
            </small>
          </div>
          <n-tag
            :type="row.accessMode === 'none' ? 'default' : row.accessMode === 'write' ? 'warning' : 'success'"
            :bordered="false"
          >
            {{ row.accessMode }}
          </n-tag>
          <n-button text type="error" @click="revoke(row)">{{ t('撤销') }}</n-button>
        </div>
      </div>
    </n-spin>
  </n-modal>
</template>

<style scoped>
.grant-form { margin-top: 18px; }
.grant-list { display: grid; gap: 8px; }
.grant-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--mg-border);
  border-radius: 10px;
}
.grant-row div { display: grid; gap: 4px; }
.grant-row small { color: var(--mg-text-2); }
</style>
