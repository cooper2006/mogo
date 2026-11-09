<template>
  <button
    v-if="failed && retryable"
    type="button"
    class="status-pill status-failed status-retry"
    :title="t('knowledge.click_relearn')"
    :aria-label="`${label}, ${t('knowledge.click_relearn')}`"
    @click.stop="emit('retry')"
  >
    <RefreshOutline aria-hidden="true" />
    <span>{{ label }}</span>
  </button>
  <span v-else class="status-pill" :class="statusClass" role="status">
    <span v-if="processing" class="learning-spinner" aria-hidden="true" />
    <span>{{ label }}</span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import RefreshOutline from '@vicons/ionicons5/es/RefreshOutline'
import { t } from '../../composables/i18n'
import { isKnowledgeProcessingStatus, knowledgeStatusText } from './knowledgeStatus'

const props = defineProps<{ status: string; revoked?: boolean; deleted?: boolean; retryable?: boolean }>()
const emit = defineEmits<{ retry: [] }>()

const failed = computed(() => !props.revoked && !props.deleted && props.status === 'failed')
const processing = computed(() => !props.revoked && !props.deleted && isKnowledgeProcessingStatus(props.status))
const label = computed(() => props.deleted ? t('knowledge.status_deleted') : knowledgeStatusText(props.status, props.revoked))
const statusClass = computed(() => ({
  'status-success': !props.revoked && props.status === 'indexed',
  'status-failed': failed.value,
  'status-learning': processing.value,
  'status-revoked': props.revoked,
  'status-deleted': props.deleted,
}))
</script>

<style scoped>
.status-pill{display:inline-flex;min-height:26px;box-sizing:border-box;align-items:center;justify-content:center;gap:6px;padding:3px 9px;border: 1px solid transparent;border-radius: 999px;font:inherit;font-size:12px;line-height:18px;white-space:nowrap}.status-success{border-color: var(--mg-success-border);background: var(--mg-success-bg);color:var(--mg-success-text)}.status-learning{border-color: var(--mg-brand-soft-border);background: var(--mg-info-bg);color:var(--mg-brand-text)}.status-failed{border-color: var(--mg-danger-border);background: var(--mg-danger-bg);color:var(--mg-danger-text)}.status-revoked,.status-deleted{border-color: var(--mg-neutral-border);background: var(--mg-neutral-bg);color:var(--mg-text-3)}.status-retry{cursor:pointer;transition:background-color .15s ease,border-color .15s ease,box-shadow .15s ease}.status-retry:hover{border-color: var(--mg-danger-text);background: var(--mg-danger-bg);box-shadow:0 2px 8px rgba(217,45,58,.14)}.status-retry:focus-visible{outline:2px solid rgba(217,45,58,.3);outline-offset:2px}.status-retry svg{width:14px;height:14px}.learning-spinner{width:12px;height:12px;box-sizing:border-box;border: 2px solid rgba(36,89,211,.22);border-top-color: currentColor;border-radius: 50%;animation:knowledge-spin .8s linear infinite}@keyframes knowledge-spin{to{transform:rotate(360deg)}}@media (prefers-reduced-motion:reduce){.learning-spinner{animation-duration:1.8s}}
</style>
