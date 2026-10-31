<script setup lang="ts">
import { t } from '@/composables/i18n'
import type { TopicMode } from '@/api/topic-admission'

defineProps<{ modelValue: TopicMode; pending: boolean }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: 'denylist' | 'allowlist'): void }>()
</script>

<template>
  <div class="mode-picker" role="group" :aria-label="t('taskAdmission.mode')">
    <button type="button" class="mode-card deny" :class="{ selected: modelValue === 'denylist' }" :aria-pressed="modelValue === 'denylist'" @click="emit('update:modelValue', 'denylist')">
      <span class="mode-head"><span class="mode-icon" aria-hidden="true">−</span><strong>{{ t('taskAdmission.blocklist') }}</strong><span v-if="modelValue === 'denylist'" class="mode-state">{{ t(pending ? 'taskAdmission.pending' : 'taskAdmission.currentMode') }}</span></span>
      <small>{{ t('taskAdmission.blocklistBehavior') }}</small>
    </button>
    <button type="button" class="mode-card allow" :class="{ selected: modelValue === 'allowlist' }" :aria-pressed="modelValue === 'allowlist'" @click="emit('update:modelValue', 'allowlist')">
      <span class="mode-head"><span class="mode-icon" aria-hidden="true">✓</span><strong>{{ t('taskAdmission.allowlist') }}</strong><span v-if="modelValue === 'allowlist'" class="mode-state">{{ t(pending ? 'taskAdmission.pending' : 'taskAdmission.currentMode') }}</span></span>
      <small>{{ t('taskAdmission.allowlistBehavior') }}</small>
    </button>
  </div>
</template>

<style scoped>
.mode-picker { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; width: 100%; }
.mode-card { --accent: #b65342; --tint: #fff5f2; --ring: #f5d6cf; display: grid; gap: 6px; min-width: 0; min-height: 74px; padding: 10px 12px; border: 1px solid #dfe5ed; border-radius: 9px; background: #fff; color: #344054; text-align: left; cursor: pointer; transition: border-color .15s, box-shadow .15s, background .15s; }
.mode-card.allow { --accent: #16845b; --tint: #effaf4; --ring: #caebd9; }
.mode-card:hover { border-color: var(--accent); }.mode-card:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.mode-card.selected { border-color: var(--accent); background: var(--tint); box-shadow: 0 0 0 2px var(--ring); }
.mode-head { display: flex; align-items: center; gap: 7px; min-width: 0; }.mode-head strong { font-size: 13px; white-space: nowrap; }.mode-icon { display: grid; flex: 0 0 20px; place-items: center; width: 20px; height: 20px; border-radius: 5px; background: var(--tint); color: var(--accent); font-size: 15px; font-weight: 700; }
.mode-state { margin-left: auto; padding: 2px 6px; border-radius: 4px; background: var(--accent); color: #fff; font-size: 10px; font-weight: 600; white-space: nowrap; }
.mode-card small { color: #667085; font-size: 11px; }
@media (max-width: 520px) { .mode-picker { grid-template-columns: 1fr; } }
</style>
