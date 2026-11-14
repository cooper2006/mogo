<template>
  <!-- 017 T029：user 记忆详情弹窗。只读展示列表行字段（user 端无独立详情端点，
       不额外 fetch，避免编造路径）；project_id + project_owner_id 消歧回显项目名，
       查不到显示「已归档 / 已删除」。不含项目成员编辑（归 049 MemberPicker）。 -->
  <n-modal :show="show" preset="card" :title="t('记忆详情')" style="width: 560px" :bordered="false" @update:show="emit('update:show', $event)">
    <template v-if="record">
      <n-descriptions :column="1" label-placement="left" bordered size="small">
        <n-descriptions-item :label="t('范围')">
          <n-tag size="small" :bordered="false" :type="record.scope === 'department' ? 'warning' : record.scope === 'project' ? 'info' : 'default'">
            {{ ({ personal: t('个人'), project: t('项目'), department: t('部门') } as Record<string, string>)[record.scope] || record.scope }}
          </n-tag>
        </n-descriptions-item>
        <n-descriptions-item :label="t('实际范围')">{{ record.actual_scope || record.scope }}</n-descriptions-item>
        <n-descriptions-item :label="t('解析来源')">{{ record.resolved_from || '-' }}</n-descriptions-item>
        <n-descriptions-item :label="t('项目')">
          {{ projectName || '-' }}
          <span v-if="record.project_id" class="subtle">（{{ record.project_id }}<template v-if="record.project_owner_id"> · owner {{ record.project_owner_id }}</template>）</span>
        </n-descriptions-item>
        <n-descriptions-item :label="t('部门')">{{ record.department_id || '-' }}</n-descriptions-item>
        <n-descriptions-item :label="t('地址')">{{ record.addr || '-' }}</n-descriptions-item>
        <n-descriptions-item :label="t('来源类型')">{{ record.source_type || (record.source_session_id ? t('会话沉淀') : t('手动')) }}</n-descriptions-item>
        <n-descriptions-item :label="t('来源会话')">{{ record.source_session_id || '-' }}</n-descriptions-item>
      </n-descriptions>

      <div class="section-title">{{ t('内容分层') }}</div>
      <div class="tier-block">
        <div class="tier-label">L0 · {{ t('摘要') }}</div>
        <div class="tier-value">{{ record.l0_summary || t('（暂无 L0 摘要）') }}</div>
      </div>
      <div class="tier-block">
        <div class="tier-label">L1 · {{ t('概览') }}</div>
        <div class="tier-value">{{ record.l1_overview || t('（暂无 L1 概览）') }}</div>
      </div>
      <div class="tier-block">
        <div class="tier-label">L2 · {{ t('原始全文') }}</div>
        <div class="tier-value">{{ record.l2_raw || record.content || t('（暂无 L2 全文）') }}</div>
      </div>

      <div class="section-title">{{ t('Provenance') }}</div>
      <pre class="json-value">{{ record.provenance && Object.keys(record.provenance).length ? JSON.stringify(record.provenance, null, 2) : t('（暂无）') }}</pre>
      <n-alert v-if="record.project_id" type="info" :bordered="false" class="hint">
        {{ t('该项目成员由「成员」入口管理（049），此处仅只读展示。') }}
      </n-alert>
    </template>
    <n-empty v-else :description="t('未选择记忆')" />
  </n-modal>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NAlert, NDescriptions, NDescriptionsItem, NEmpty, NModal, NTag } from 'naive-ui'
import { t } from '../composables/i18n'
import { resolveProjectName, type MemoryItem, type MemoryProjectView } from '../api/memories'

const props = defineProps<{ show: boolean; record: MemoryItem | null; projects: MemoryProjectView[] }>()
const emit = defineEmits<{ 'update:show': [value: boolean] }>()

const projectName = computed(() => props.record
  ? resolveProjectName(props.projects, props.record.project_id, props.record.project_owner_id)
  : '')
</script>

<style scoped>
.section-title { margin: 16px 0 8px; font-weight: 650; color: var(--mg-text-1); }
.tier-block { margin-bottom: 10px; padding: 10px 12px; border: 1px solid var(--mg-border); border-radius: 8px; background: var(--mg-bg-surface); }
.tier-label { margin-bottom: 6px; font-size: 12px; font-weight: 650; color: var(--mg-text-2); }
.tier-value { color: var(--mg-text-1); white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.6; }
.subtle { color: var(--mg-text-2); font-size: 12px; }
.json-value { margin: 0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--mg-text-2); white-space: pre-wrap; overflow-wrap: anywhere; }
.hint { margin-top: 14px; }
</style>
