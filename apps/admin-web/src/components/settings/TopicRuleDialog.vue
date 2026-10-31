<script setup lang="ts">
import { computed, type Component } from 'vue'
import { t } from '@/composables/i18n'
import type { TopicRule } from '@/api/topic-admission'
import TopicRuleEditor from './TopicRuleEditor.vue'

const props = defineProps<{
  rule: TopicRule | null
  isNew: boolean
  audienceEditor?: Component
  audienceBadge?: Component
  audienceValue?: unknown
  audienceLoading: boolean
}>()
const emit = defineEmits<{
  (event: 'update:rule', rule: TopicRule): void
  (event: 'update:audience', ruleId: string, value: unknown): void
  (event: 'remove', rule: TopicRule): void
  (event: 'cancel'): void
  (event: 'done'): void
}>()
const title = computed(() => props.isNew
  ? t('taskAdmission.addRule')
  : t('taskAdmission.editRule', { name: props.rule?.name?.trim() || props.rule?.terms[0]?.keyword?.trim() || t('taskAdmission.newRule') }))

</script>

<template>
  <n-modal :show="Boolean(rule)" preset="card" :title="title" :style="{ width: 'min(860px, calc(100vw - 32px))' }"
    :mask-closable="false" :close-on-esc="false" :auto-focus="false"
    @update:show="(show: boolean) => { if (!show) emit('cancel') }">
    <div v-if="rule" class="rule-dialog-content">
      <TopicRuleEditor :key="rule.id" :model-value="rule" :can-edit-audience="Boolean(audienceEditor)"
        @update:model-value="emit('update:rule', $event)">
        <template #audience>
          <div class="topic-audience-toolbar">
            <component :is="audienceBadge" v-if="audienceBadge" />
            <n-tag v-else type="warning" size="small">{{ t('taskAdmission.enterprise') }}</n-tag>
            <span>{{ t('taskAdmission.ruleAudience') }}</span>
          </div>
          <n-spin :show="audienceLoading">
            <component :is="audienceEditor" v-if="audienceEditor && audienceValue !== undefined"
              :model-value="audienceValue" @update:model-value="emit('update:audience', rule.id, $event)" />
          </n-spin>
        </template>
      </TopicRuleEditor>
    </div>
    <template #footer>
      <div class="rule-dialog-footer">
        <n-button v-if="rule" tertiary type="error" @click="emit('remove', rule)">{{ t('taskAdmission.delete') }}</n-button>
        <span class="rule-dialog-hint">{{ t('taskAdmission.doneHint') }}</span>
        <n-button type="primary" @click="emit('done')">{{ t('taskAdmission.done') }}</n-button>
      </div>
    </template>
  </n-modal>
</template>

<style scoped>
.rule-dialog-content { max-height: calc(100vh - 170px); overflow-y: auto; padding-right: 4px; scrollbar-gutter: stable; scrollbar-width: thin; scrollbar-color: #becbdb transparent; }
.rule-dialog-footer { display: flex; align-items: center; gap: 12px; }
.rule-dialog-hint { flex: 1; color: #8b97a8; font-size: 12px; text-align: right; }
.topic-audience-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; color: #475467; font-size: 13px; }
@media (max-width: 620px) { .rule-dialog-footer { flex-wrap: wrap; }.rule-dialog-hint { order: 3; flex-basis: 100%; text-align: left; } }
</style>
