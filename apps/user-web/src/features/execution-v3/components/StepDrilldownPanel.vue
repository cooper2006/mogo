<script setup lang="ts">
import { computed } from 'vue'
import { t, useLocale } from '../../../composables/i18n'
import { formatRunDuration } from '../domain/runTiming'
import type { ReplayStep } from '../domain/replaySteps'
import { stepLabel } from '../domain/replaySteps'

// 043 (session replay): step drill-down.
//
// Shows what one step was asked to do, what it produced and how long it took.
// The cost row is *conditional*: it only renders when the event payload actually
// carried a cost (spec R-07/R-13). No placeholder, no zero, no estimate — with
// 035 not yet landed on the user-web event stream, this row simply never shows.

const props = defineProps<{ step: ReplayStep }>()

const { locale } = useLocale()

const duration = computed(() =>
  formatRunDuration(props.step.durationMs, locale.value),
)

const hasCost = computed(
  () => props.step.costUsd !== null && Number.isFinite(props.step.costUsd),
)

const costText = computed(() => {
  if (!hasCost.value) return ''
  const value = Number(props.step.costUsd)
  return `$${value.toFixed(value < 0.01 ? 4 : 2)}`
})
</script>

<template>
  <div class="mt-2 rounded-xl border border-gray-200 bg-gray-50/70 p-3 text-xs">
    <header class="mb-2 flex flex-wrap items-center gap-2">
      <span class="font-medium text-gray-700">{{ stepLabel(props.step) }}</span>
      <span class="rounded bg-white px-1.5 py-0.5 text-[11px] text-gray-500">
        {{ props.step.kind }}
      </span>
      <span v-if="duration" class="text-gray-500">
        {{ t('chat.view.replay_duration') }} · {{ duration }}
      </span>
      <span v-if="hasCost" class="text-gray-400 opacity-60">
        {{ t('chat.view.replay_cost') }} · {{ costText }}
        {{ t('chat.view.replay_cost_reference') }}
      </span>
    </header>

    <dl class="space-y-2">
      <div>
        <dt class="mb-0.5 font-medium text-gray-500">{{ t('chat.view.replay_input') }}</dt>
        <dd class="whitespace-pre-wrap break-words text-gray-700">
          {{ props.step.input || t('chat.view.replay_empty_field') }}
        </dd>
      </div>
      <div>
        <dt class="mb-0.5 font-medium text-gray-500">{{ t('chat.view.replay_output') }}</dt>
        <dd class="whitespace-pre-wrap break-words text-gray-700">
          {{ props.step.output || t('chat.view.replay_empty_field') }}
        </dd>
      </div>
    </dl>
  </div>
</template>
