<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import ExecutionViewV3 from './ExecutionViewV3.vue'
import TrajectoryTimeline from './TrajectoryTimeline.vue'
import StepDrilldownPanel from './StepDrilldownPanel.vue'
import { ensureMessageExecutionV3 } from '../stores/messageExecution'
import { collectTrajectoryRounds } from '../domain/trajectoryRounds'
import { extractReplaySteps, stepLabel, type ReplayStep } from '../domain/replaySteps'
import { formatAppTime } from '../../../composables/appTimezone'
import { t } from '../../../composables/i18n'

// Session-level trajectory view (028, route C) + replay (043, stage 1).
//
// The conversation and the trajectory are two projections of the SAME V3 event
// stream (see services/chat-api/app/dsh_runtime/events/projection.py). This view
// reuses the per-message ExecutionStoreV3 that ChatWindow already attaches, so it
// adds zero data plumbing.
//
// 043 adds three things on top of the 028 stack, all purely local:
//   1. a cross-round timeline that focuses one round at a time,
//   2. step drill-down (input / output / duration, cost only when present),
//   3. new-round awareness while the run is still streaming.
// Focus state lives here as component state (spec FR-009): nothing is persisted
// and no store is touched, so the two panes stay independent.
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

/** Spec R-15: above this many rounds the timeline is advisory, nothing is virtualised. */
const LONG_SESSION_ROUNDS = 300
/** Spec R-08: auto-follow only while the reader is within this many px of the bottom. */
const BOTTOM_SLACK_PX = 40

const focusedKey = ref<string | null>(null)
const expandedStepIds = ref<string[]>([])
const pendingNewRounds = ref(0)
const now = ref(Date.now())
const scroller = ref<HTMLElement | null>(null)

let timer: ReturnType<typeof setInterval> | null = null

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

const anchors = computed(() =>
  rounds.value.map((round) => ({
    key: round.key,
    index: round.index,
    time: round.time,
    live: round.live,
  })),
)

const focusedRound = computed(
  () => rounds.value.find((round) => round.key === focusedKey.value) || null,
)

const anyLive = computed(() => rounds.value.some((round) => round.live))

/** A round stays expanded when nothing is focused (028 behaviour), else only the focused one. */
function isExpanded(key: string): boolean {
  return focusedKey.value === null || focusedKey.value === key
}

/** Steps of one round, recomputed from its own store snapshot. */
function stepsOf(round: (typeof rounds.value)[number]): ReplayStep[] {
  const state = round.store.state as unknown as {
    order?: string[]
    items?: Record<string, any>
  }
  return extractReplaySteps(state.order, state.items, now.value)
}

const focusedSteps = computed<ReplayStep[]>(() =>
  focusedRound.value ? stepsOf(focusedRound.value) : [],
)

const expandedSteps = computed<ReplayStep[]>(() =>
  focusedSteps.value.filter((step) => expandedStepIds.value.includes(step.id)),
)

function toggleStep(stepId: string) {
  const index = expandedStepIds.value.indexOf(stepId)
  if (index >= 0) expandedStepIds.value.splice(index, 1)
  else expandedStepIds.value.push(stepId)
}

/** Spec R-16: a stale focus (round removed / re-derived) must not blank the pane. */
function normalizeFocus() {
  const stillThere = rounds.value.some((round) => round.key === focusedKey.value)
  if (focusedKey.value && !stillThere) {
    focusedKey.value = rounds.value.length ? rounds.value[rounds.value.length - 1].key : null
    expandedStepIds.value = []
  }
}

function focusRound(key: string) {
  if (focusedKey.value === key) {
    focusedKey.value = null
    expandedStepIds.value = []
    return
  }
  focusedKey.value = key
  expandedStepIds.value = []
  pendingNewRounds.value = 0
}

function exitFocus() {
  focusedKey.value = null
  expandedStepIds.value = []
}

function jump(edge: 'earliest' | 'latest') {
  const list = rounds.value
  if (!list.length) return
  focusRound(edge === 'latest' ? list[list.length - 1].key : list[0].key)
  pendingNewRounds.value = 0
}

function nearBottom(): boolean {
  const el = scroller.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight <= BOTTOM_SLACK_PX
}

function scrollToBottom() {
  const el = scroller.value
  if (el) el.scrollTop = el.scrollHeight
}

watch(
  () => rounds.value.length,
  (next, previous) => {
    if (!previous || next <= previous) return
    normalizeFocus()
    if (focusedKey.value === null && nearBottom()) scrollToBottom()
    else pendingNewRounds.value += next - previous
  },
)

watch(
  () => rounds.value.map((round) => round.key).join('|'),
  () => normalizeFocus(),
)

onMounted(() => {
  // Only the live round needs a ticking clock; a finished session is static.
  timer = setInterval(() => {
    if (anyLive.value) now.value = Date.now()
  }, 1000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  timer = null
})
</script>

<template>
  <div ref="scroller" class="h-full w-full overflow-y-auto custom-scrollbar bg-gray-50/40">
    <div
      v-if="rounds.length === 0"
      class="flex h-full items-center justify-center px-6 text-sm text-gray-400"
    >
      {{ t('chat.view.trajectory_empty') }}
    </div>
    <div v-else class="mx-auto w-full max-w-4xl space-y-4 p-4 md:p-6">
      <TrajectoryTimeline
        :anchors="anchors"
        :focused-key="focusedKey"
        @select="focusRound"
        @exit="exitFocus"
        @jump="jump"
      />

      <p v-if="rounds.length >= LONG_SESSION_ROUNDS" class="text-xs text-amber-600">
        {{ t('chat.view.replay_long_session', { count: rounds.length }) }}
      </p>

      <button
        v-if="pendingNewRounds > 0"
        type="button"
        class="sticky bottom-2 z-10 mx-auto block rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs text-blue-700 shadow-sm"
        @click="jump('latest')"
      >
        {{ t('chat.view.replay_new_rounds', { count: pendingNewRounds }) }}
      </button>

      <section
        v-for="round in rounds"
        :key="round.key"
        class="rounded-2xl border bg-white p-4"
        :class="round.key === focusedKey ? 'border-blue-200' : 'border-gray-100'"
      >
        <header class="mb-3 flex flex-wrap items-center gap-2 text-xs font-medium text-gray-400">
          <button
            type="button"
            class="rounded-full px-2 py-0.5"
            :class="round.key === focusedKey ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-600'"
            @click="focusRound(round.key)"
          >
            {{ t('chat.view.trajectory_round', { index: round.index }) }}
          </button>
          <span v-if="round.time">{{ round.time }}</span>
          <span v-if="round.live" class="text-emerald-600">{{ t('chat.view.replay_running') }}</span>
          <button
            v-if="focusedKey"
            type="button"
            class="ml-auto text-gray-500 underline-offset-2 hover:underline"
            @click="isExpanded(round.key) ? exitFocus() : focusRound(round.key)"
          >
            {{ isExpanded(round.key) ? t('chat.view.replay_exit_focus') : t('chat.view.replay_focus_round') }}
          </button>
        </header>

        <template v-if="isExpanded(round.key)">
          <ExecutionViewV3 :store="round.store" :live="round.live" />

          <div v-if="focusedKey === round.key" class="mt-3 border-t border-gray-100 pt-3">
            <p class="mb-1 text-xs font-medium text-gray-500">
              {{ t('chat.view.replay_steps', { count: stepsOf(round).length }) }}
            </p>
            <ul class="flex flex-wrap gap-1.5">
              <li v-for="step in stepsOf(round)" :key="step.id">
                <button
                  type="button"
                  class="rounded border px-2 py-0.5 text-[11px]"
                  :class="expandedStepIds.includes(step.id)
                    ? 'border-blue-300 bg-blue-50 text-blue-700'
                    : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'"
                  @click="toggleStep(step.id)"
                >
                  {{ stepLabel(step) }}
                </button>
              </li>
            </ul>

            <StepDrilldownPanel
              v-for="step in expandedSteps"
              :key="`panel-${step.id}`"
              :step="step"
            />
          </div>
        </template>

        <p v-else class="text-xs text-gray-400">
          {{ t('chat.view.replay_collapsed', { index: round.index }) }}
        </p>
      </section>
    </div>
  </div>
</template>
