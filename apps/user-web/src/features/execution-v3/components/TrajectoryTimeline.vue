<script lang="ts">
export type TimelineAnchor = {
  key: string
  index: number
  time: string
  live: boolean
}
</script>

<script setup lang="ts">
import { t } from '../../../composables/i18n'

// 043 (session replay): cross-round timeline.
//
// Pure presentation: it knows nothing about the execution stores, it only
// renders one anchor per assistant round and emits the focus request. The parent
// (`SessionTrajectoryView`) owns the focus state, so multi-pane isolation is
// automatic — no store involved (spec R-009).

const props = defineProps<{
  anchors: TimelineAnchor[]
  focusedKey: string | null
}>()

const emit = defineEmits<{
  (e: 'select', key: string): void
  (e: 'exit'): void
  (e: 'jump', edge: 'earliest' | 'latest'): void
}>()
</script>

<template>
  <nav
    v-if="props.anchors.length > 0"
    class="sticky top-0 z-10 -mx-4 border-b border-gray-100 bg-gray-50/95 px-4 py-2 backdrop-blur md:-mx-6 md:px-6"
    :aria-label="t('chat.view.replay_timeline')"
  >
    <div class="mb-1 flex items-center justify-between gap-2 text-xs text-gray-500">
      <span class="font-medium">{{ t('chat.view.replay_timeline') }}</span>
      <span class="flex items-center gap-2">
        <button
          type="button"
          class="rounded px-1.5 py-0.5 hover:bg-gray-200/70 disabled:opacity-40"
          :disabled="props.anchors.length < 2"
          @click="emit('jump', 'earliest')"
        >
          {{ t('chat.view.replay_go_earliest') }}
        </button>
        <button
          type="button"
          class="rounded px-1.5 py-0.5 hover:bg-gray-200/70 disabled:opacity-40"
          :disabled="props.anchors.length < 2"
          @click="emit('jump', 'latest')"
        >
          {{ t('chat.view.replay_go_latest') }}
        </button>
        <button
          v-if="props.focusedKey"
          type="button"
          class="rounded px-1.5 py-0.5 text-gray-600 hover:bg-gray-200/70"
          @click="emit('exit')"
        >
          {{ t('chat.view.replay_exit_focus') }}
        </button>
      </span>
    </div>
    <ol class="flex gap-1.5 overflow-x-auto pb-1 custom-scrollbar">
      <li v-for="anchor in props.anchors" :key="anchor.key" class="shrink-0">
        <button
          type="button"
          class="flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs transition-colors"
          :class="anchor.key === props.focusedKey
            ? 'border-blue-300 bg-blue-50 text-blue-700'
            : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'"
          :aria-current="anchor.key === props.focusedKey ? 'true' : undefined"
          @click="emit('select', anchor.key)"
        >
          <span class="font-medium">{{ anchor.index }}</span>
          <span v-if="anchor.time" class="text-gray-400">{{ anchor.time }}</span>
          <span
            v-if="anchor.live"
            class="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500"
            :title="t('chat.view.replay_running')"
          />
        </button>
      </li>
    </ol>
  </nav>
</template>
