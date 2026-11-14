<script setup lang="ts">
/**
 * 017 T026 — admin 记忆详情抽屉（参考 AuditDetailDrawer.vue 范式）。
 * 内容分层 L0/L1/L2 全文、provenance、project_id + project_owner_id 消歧回显项目名，
 * 查不到显示「已归档 / 已删除」。不可见一律 404，详情补全失败静默回退，不泄露内容（T030）。
 */
import { computed, ref, watch } from 'vue';
import { t } from '@/composables/i18n';
import { formatAdminDateTime } from '@/composables/adminTimezone';
import {
  type MemoryItem,
  type MemoryProjectView,
  fetchAdminMemory,
  resolveProjectName,
  normalizeMemoryError,
} from '@/api/memories';

const props = defineProps<{ show: boolean; record: MemoryItem | null; projects: MemoryProjectView[] }>();
const emit = defineEmits<{ 'update:show': [value: boolean] }>();

const full = ref<MemoryItem | null>(null);
const loadError = ref('');

watch(() => [props.show, props.record?.memory_id] as const, async ([show, id]) => {
  full.value = null;
  loadError.value = '';
  if (!show || !id) return;
  try {
    // TODO(backend): GET /api/v1/memories/admin/{id} 为 §9.1 治理端点，待后端提供；
    // 未提供（404）时静默回退到列表行字段，不泄露内容。
    full.value = await fetchAdminMemory(id);
  } catch (error: any) {
    const e = normalizeMemoryError(error);
    loadError.value = e.notFound ? t('详情暂不可用（内容不存在或无权查看）') : t('详情暂不可用');
  }
}, { immediate: true });

const detail = computed<MemoryItem | null>(() => full.value || props.record);
const projectName = computed(() => detail.value
  ? resolveProjectName(props.projects, detail.value.project_id, detail.value.project_owner_id)
  : '');
const provenanceRows = computed(() => Object.entries(detail.value?.provenance || {}).filter(([, v]) => v !== '' && v != null));
</script>

<template>
  <n-drawer :show="show" :width="600" placement="right" @update:show="emit('update:show', $event)">
    <n-drawer-content :title="t('记忆详情')" closable>
      <template v-if="detail">
        <n-alert v-if="loadError" type="warning" :bordered="false" class="detail-alert">{{ loadError }}</n-alert>

        <n-descriptions :column="1" label-placement="left" bordered size="small">
          <n-descriptions-item :label="t('记忆 ID')">{{ detail.memory_id }}</n-descriptions-item>
          <n-descriptions-item :label="t('范围')">
            <n-tag size="small" :bordered="false" :type="detail.scope === 'department' ? 'warning' : detail.scope === 'project' ? 'info' : 'default'">
              {{ ({ personal: t('个人'), project: t('项目'), department: t('部门') } as Record<string, string>)[detail.scope] || detail.scope }}
            </n-tag>
          </n-descriptions-item>
          <n-descriptions-item :label="t('实际范围')">{{ detail.actual_scope || detail.scope }}</n-descriptions-item>
          <n-descriptions-item :label="t('解析来源')">{{ detail.resolved_from || '-' }}</n-descriptions-item>
          <n-descriptions-item :label="t('归属人')">{{ detail.owner_id || '-' }}</n-descriptions-item>
          <n-descriptions-item :label="t('项目')">
            {{ projectName || '-' }}
            <span v-if="detail.project_id" class="subtle">（{{ detail.project_id }}<template v-if="detail.project_owner_id"> · owner {{ detail.project_owner_id }}</template>）</span>
          </n-descriptions-item>
          <n-descriptions-item :label="t('部门')">{{ detail.department_id || '-' }}</n-descriptions-item>
          <n-descriptions-item :label="t('地址')">{{ detail.addr || '-' }}</n-descriptions-item>
          <n-descriptions-item :label="t('创建时间')">{{ formatAdminDateTime(detail.created_at, '-') }}</n-descriptions-item>
          <n-descriptions-item :label="t('最近命中')">{{ formatAdminDateTime(detail.last_accessed_at, '-') }}</n-descriptions-item>
        </n-descriptions>

        <div class="section-title">{{ t('内容分层') }}</div>
        <div class="tier-block">
          <div class="tier-label">L0 · {{ t('摘要') }}</div>
          <div class="tier-value">{{ detail.l0_summary || t('（暂无 L0 摘要）') }}</div>
        </div>
        <div class="tier-block">
          <div class="tier-label">L1 · {{ t('概览') }}</div>
          <div class="tier-value">{{ detail.l1_overview || t('（暂无 L1 概览）') }}</div>
        </div>
        <div class="tier-block">
          <div class="tier-label">L2 · {{ t('原始全文') }}</div>
          <div class="tier-value">{{ detail.l2_raw || detail.content || t('（暂无 L2 全文）') }}</div>
        </div>

        <div class="section-title">{{ t('Provenance（来源链路）') }}</div>
        <n-descriptions :column="1" label-placement="left" bordered size="small">
          <n-descriptions-item :label="t('来源类型')">{{ detail.source_type || t('手动') }}</n-descriptions-item>
          <n-descriptions-item :label="t('来源会话')">{{ detail.source_session_id || '-' }}</n-descriptions-item>
          <n-descriptions-item v-for="([key, value]) in provenanceRows" :key="key" :label="key">
            {{ typeof value === 'object' ? JSON.stringify(value) : value }}
          </n-descriptions-item>
        </n-descriptions>

        <div class="section-title">{{ t('命中轨迹 / 审计记录') }}</div>
        <div class="tier-block">
          <div class="tier-label">{{ t('检索命中轨迹') }}</div>
          <pre class="json-value">{{ detail.retrieval_trace?.length ? JSON.stringify(detail.retrieval_trace, null, 2) : t('（暂无）') }}</pre>
        </div>
        <div class="tier-block">
          <div class="tier-label">{{ t('审计记录（memory.* / project.member.*）') }}</div>
          <pre class="json-value">{{ detail.audit?.length ? JSON.stringify(detail.audit, null, 2) : t('（暂无）') }}</pre>
        </div>
      </template>
      <n-empty v-else :description="t('未选择记忆')" />
    </n-drawer-content>
  </n-drawer>
</template>

<style scoped>
.detail-alert { margin-bottom: 14px; }
.section-title { margin: 18px 0 10px; font-weight: 650; color: var(--mg-text-1); }
.tier-block { margin-bottom: 12px; padding: 12px 14px; border: 1px solid var(--mg-border); border-radius: 8px; background: var(--mg-bg-surface); }
.tier-label { margin-bottom: 6px; font-size: 12px; font-weight: 650; color: var(--mg-text-2); }
.tier-value { color: var(--mg-text-1); white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.6; }
.subtle { color: var(--mg-text-2); font-size: 12px; }
.json-value { margin: 0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--mg-text-2); white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
