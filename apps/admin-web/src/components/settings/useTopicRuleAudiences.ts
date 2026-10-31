import { ref } from 'vue'
import type { TopicRuleAudienceUiExtension } from '@/product/contracts'

export function useTopicRuleAudiences(extension?: TopicRuleAudienceUiExtension) {
  const values = ref<Record<string, unknown>>({})
  const loading = ref<Record<string, boolean>>({})
  const dirtyIds = ref<string[]>([])

  async function load(ruleId: string, isNew: boolean): Promise<void> {
    if (!extension || Object.prototype.hasOwnProperty.call(values.value, ruleId) || loading.value[ruleId]) return
    loading.value = { ...loading.value, [ruleId]: true }
    try {
      const value = isNew ? extension.createValue() : await extension.load(ruleId)
      values.value = { ...values.value, [ruleId]: value }
    } finally {
      const next = { ...loading.value }
      delete next[ruleId]
      loading.value = next
    }
  }

  function update(ruleId: string, value: unknown): void {
    values.value = { ...values.value, [ruleId]: value }
    if (!dirtyIds.value.includes(ruleId)) dirtyIds.value = [...dirtyIds.value, ruleId]
  }

  function remove(ruleId: string): void {
    const next = { ...values.value }
    delete next[ruleId]
    values.value = next
    dirtyIds.value = dirtyIds.value.filter(id => id !== ruleId)
  }

  function validate(ruleId: string): string | null {
    return extension?.validate?.(values.value[ruleId]) || null
  }

  function validateDirty(): { ruleId: string; message: string } | null {
    for (const ruleId of dirtyIds.value) {
      const message = validate(ruleId)
      if (message) return { ruleId, message }
    }
    return null
  }

  async function saveDirty(): Promise<void> {
    if (!extension) return
    for (const ruleId of [...dirtyIds.value]) {
      await extension.save(ruleId, values.value[ruleId])
      dirtyIds.value = dirtyIds.value.filter(id => id !== ruleId)
    }
  }

  return { values, loading, dirtyIds, load, update, remove, validate, validateDirty, saveDirty }
}
