import { computed, ref, type Ref } from 'vue'
import type { Locale } from '../../composables/i18n'
import { t, translateSourceText } from '../../composables/i18n'
import type { KnowledgeSourceSummary } from '../../api/knowledgeSource'
import { fetchEffectiveShortcuts } from '../../api/shortcuts'
import { internalKnowledgeBaseName } from '../../locales/legacyRecognitionValues'
import ChatComposer from './ChatComposer.vue'
import { promptGuideCategories, type PromptGuideConfigTarget, type PromptGuideItem } from './promptGuideConfig'
import { effectiveShortcutEntries, resolveShortcutGuideCategories } from './shortcutGuideResolver'

type PromptGuideOptions = {
  allowContent: Ref<boolean>
  allowKnowledge: Ref<boolean>
  allowTools: Ref<boolean>
  locale: Ref<Locale>
  composerRef: Ref<InstanceType<typeof ChatComposer> | null>
  authToken: () => string | undefined
  userId: () => string | undefined
  openSkills: () => void
  openKnowledge: () => void
  openTools: () => void
}

export function usePromptGuide(options: PromptGuideOptions) {
  const { allowContent, allowKnowledge, allowTools, locale, composerRef } = options
  const activePromptGuideKey = ref<string | null>(null)
  const knowledgeSourceSummary = ref<KnowledgeSourceSummary>({ mode: 'movo', displayName: '' })
  function setKnowledgeSourceSummary(source: KnowledgeSourceSummary) {
    knowledgeSourceSummary.value = source
    if (source.mode === 'external' && activePromptGuideKey.value === 'internal') promptGuideNotice.value = null
  }
  const effectivePromptGuideCategories = ref(promptGuideCategories)
  const promptGuideNotice = ref<{
    title: string
    description: string
    target: PromptGuideConfigTarget
  } | null>(null)
  let promptGuideCloseTimer: ReturnType<typeof setTimeout> | null = null

  const visiblePromptGuideCategories = computed(() => (effectivePromptGuideCategories.value ?? [])
    .map((category) => category.key === 'favorites'
      ? { ...category, items: (category.items ?? []).filter(item =>
        (item.categoryKey !== 'content' || allowContent.value)
        && (item.categoryKey !== 'internal' || allowKnowledge.value)
        && (item.categoryKey !== 'systems' || allowTools.value)) }
      : category.key === 'internal' && knowledgeSourceSummary.value.mode === 'external'
        ? {
          ...category,
          label: knowledgeSourceSummary.value.displayName,
          requiresConfig: false,
          items: category.items ?? [],
        }
        : category)
    .filter((category) => {
      if (category.key === 'content') return allowContent.value
      if (category.key === 'internal') return allowKnowledge.value
      if (category.key === 'systems') return allowTools.value
      return (category.items ?? []).length > 0
    }))
  const activePromptGuideCategory = computed(() => (
    visiblePromptGuideCategories.value.find((item) => item.key === activePromptGuideKey.value) || null
  ))

  function selectPromptGuideCategory(key: string) {
    cancelPromptGuideClose()
    activePromptGuideKey.value = key
    const category = visiblePromptGuideCategories.value.find((item) => item.key === key)
    if (!category) return
    promptGuideNotice.value = category?.requiresConfig
      ? {
        title: category.configTitle || t('legacy.setup_required_d047e4f'),
        description: category.configDescription || t('legacy.complete_setup_before_using_this_capability'),
        target: category.configTarget || 'tools',
      }
      : null
  }

  function closePromptGuide() {
    cancelPromptGuideClose()
    activePromptGuideKey.value = null
    promptGuideNotice.value = null
  }

  function cancelPromptGuideClose() {
    if (promptGuideCloseTimer) {
      clearTimeout(promptGuideCloseTimer)
      promptGuideCloseTimer = null
    }
  }

  function schedulePromptGuideClose() {
    cancelPromptGuideClose()
    promptGuideCloseTimer = setTimeout(() => {
      activePromptGuideKey.value = null
      promptGuideNotice.value = null
      promptGuideCloseTimer = null
    }, 220)
  }

  async function usePromptGuideItem(item: PromptGuideItem) {
    if (!item.available) {
      promptGuideNotice.value = {
        title: item.configTitle || t('legacy.setup_required_d047e4f'),
        description: item.configDescription || t('legacy.complete_setup_before_using_this_capability'),
        target: item.configTarget || 'tools',
      }
      return
    }
    if (!item.prompt) return
    promptGuideNotice.value = null
    if (item.shortcutType === 'skill') {
      try {
        const selected = item.resourceId && await composerRef.value?.selectShortcutSkill(item.resourceId, item.label)
        if (!selected) {
          promptGuideNotice.value = {
            title: t('shortcuts.skill_unavailable'),
            description: t('shortcuts.skill_unavailable_hint'),
            target: 'skills',
          }
          return
        }
      } catch {
        promptGuideNotice.value = {
          title: t('shortcuts.skill_unavailable'),
          description: t('shortcuts.skill_unavailable_hint'),
          target: 'skills',
        }
        return
      }
    }
    if (item.categoryKey === 'internal' || activePromptGuideCategory.value?.key === 'internal') {
      composerRef.value?.enableKnowledgeQa()
    }
    let prompt = translateSourceText(item.prompt)
    if (knowledgeSourceSummary.value.mode === 'external'
      && (item.categoryKey === 'internal' || activePromptGuideCategory.value?.key === 'internal')) {
      prompt = prompt.replaceAll(internalKnowledgeBaseName[locale.value], knowledgeSourceSummary.value.displayName)
    }
    await composerRef.value?.setTextAndFocus(prompt)
  }

  function openPromptGuideConfig(target: PromptGuideConfigTarget) {
    if (target === 'skills') options.openSkills()
    else if (target === 'knowledge') options.openKnowledge()
    else options.openTools()
  }

  async function loadPromptGuideShortcuts() {
    if (!options.authToken() || !options.userId()) {
      effectivePromptGuideCategories.value = promptGuideCategories
      return
    }
    try {
      const result = await fetchEffectiveShortcuts()
      effectivePromptGuideCategories.value = resolveShortcutGuideCategories(effectiveShortcutEntries(result), result.configured, result.groups)
    } catch {
      effectivePromptGuideCategories.value = promptGuideCategories
    }
  }

  function handleShortcutPreferencesUpdated() {
    void loadPromptGuideShortcuts()
  }

  return {
    activePromptGuideKey, promptGuideNotice, visiblePromptGuideCategories,
    activePromptGuideCategory, setKnowledgeSourceSummary, selectPromptGuideCategory,
    closePromptGuide, cancelPromptGuideClose, schedulePromptGuideClose,
    usePromptGuideItem, openPromptGuideConfig, loadPromptGuideShortcuts,
    handleShortcutPreferencesUpdated,
  }
}
