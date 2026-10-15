<script setup lang="ts">
import { t } from '../../composables/i18n'

// Session-level view tabs (028). Mirrors the official dsh web
// `conversation.view` selection (chat | trajectory) without depending on the
// official React/cordis client packages. See
// docs/user-web-复用dsh-web会话能力-方案.md (route C).

const props = defineProps<{ view: 'chat' | 'trajectory' }>()
const emit = defineEmits<{ (e: 'update:view', view: 'chat' | 'trajectory'): void }>()

const tabs = [
  { id: 'chat', labelKey: 'chat.view.chat' },
  { id: 'trajectory', labelKey: 'chat.view.trajectory' },
] as const
</script>

<template>
  <div
    class="flex shrink-0 items-center gap-1 border-b border-gray-100 bg-white px-4 py-2"
    role="tablist"
  >
    <button
      v-for="tab in tabs"
      :key="tab.id"
      type="button"
      role="tab"
      :aria-selected="props.view === tab.id"
      class="rounded-lg px-3 py-1.5 text-sm font-medium transition-colors"
      :class="props.view === tab.id
        ? 'bg-gray-100 text-gray-900'
        : 'text-gray-500 hover:bg-gray-50 hover:text-gray-700'"
      @click="emit('update:view', tab.id)"
    >
      {{ t(tab.labelKey) }}
    </button>
  </div>
</template>
