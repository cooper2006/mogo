<script setup lang="ts">
/**
 * 017 T027 — admin 可见范围 / 策略 / 配额配置（参考 ResourceAccessExtensionPanel.vue）。
 *  · 可见范围：部门 / 岗位角色 / 指定员工 + 「含下级」开关（§7.2）
 *  · 策略：衰减周期、清理方式、摘要刷新窗口、L2 硬上限、归档项目是否可检索（§9.5）
 *  · 配额：每用户 / 每项目 / 每部门（§9.5 / 042 三层配额引擎，默认值待定）
 * 端点 §9.1 GET/PUT /api/v1/memories/admin/policies 为 TODO 待后端提供；
 * 404 时保留默认表单并给出中性提示，不泄露内容（T030）。
 */
import { onMounted, ref } from 'vue';
import { t } from '@/composables/i18n';
import { useMessage } from 'naive-ui';
import {
  type MemoryPolicies,
  defaultMemoryPolicies,
  fetchMemoryPolicies,
  updateMemoryPolicies,
  memoryErrorText,
  normalizeMemoryError,
} from '@/api/memories';

const message = useMessage();
const model = ref<MemoryPolicies>(defaultMemoryPolicies());
const loading = ref(false);
const saving = ref(false);
const loadHint = ref('');

const cleanupOptions = [
  { label: t('归档 (archive)'), value: 'archive' },
  { label: t('删除 (delete)'), value: 'delete' },
];

async function load() {
  loading.value = true;
  loadHint.value = '';
  try {
    const data = await fetchMemoryPolicies();
    if (data) model.value = { ...defaultMemoryPolicies(), ...data };
  } catch (error: any) {
    // TODO(backend): policies 端点待后端提供；404 不泄露内容，仅提示待配置。
    const e = normalizeMemoryError(error);
    loadHint.value = e.notFound
      ? t('策略端点待后端提供，当前展示默认值（可离线编辑，暂不落库）。')
      : memoryErrorText(error, t('策略加载失败'));
  } finally { loading.value = false; }
}
onMounted(load);

async function save() {
  saving.value = true;
  try {
    await updateMemoryPolicies(model.value);
    message.success(t('配置已保存'));
    loadHint.value = '';
  } catch (error: any) {
    // TODO(backend): 同 load，端点待后端提供。
    message.error(memoryErrorText(error, t('保存失败')));
  } finally { saving.value = false; }
}
</script>

<template>
  <div class="governance">
    <n-alert v-if="loadHint" type="info" :bordered="false" class="hint">{{ loadHint }}</n-alert>
    <n-spin :show="loading">
      <div class="grid">
        <!-- 可见范围：部门 / 岗位 / 指定员工 + 含下级开关 -->
        <n-card :title="t('可见范围配置')" size="small" :bordered="true">
          <div class="field">
            <label class="field-label">{{ t('部门') }}</label>
            <n-select v-model:value="model.visibility.department_ids" multiple filterable tag :options="[]" :placeholder="t('输入部门 ID 后回车添加')" />
          </div>
          <div class="field">
            <label class="field-label">{{ t('岗位角色') }}</label>
            <n-select v-model:value="model.visibility.position_role_ids" multiple filterable tag :options="[]" :placeholder="t('输入岗位角色后回车添加')" />
          </div>
          <div class="field">
            <label class="field-label">{{ t('指定员工') }}</label>
            <n-select v-model:value="model.visibility.employee_user_ids" multiple filterable tag :options="[]" :placeholder="t('输入员工 ID 后回车添加')" />
          </div>
          <div class="switch-row">
            <span>{{ t('含下级部门 / 岗位') }}</span>
            <n-switch v-model:value="model.visibility.include_descendants" />
          </div>
        </n-card>

        <!-- 策略配置（§9.5） -->
        <n-card :title="t('策略配置')" size="small" :bordered="true">
          <div class="field">
            <label class="field-label">{{ t('衰减周期（天）') }}</label>
            <n-input-number v-model:value="model.decay_days" :min="1" />
          </div>
          <div class="field">
            <label class="field-label">{{ t('清理方式') }}</label>
            <n-select v-model:value="model.cleanup_policy" :options="cleanupOptions" />
          </div>
          <div class="field">
            <label class="field-label">{{ t('摘要刷新窗口（天）') }}</label>
            <n-input-number v-model:value="model.summary_refresh_days" :min="1" />
          </div>
          <div class="field">
            <label class="field-label">{{ t('L2 硬上限（字节）') }}</label>
            <n-input-number v-model:value="model.l2_hard_max_bytes" :min="0" />
          </div>
          <div class="switch-row">
            <span>{{ t('归档项目仍可检索') }}</span>
            <n-switch v-model:value="model.archived_project_retrievable" />
          </div>
        </n-card>

        <!-- 配额（每用户 / 每项目 / 每部门，§9.5 待定） -->
        <n-card :title="t('配额')" size="small" :bordered="true">
          <div class="field">
            <label class="field-label">{{ t('每用户记忆条数上限') }}</label>
            <n-input-number v-model:value="model.quota.per_user" :min="0" />
          </div>
          <div class="field">
            <label class="field-label">{{ t('每项目记忆条数上限') }}</label>
            <n-input-number v-model:value="model.quota.per_project" :min="0" />
          </div>
          <div class="field">
            <label class="field-label">{{ t('每部门记忆条数上限') }}</label>
            <n-input-number v-model:value="model.quota.per_department" :min="0" />
          </div>
          <p class="quota-note">{{ t('0 表示沿用 042 三层配额引擎默认；具体上限值待后端 §9.5 确认。') }}</p>
        </n-card>
      </div>

      <n-space justify="end" class="actions">
        <n-button @click="load">{{ t('重置') }}</n-button>
        <n-button type="primary" :loading="saving" @click="save">{{ t('保存配置') }}</n-button>
      </n-space>
    </n-spin>
  </div>
</template>

<style scoped>
.governance { display: grid; gap: 14px; }
.hint { margin-bottom: 4px; }
.grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.field { margin-bottom: 12px; }
.field-label { display: block; margin-bottom: 6px; font-size: 13px; color: var(--mg-text-2); }
.switch-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 6px 0; color: var(--mg-text-1); font-size: 13px; }
.quota-note { margin: 8px 0 0; color: var(--mg-text-2); font-size: 12px; }
.actions { margin-top: 4px; }
@media (max-width: 1100px) { .grid { grid-template-columns: 1fr; } }
</style>
