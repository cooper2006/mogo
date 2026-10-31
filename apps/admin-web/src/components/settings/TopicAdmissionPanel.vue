<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import axios from 'axios'
import { useMessage } from 'naive-ui'
import { t } from '@/composables/i18n'
import adminProductUiExtension from '@mogo-admin-product-extension'
import { fetchTopicRules, fetchTopicSummary, previewTopicChanges, saveTopicChanges, type TopicChanges, type TopicMode, type TopicRule, type TopicSummary, type TopicTestResult } from '@/api/topic-admission'
import TopicRuleDialog from './TopicRuleDialog.vue'
import TopicRuleList from './TopicRuleList.vue'
import TopicAdmissionModePicker from './TopicAdmissionModePicker.vue'
import { useTopicRuleAudiences } from './useTopicRuleAudiences'
import { createClientUuid } from '@/utils/clientUuid'

const message = useMessage()
const MAX_RULES = 200
const PAGE_SIZE = 10
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const loadingRules = ref(false)
const summary = ref<TopicSummary>({ mode: 'off', ruleCount: 0, enabledRuleCount: 0 })
const mode = ref<TopicMode>('off')
const serverRules = ref<TopicRule[]>([])
const serverTotal = ref(0)
const currentPage = ref(1)
const currentQuery = ref('')
const currentStatus = ref('all')
const originalRules = ref<Record<string, TopicRule>>({})
const upserts = ref<Record<string, TopicRule>>({})
const deletedIds = ref<string[]>([])
const newIds = ref<string[]>([])
const ruleListRef = ref<{ resetFilters: () => void } | null>(null)
let rulesRequest = 0
const savedMode = ref<TopicMode>('off')
const selectedRuleId = ref<string | null>(null)
const lastEnabledMode = ref<TopicMode>('denylist')
const sample = ref('')
const result = ref<TopicTestResult | null>(null)
const audienceExtension = adminProductUiExtension.topicRuleAudience
const audienceBadge = adminProductUiExtension.topicRuleAudienceBadge
const audiences = useTopicRuleAudiences(audienceExtension)
const savedAudienceSummaries = ref<Record<string, unknown>>({})
const audienceSummaryLoaded = ref(false)
const audienceSummaries = computed(() => {
  if (!audienceExtension?.summarize) return undefined
  const result: Record<string, { key: string; count?: number }> = {}
  for (const rule of visibleRules.value) {
    const draft = audiences.values.value[rule.id]
    const saved = savedAudienceSummaries.value[rule.id]
    if (draft === undefined && saved === undefined && !audienceSummaryLoaded.value && !newIds.value.includes(rule.id)) continue
    const value = draft ?? saved ?? audienceExtension.createValue()
    result[rule.id] = audienceExtension.summarize(value)
  }
  return result
})
const modeDirty = computed(() => mode.value !== savedMode.value)
const ruleCount = computed(() => summary.value.ruleCount + newIds.value.length - deletedIds.value.length)
const enabledRuleCount = computed(() => {
  let count = summary.value.enabledRuleCount
  for (const id of deletedIds.value) if (originalRules.value[id]?.enabled) count--
  for (const [id, rule] of Object.entries(upserts.value)) {
    if (newIds.value.includes(id)) count += Number(rule.enabled)
    else count += Number(rule.enabled) - Number(originalRules.value[id]?.enabled)
  }
  return count
})
const visibleRules = computed(() => {
  const saved = serverRules.value.filter(rule => !deletedIds.value.includes(rule.id)).map(rule => upserts.value[rule.id] || rule)
  const added = !currentQuery.value && currentStatus.value === 'all'
    ? newIds.value.slice((currentPage.value - 1) * PAGE_SIZE, currentPage.value * PAGE_SIZE)
      .map(id => upserts.value[id]).filter((rule): rule is TopicRule => Boolean(rule)) : []
  return [...added, ...saved]
})
const selectedRule = computed(() => {
  const id = selectedRuleId.value
  if (!id) return null
  return upserts.value[id] || serverRules.value.find(rule => rule.id === id) || originalRules.value[id] || null
})
const selectedAudienceValue = computed(() => selectedRuleId.value ? audiences.values.value[selectedRuleId.value] : undefined)
const selectedAudienceLoading = computed(() => Boolean(selectedRuleId.value && audiences.loading.value[selectedRuleId.value]))
const visibleTotal = computed(() => {
  if (!currentQuery.value && currentStatus.value === 'all') return ruleCount.value
  const needle = currentQuery.value.normalize('NFKC').toLocaleLowerCase()
  const deletedMatches = deletedIds.value.filter(id => {
    const rule = originalRules.value[id]
    if (!rule || (currentStatus.value === 'enabled' && !rule.enabled) || (currentStatus.value === 'disabled' && rule.enabled)) return false
    return (rule.name || '').normalize('NFKC').toLocaleLowerCase().includes(needle) || rule.terms.some(term => [term.keyword, ...term.synonyms]
      .some(value => value.normalize('NFKC').toLocaleLowerCase().includes(needle)))
  }).length
  return Math.max(0, serverTotal.value - deletedMatches)
})
const changes = computed<TopicChanges>(() => ({ mode: mode.value, updatedAt: summary.value.updatedAt, upserts: Object.values(upserts.value), deletes: deletedIds.value }))
const modeEnabled = computed({
  get: () => mode.value !== 'off',
  set: (enabled: boolean) => {
    if (!enabled && mode.value !== 'off') lastEnabledMode.value = mode.value
    mode.value = enabled ? lastEnabledMode.value : 'off'
    result.value = null
  },
})

async function load() {
  loading.value = true
  try {
    summary.value = await fetchTopicSummary()
    mode.value = summary.value.mode
    savedMode.value = mode.value
    if (mode.value !== 'off') lastEnabledMode.value = mode.value
    selectedRuleId.value = null
    await loadRules({ q: '', status: 'all', page: 1 })
  } catch { message.error(t('taskAdmission.loadFailed')) }
  finally { loading.value = false }
}

async function loadRules(params: { q: string; status: string; page: number }) {
  const request = ++rulesRequest
  currentQuery.value = params.q
  currentStatus.value = params.status
  currentPage.value = params.page
  loadingRules.value = true
  serverRules.value = []
  audienceSummaryLoaded.value = false
  try {
    const combined = !params.q && params.status === 'all'
    const pageStart = (params.page - 1) * PAGE_SIZE
    const newOnPage = combined ? newIds.value.slice(pageStart, pageStart + PAGE_SIZE).length : 0
    const savedSlots = PAGE_SIZE - newOnPage
    if (!savedSlots) {
      serverRules.value = []
      serverTotal.value = summary.value.ruleCount
      return
    }
    const result = await fetchTopicRules({ ...params, pageSize: savedSlots,
      ...(combined ? { offset: Math.max(0, pageStart - newIds.value.length) } : {}) })
    if (request !== rulesRequest) return
    serverRules.value = result.items
    serverTotal.value = result.total
    if (audienceExtension?.loadSummaries) {
      try {
        const summaries = await audienceExtension.loadSummaries(result.items.map(rule => rule.id))
        if (request === rulesRequest) {
          savedAudienceSummaries.value = summaries
          audienceSummaryLoaded.value = true
        }
      } catch { if (request === rulesRequest) savedAudienceSummaries.value = {} }
    }
    for (const rule of result.items) originalRules.value[rule.id] = rule
    if (params.page > 1 && !result.items.length && result.total) {
      await loadRules({ ...params, page: Math.ceil((result.total + (combined ? newIds.value.length : 0)) / PAGE_SIZE) })
    }
  } catch { if (request === rulesRequest) message.error(t('taskAdmission.loadFailed')) }
  finally { if (request === rulesRequest) loadingRules.value = false }
}

function setMode(nextMode: TopicMode) {
  // Keep rule edits while changing the mode; the save action submits both.
  mode.value = nextMode
  if (nextMode !== 'off') lastEnabledMode.value = nextMode
  result.value = null
}

async function addRule() {
  if (ruleCount.value >= MAX_RULES) {
    message.warning(t('taskAdmission.maxRules', { count: MAX_RULES }))
    return
  }
  const rule: TopicRule = { id: createClientUuid(), name: '', enabled: true, terms: [{ keyword: '', synonyms: [] }] }
  ruleListRef.value?.resetFilters()
  currentPage.value = 1
  currentQuery.value = ''
  currentStatus.value = 'all'
  newIds.value = [rule.id, ...newIds.value]
  upserts.value = { ...upserts.value, [rule.id]: rule }
  void loadRules({ q: '', status: 'all', page: 1 })
  await nextTick()
  selectedRuleId.value = rule.id
  try { await audiences.load(rule.id, true) }
  catch { message.error(t('taskAdmission.audienceLoadFailed')) }
  result.value = null
}

function updateRule(rule: TopicRule) {
  upserts.value = { ...upserts.value, [rule.id]: rule }
  result.value = null
}

function setEditingRule(id: string) {
  selectedRuleId.value = id
  void audiences.load(id, false).catch(() => message.error(t('taskAdmission.audienceLoadFailed')))
}

function closeRule() {
  const rule = selectedRule.value
  if (rule && newIds.value.includes(rule.id) && !rule.name?.trim()
    && rule.terms.every(term => !term.keyword.trim() && term.synonyms.every(synonym => !synonym.trim()))
    && !audiences.dirtyIds.value.includes(rule.id)) {
    removeRule(rule)
    return
  }
  if (rule && (!rule.terms.length || rule.terms.some(term => !term.keyword.trim()))) {
    message.warning(t('taskAdmission.keywordRequired'))
    return
  }
  if (rule && audiences.dirtyIds.value.includes(rule.id)) {
    const error = audiences.validate(rule.id)
    if (error) { message.warning(t(error)); return }
  }
  selectedRuleId.value = null
}

function cancelRule() {
  const rule = selectedRule.value
  if (rule && newIds.value.includes(rule.id)) {
    removeRule(rule)
    return
  }
  closeRule()
}

function removeRule(rule: TopicRule) {
  audiences.remove(rule.id)
  const wasNew = newIds.value.includes(rule.id)
  const drafts = { ...upserts.value }
  delete drafts[rule.id]
  upserts.value = drafts
  if (wasNew) newIds.value = newIds.value.filter(id => id !== rule.id)
  else deletedIds.value = [...deletedIds.value, rule.id]
  selectedRuleId.value = null
  result.value = null
  const lastPage = Math.max(1, Math.ceil(visibleTotal.value / PAGE_SIZE))
  if (currentPage.value > lastPage) void loadRules({ q: currentQuery.value, status: currentStatus.value, page: lastPage })
  else if (wasNew) void loadRules({ q: currentQuery.value, status: currentStatus.value, page: currentPage.value })
}

function validate(): boolean {
  for (const rule of Object.values(upserts.value)) {
    if (!rule.terms.length || rule.terms.some(term => !term.keyword.trim())) {
      selectedRuleId.value = rule.id
      message.warning(t('taskAdmission.keywordRequired'))
      return false
    }
  }
  const audienceError = audiences.validateDirty()
  if (audienceError) {
    selectedRuleId.value = audienceError.ruleId
    message.warning(t(audienceError.message))
    return false
  }
  return true
}

async function save() {
  if (!validate()) return
  saving.value = true
  let savingAudience = false
  try {
    if (modeDirty.value || Object.keys(upserts.value).length || deletedIds.value.length) {
      summary.value = await saveTopicChanges(changes.value)
      savedMode.value = summary.value.mode
      upserts.value = {}
      deletedIds.value = []
      newIds.value = []
      originalRules.value = {}
      await loadRules({ q: currentQuery.value, status: currentStatus.value, page: currentPage.value })
    }
    savingAudience = true
    await audiences.saveDirty()
    if (audienceExtension?.loadSummaries && serverRules.value.length) {
      try {
        savedAudienceSummaries.value = await audienceExtension.loadSummaries(serverRules.value.map(rule => rule.id))
        audienceSummaryLoaded.value = true
      } catch { audienceSummaryLoaded.value = false }
    }
    selectedRuleId.value = null
    message.success(t('taskAdmission.saved'))
  } catch (error) {
    message.error(savingAudience ? t('taskAdmission.audienceSaveFailed') : axios.isAxiosError(error) && error.response?.status === 409
      ? t('taskAdmission.concurrentUpdate') : t('taskAdmission.saveFailed'))
  }
  finally { saving.value = false }
}

async function test() {
  if (!sample.value.trim() || !validate()) return
  testing.value = true
  try { result.value = await previewTopicChanges(sample.value, changes.value) }
  catch { message.error(t('taskAdmission.testFailed')) }
  finally { testing.value = false }
}

onMounted(load)
</script>

<template>
  <div class="topic-page">
    <header class="topic-header">
      <div>
        <div class="topic-title">{{ t('taskAdmission.title') }}</div>
        <div class="topic-subtitle">{{ t('taskAdmission.description') }}</div>
      </div>
      <div class="topic-save-actions"><small v-if="modeDirty">{{ t('taskAdmission.unsavedMode') }}</small><n-button type="primary" :loading="saving" @click="save">{{ t('taskAdmission.save') }}</n-button></div>
    </header>

    <n-spin :show="loading">
      <div class="topic-workspace">
        <section class="topic-pane topic-rules-section">
          <div class="topic-section-head"><div><h2>{{ t('taskAdmission.keywordRules') }}</h2><p>{{ t('taskAdmission.ruleTermsDescription') }}</p></div><n-button secondary size="small" :disabled="ruleCount >= MAX_RULES" @click="addRule">+ {{ t('taskAdmission.addRule') }}</n-button></div>
          <TopicRuleList ref="ruleListRef" :rules="visibleRules" :total="visibleTotal" :page="currentPage" :loading="loadingRules" :audience-summaries="audienceSummaries" @edit="setEditingRule" @search="loadRules" @page="loadRules" />
        </section>

        <div class="topic-side">
          <section class="topic-pane topic-controls">
            <div class="topic-enable"><n-switch v-model:value="modeEnabled" /><div><strong>{{ t('taskAdmission.enable') }}</strong><small>{{ t('taskAdmission.defaultOff') }}</small></div></div>
            <TopicAdmissionModePicker v-if="modeEnabled" :model-value="mode" :pending="modeDirty" @update:model-value="setMode" />
            <n-alert v-if="mode === 'allowlist' && enabledRuleCount <= 0" type="warning" :bordered="false">{{ t('taskAdmission.emptyAllowlistWarning') }}</n-alert>
          </section>

          <section class="topic-pane topic-test">
            <div class="topic-section-head"><div><h2>{{ t('taskAdmission.ruleTest') }}</h2><p>{{ t('taskAdmission.previewDescription') }}</p></div></div>
            <n-input v-model:value="sample" type="textarea" :rows="5" :placeholder="t('taskAdmission.testInput')" />
            <div class="topic-test-actions"><span v-if="audienceExtension">{{ t('taskAdmission.testAudienceLimit') }}</span><n-button type="primary" secondary :loading="testing" :disabled="!sample.trim()" @click="test">{{ t('taskAdmission.testMatch') }}</n-button></div>
            <n-alert v-if="result" :type="result.allowed ? 'success' : 'warning'" :bordered="false">
              {{ result.allowed ? t('taskAdmission.allowed') : t('taskAdmission.blocked') }}<span v-if="result.matchedRule"> · {{ t('taskAdmission.matchedRule') }}：{{ result.matchedRule.keyword }}</span>
            </n-alert>
          </section>
        </div>
      </div>
    </n-spin>
    <TopicRuleDialog :rule="selectedRule" :is-new="Boolean(selectedRuleId && newIds.includes(selectedRuleId))"
      :audience-editor="audienceExtension?.component" :audience-badge="audienceBadge"
      :audience-value="selectedAudienceValue" :audience-loading="selectedAudienceLoading"
      @update:rule="updateRule" @update:audience="audiences.update" @remove="removeRule" @cancel="cancelRule" @done="closeRule" />
  </div>
</template>

<style scoped>
.topic-page { display: grid; gap: 14px; }
.topic-header, .topic-section-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.topic-title { color: #23324b; font-size: 22px; font-weight: 700; }
.topic-save-actions { display: flex; align-items: center; gap: 10px; }.topic-save-actions small { color: #bd6a19; font-size: 12px; }
.topic-subtitle, .topic-section-head p { margin: 3px 0 0; color: #7b8799; font-size: 12px; line-height: 1.45; }
.topic-controls { gap: 14px; }
.topic-enable { display: flex; align-items: center; gap: 12px; min-width: 220px; }.topic-enable > div { display: grid; gap: 2px; }.topic-enable strong { color: #344054; font-size: 13px; }.topic-enable small { color: #8b97a8; font-size: 11px; }
.topic-workspace { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(320px, .85fr); gap: 16px; align-items: start; }
.topic-side { display: grid; gap: 16px; min-width: 0; align-content: start; }
.topic-pane { display: grid; gap: 14px; min-width: 0; padding: 18px; border: 1px solid #e0e7f0; border-radius: 11px; background: #fff; }
.topic-section-head h2 { margin: 0; color: #25324a; font-size: 16px; }
.topic-test :deep(.n-input), .topic-test :deep(.n-alert) { width: 100%; }
.topic-test-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; }.topic-test-actions span { color: #8b97a8; font-size: 11px; line-height: 1.4; }
@media (max-width: 1100px) { .topic-workspace { grid-template-columns: 1fr; }.topic-side { display: contents; }.topic-controls { order: 0; }.topic-rules-section { order: 1; }.topic-test { order: 2; } }
@media (max-width: 680px) { .topic-header, .topic-section-head { align-items: flex-start; flex-direction: column; }.topic-pane { padding: 14px; } }
</style>
