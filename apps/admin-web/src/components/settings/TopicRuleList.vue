<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { t } from '@/composables/i18n'
import type { TopicRule } from '@/api/topic-admission'

type RuleStatus = 'all' | 'enabled' | 'disabled'
const props = defineProps<{ rules: TopicRule[]; total: number; page: number; loading: boolean; audienceSummaries?: Record<string, { key: string; count?: number }> }>()
const emit = defineEmits<{
  (event: 'edit', id: string): void
  (event: 'search', value: { q: string; status: RuleStatus; page: number }): void
  (event: 'page', value: { q: string; status: RuleStatus; page: number }): void
}>()

const query = ref('')
const status = ref<RuleStatus>('all')
const PAGE_SIZE = 10
const listRef = ref<HTMLElement | null>(null)
const footerRef = ref<HTMLElement | null>(null)
const listHeight = ref<number | null>(null)
let mainObserver: ResizeObserver | null = null
let searchTimer: ReturnType<typeof setTimeout> | null = null
const statusOptions = computed(() => [
  { label: t('taskAdmission.allStatuses'), value: 'all' },
  { label: t('taskAdmission.enabled'), value: 'enabled' },
  { label: t('taskAdmission.disabled'), value: 'disabled' },
])
const pageCount = computed(() => Math.max(1, Math.ceil(props.total / PAGE_SIZE)))
const rangeStart = computed(() => props.total && props.rules.length ? (props.page - 1) * PAGE_SIZE + 1 : 0)
const rangeEnd = computed(() => Math.min((props.page - 1) * PAGE_SIZE + props.rules.length, props.total))

function summary(rule: TopicRule): string {
  const terms = rule.terms.flatMap(term => [term.keyword, ...term.synonyms]).map(term => term.trim()).filter(Boolean)
  return (rule.name?.trim() ? terms : terms.slice(1)).join(' · ') || t('taskAdmission.editRuleTerms')
}

function changePage(nextPage: number) {
  emit('page', { q: query.value.trim(), status: status.value, page: nextPage })
  if (listRef.value) listRef.value.scrollTop = 0
}

function resetFilters() {
  query.value = ''
  status.value = 'all'
  if (searchTimer) clearTimeout(searchTimer)
  emit('search', { q: '', status: 'all', page: 1 })
}

defineExpose({ resetFilters })

function fitListToViewport() {
  const list = listRef.value
  const footer = footerRef.value
  const main = list?.closest<HTMLElement>('.settings-main')
  if (!list || !footer || !main) return

  const pane = list.closest<HTMLElement>('.topic-pane')
  const mainBottom = main.getBoundingClientRect().bottom - parseFloat(getComputedStyle(main).paddingBottom)
  const panePadding = pane ? parseFloat(getComputedStyle(pane).paddingBottom) : 18
  const available = mainBottom - list.getBoundingClientRect().top - footer.getBoundingClientRect().height - panePadding - 8
  listHeight.value = Math.max(120, Math.min(600, Math.floor(available)))
}

onMounted(() => {
  const main = listRef.value?.closest<HTMLElement>('.settings-main')
  if (main) {
    mainObserver = new ResizeObserver(fitListToViewport)
    mainObserver.observe(main)
  }
  window.addEventListener('resize', fitListToViewport)
  fitListToViewport()
})

onUnmounted(() => {
  mainObserver?.disconnect()
  window.removeEventListener('resize', fitListToViewport)
  if (searchTimer) clearTimeout(searchTimer)
})

watch(() => props.rules.length, async () => {
  await nextTick()
  if (!mainObserver) {
    const main = listRef.value?.closest<HTMLElement>('.settings-main')
    if (main) {
      mainObserver = new ResizeObserver(fitListToViewport)
      mainObserver.observe(main)
    }
  }
  fitListToViewport()
})

watch([query, status], () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => emit('search', { q: query.value.trim(), status: status.value, page: 1 }), 250)
  if (listRef.value) listRef.value.scrollTop = 0
})
</script>

<template>
  <div class="rule-browser">
    <div class="rule-filters">
      <n-input v-model:value="query" clearable :placeholder="t('taskAdmission.searchRules')" :aria-label="t('taskAdmission.searchRules')" />
      <n-select v-model:value="status" :options="statusOptions" :aria-label="t('taskAdmission.ruleStatus')" />
    </div>
    <div ref="listRef" class="rule-scroll" :style="listHeight === null ? undefined : { height: `${listHeight}px` }" role="group" :aria-label="t('taskAdmission.keywordRules')">
      <div v-for="rule in rules" :key="rule.id" class="rule-shell">
        <button class="rule-row" type="button" @click="emit('edit', rule.id)">
          <span class="rule-main"><strong>{{ rule.name?.trim() || rule.terms[0]?.keyword?.trim() || t('taskAdmission.newRule') }}</strong><small><span class="rule-terms">{{ summary(rule) }}</span><span v-if="audienceSummaries?.[rule.id]" class="rule-audience">{{ t(audienceSummaries[rule.id].key, { count: audienceSummaries[rule.id].count ?? 0 }) }}</span></small></span>
          <span class="rule-status" :class="{ muted: !rule.enabled }">{{ t(rule.enabled ? 'taskAdmission.enabled' : 'taskAdmission.disabled') }}</span>
        </button>
      </div>
      <div v-if="!loading && !rules.length" class="rule-no-results">{{ total ? t('taskAdmission.noRulesOnPage') : !query && status === 'all' ? t('taskAdmission.noRules') : t('taskAdmission.noMatchingRules') }}</div>
    </div>
    <div ref="footerRef" class="rule-footer">
      <span>{{ t('taskAdmission.pagination', { from: rangeStart, to: rangeEnd, count: total }) }}</span>
      <n-pagination v-if="pageCount > 1" :page="page" :page-size="PAGE_SIZE" :item-count="total" :page-slot="5" size="small" @update:page="changePage" />
    </div>
  </div>
</template>

<style scoped>
.rule-browser { display: grid; gap: 10px; min-width: 0; }
.rule-filters { display: grid; grid-template-columns: minmax(0, 1fr) 112px; gap: 8px; }
.rule-scroll { box-sizing: border-box; height: min(52vh, 480px); min-height: 100px; margin-top: 6px; overflow-y: scroll; overscroll-behavior: contain; scrollbar-gutter: stable; scrollbar-color: #becbdb #f5f7fb; scrollbar-width: thin; padding: 2px 4px 2px 2px; }
.rule-scroll::-webkit-scrollbar { width: 8px; }.rule-scroll::-webkit-scrollbar-track { background: #f5f7fb; border-radius: 8px; }.rule-scroll::-webkit-scrollbar-thumb { background: #becbdb; border-radius: 8px; }
.rule-shell + .rule-shell { margin-top: 6px; }
.rule-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; width: 100%; min-height: 49px; padding: 7px 10px; border: 1px solid #e5eaf2; border-radius: 8px; color: #28364e; background: #fff; text-align: left; cursor: pointer; transition: border-color .15s, background .15s; }
.rule-row:hover { border-color: #b8c9ec; background: #f8faff; }
.rule-main { display: grid; min-width: 0; gap: 3px; }.rule-main strong, .rule-main small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.rule-main strong { font-size: 13px; font-weight: 600; }.rule-main small { color: #8290a4; font-size: 12px; }
.rule-main small { display: flex; gap: 8px; }.rule-terms { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.rule-audience { flex: 0 0 auto; color: #61718a; }.rule-audience::before { content: '·'; margin-right: 8px; color: #b3bece; }
.rule-status { flex: 0 0 auto; color: #258260; font-size: 11px; }.rule-status.muted { color: #98a2b3; }
.rule-footer { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; min-height: 28px; color: #8b97a8; font-size: 11px; }.rule-no-results { display: grid; place-items: center; min-height: 82px; border: 1px dashed #dce4ef; border-radius: 8px; color: #8b97a8; font-size: 12px; }
@media (max-width: 520px) { .rule-filters { grid-template-columns: 1fr; } }
</style>
