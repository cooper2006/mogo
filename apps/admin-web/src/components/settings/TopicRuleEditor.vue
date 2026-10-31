<script setup lang="ts">
import { computed, ref } from 'vue'
import { t } from '@/composables/i18n'
import type { TopicRule } from '@/api/topic-admission'

const props = defineProps<{ modelValue: TopicRule; canEditAudience: boolean }>()
const emit = defineEmits<{
  (event: 'update:modelValue', value: TopicRule): void
}>()

const rule = computed(() => props.modelValue)
const synonymDrafts = ref<string[]>(props.modelValue.terms.map(term => term.synonyms.join('，')))

function update(patch: Partial<TopicRule>) {
  emit('update:modelValue', { ...rule.value, ...patch })
}

function updateTerm(index: number, patch: { keyword?: string; synonyms?: string[] }) {
  const terms = rule.value.terms.map((item, termIndex) => termIndex === index ? { ...item, ...patch } : item)
  update({ terms })
}

function addTerm() {
  if (rule.value.terms.length >= 30) return
  synonymDrafts.value.push('')
  update({ terms: [...rule.value.terms, { keyword: '', synonyms: [] }] })
}

function removeTerm(index: number) {
  synonymDrafts.value.splice(index, 1)
  update({ terms: rule.value.terms.filter((_, termIndex) => termIndex !== index) })
}

function updateSynonyms(index: number, value: string) {
  synonymDrafts.value[index] = value
  updateTerm(index, { synonyms: value.split(/[,，]/).map(part => part.trim()).filter(Boolean) })
}
</script>

<template>
  <section class="topic-rule">
    <n-form label-placement="top" class="topic-rule-body">
      <div class="topic-rule-top">
        <n-form-item :label="t('taskAdmission.ruleName')"><n-input :value="rule.name || ''" :placeholder="t('taskAdmission.ruleNamePlaceholder')" maxlength="80" clearable @update:value="update({ name: $event })" /></n-form-item>
        <div class="topic-rule-status">
          <span>{{ t('taskAdmission.ruleStatus') }}</span>
          <div><small>{{ t(rule.enabled ? 'taskAdmission.enabled' : 'taskAdmission.disabled') }}</small><n-switch :value="rule.enabled" :aria-label="t('taskAdmission.ruleStatus')" @update:value="update({ enabled: $event })" /></div>
        </div>
      </div>
      <div class="topic-term-heading"><span>{{ t('taskAdmission.keyword') }}</span><span>{{ t('taskAdmission.synonyms') }}</span></div>
      <div v-for="(term, index) in rule.terms" :key="index" class="topic-term-row">
        <n-input :value="term.keyword" :placeholder="t('taskAdmission.keywordExample')" maxlength="80" @update:value="updateTerm(index, { keyword: $event })" />
        <n-input :value="synonymDrafts[index] ?? term.synonyms.join('，')" :placeholder="t('taskAdmission.synonymsExample')" @update:value="updateSynonyms(index, $event)" />
        <n-button quaternary :disabled="rule.terms.length <= 1" @click="removeTerm(index)">−</n-button>
      </div>
      <n-button text type="primary" :disabled="rule.terms.length >= 30" @click="addTerm">+ {{ t('taskAdmission.addKeyword') }}</n-button>
    </n-form>
    <div v-if="canEditAudience" class="topic-audience"><slot name="audience" /></div>
  </section>
</template>

<style scoped>
.topic-rule { display: grid; gap: 18px; }
.topic-rule-body { display: grid; gap: 12px; }
.topic-rule-top { display: grid; grid-template-columns: minmax(0, 1fr) 158px; gap: 16px; align-items: start; }
.topic-rule-status { display: grid; gap: 8px; color: #667085; font-size: 12px; }
.topic-rule-status > div { display: flex; align-items: center; justify-content: space-between; min-height: 32px; padding: 0 10px; border: 1px solid #dce4ef; border-radius: 6px; }
.topic-rule-status small { color: #344054; font-size: 12px; }
.topic-rule-body :deep(.n-form-item) { margin-bottom: 0; }
.topic-term-heading, .topic-term-row { display: grid; grid-template-columns: minmax(120px, 1fr) minmax(180px, 2fr) 32px; gap: 10px; align-items: center; }
.topic-term-heading { color: #667085; font-size: 12px; }
.topic-audience { display: grid; gap: 12px; padding-top: 16px; border-top: 1px solid #edf1f6; }
@media (max-width: 680px) { .topic-rule-top { grid-template-columns: 1fr; }.topic-term-heading { display: none; } .topic-term-row { grid-template-columns: 1fr 1fr 32px; } }
</style>
