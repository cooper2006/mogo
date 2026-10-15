<script setup lang="ts">
import { computed } from 'vue'
import ExecutionViewV3 from './ExecutionViewV3.vue'
import { ensureMessageExecutionV3 } from '../stores/messageExecution'
import { collectTrajectoryRounds } from '../domain/trajectoryRounds'
import { formatAppTime } from '../../../composables/appTimezone'
import { t } from '../../../composables/i18n'

// Session-level trajectory view (028, route C).
//
// The conversation and the trajectory are two projections of the SAME V3 event
// stream (see services/chat-api/app/dsh_runtime/events/projection.py). This view
// reuses the per-message ExecutionStoreV3 that ChatWindow already attaches, so it
// adds zero data plumbing. Stage 1 renders one ExecutionViewV3 per assistant
// round, stacked chronologically; a cross-round aggregate timeline is stage 2.
//
// Read-only by design: no permission binding here. Approval stays in the
// conversation tab (the legacy /chat/permission route is a dead link).

type TrajectoryMessage = {
  _id?: string
  role?: string
  created_at?: string
  execution_events?: unknown[]
  documents?: unknown[]
  evidence_bundles?: unknown[]
  evidenceBundles?: unknown[]
}

const props = defineProps<{ messages: TrajectoryMessage[] }>()

type EnsureArg = Parameters<typeof ensureMessageExecutionV3>[0]

const rounds = computed(() =>
  collectTrajectoryRounds(props.messages).map((round) => {
    const store = ensureMessageExecutionV3(round.message as unknown as EnsureArg)
    return {
      key: round.key,
      index: round.index,
      time: formatAppTime(round.message.created_at),
      live: store.state.runStatus === 'running',
      store,
    }
  }),
)
</script>

<template>
  <div class="h-full w-full overflow-y-auto custom-scrollbar bg-gray-50/40">
    <div
      v-if="rounds.length === 0"
      class="flex h-full items-center justify-center px-6 text-sm text-gray-400"
    >
      {{ t('chat.view.trajectory_empty') }}
    </div>
    <div v-else class="mx-auto w-full max-w-4xl space-y-4 p-4 md:p-6">
      <section
        v-for="round in rounds"
        :key="round.key"
        class="rounded-2xl border border-gray-100 bg-white p-4"
      >
        <header class="mb-3 flex items-center gap-2 text-xs font-medium text-gray-400">
          <span class="rounded-full bg-gray-100 px-2 py-0.5 text-gray-600">
            {{ t('chat.view.trajectory_round', { index: round.index }) }}
          </span>
          <span v-if="round.time">{{ round.time }}</span>
        </header>
        <ExecutionViewV3 :store="round.store" :live="round.live" />
      </section>
    </div>
  </div>
</template>
