import assert from 'node:assert/strict'
import { collectTrajectoryAnchors, collectTrajectoryRounds } from '../src/features/execution-v3/domain/trajectoryRounds'
import {
  extractReplaySteps,
  isDrillableEvent,
  readCostUsd,
  stepInputText,
  stepLabel,
  stepOutputText,
  type ReplayStepSource,
} from '../src/features/execution-v3/domain/replaySteps'
import { formatRunDuration, elapsedRunMs } from '../src/features/execution-v3/domain/runTiming'

// 043 (session replay) unit tests — pure projections only.
//
// These cover the parts that can silently break the acceptance criteria:
//   T008 anchor derivation (round numbering, non-assistant filtering),
//   T009 steps.ts (drill-down input/output extraction + duration),
//   T010 cost guard (R-07: never fabricate a cost).

// ---- T008: timeline anchors -------------------------------------------------

const messages = [
  { _id: 'u1', role: 'user', created_at: '2026-10-24T01:00:00Z' },
  { _id: 'a1', role: 'assistant', created_at: '2026-10-24T01:00:05Z' },
  { _id: 'u2', role: 'user', created_at: '2026-10-24T01:01:00Z' },
  { _id: 'a2', role: 'assistant' }, // no id, no created_at → synthetic key, 2nd round
  { _id: 'a3', role: 'assistant', created_at: '2026-10-24T01:02:00Z' },
]

const anchors = collectTrajectoryAnchors(messages)
assert.equal(anchors.length, 3, 'one anchor per assistant round')
assert.deepEqual(anchors.map((a) => a.index), [1, 2, 3], 'round index is 1-based and assistant-only')
assert.deepEqual(
  anchors.map((a) => a.key),
  ['a1', 'a2', 'a3'],
  'anchors reuse the round key from collectTrajectoryRounds',
)
assert.equal(anchors[1].createdAt, undefined, 'missing created_at stays undefined (no fabrication)')
assert.deepEqual(
  collectTrajectoryAnchors([]),
  [],
  'empty session yields no anchor',
)
assert.deepEqual(collectTrajectoryAnchors(undefined), [], 'undefined messages are tolerated')
assert.equal(
  collectTrajectoryRounds(messages).length,
  anchors.length,
  'anchor count can never drift from the rendered rows (R-1)',
)

// ---- T009/T010: step extraction --------------------------------------------

function source(overrides: Partial<ReplayStepSource>): ReplayStepSource {
  return {
    id: 'step-1',
    kind: 'tool',
    status: 'completed',
    startedAt: 1_000,
    updatedAt: 3_500,
    payload: {},
    ...overrides,
  }
}

const order = ['step-1', 'step-2', 'step-3']
const items: Record<string, ReplayStepSource> = {
  'step-1': source({ payload: { args: { q: 'hello' }, result: 'world' } }),
  'step-2': source({
    id: 'step-2',
    kind: 'evidence',
    startedAt: 4_000,
    updatedAt: 4_000,
    payload: { sources: [{ title: 'Doc A' }, { citation_id: 'doc:1' }] },
  }),
  'step-3': source({
    id: 'step-3',
    kind: 'final_answer',
    status: 'running',
    startedAt: 5_000,
    updatedAt: 5_000,
    payload: { text: 'final text' },
  }),
}

const steps = extractReplaySteps(order, items, 9_000)
assert.equal(steps.length, 3, 'every ordered item becomes a step')
assert.equal(steps[0].durationMs, 2_500, 'finished step uses updatedAt - startedAt')
assert.equal(steps[2].running, true, 'status running is surfaced')
assert.equal(steps[2].durationMs, 4_000, 'running step ticks against `now` (FR-005)')

// Missing item in order must not throw — R-16 keeps the list resilient.
assert.deepEqual(extractReplaySteps(['ghost'], items, 1), [], 'unknown ids are skipped')
assert.deepEqual(extractReplaySteps(undefined, items, 1), [], 'missing order yields no steps')
assert.deepEqual(extractReplaySteps(order, undefined, 1), [], 'missing items yields no steps')

// tool: input from args, output from result
assert.equal(stepInputText(items['step-1']), JSON.stringify({ q: 'hello' }, null, 2))
assert.equal(stepOutputText(items['step-1']), 'world')
assert.equal(stepLabel(steps[0]), 'tool', 'falls back to kind when payload has no name')

// evidence: output comes from source titles, never from an inferred summary (R-2)
assert.equal(stepOutputText(items['step-2']), 'Doc A\ndoc:1')

// final answer: output from payload.text, input stays empty
assert.equal(stepOutputText(items['step-3']), 'final text')
assert.equal(stepInputText(items['step-3']), '')

// ---- T010: cost must never be fabricated ------------------------------------

assert.equal(readCostUsd(undefined), null, 'no payload → no cost')
assert.equal(readCostUsd({}), null, 'absent key → no cost')
assert.equal(readCostUsd({ cost_usd: null }), null, 'null → no cost')
assert.equal(readCostUsd({ cost_usd: '0.01' }), null, 'string is not a measured cost (R-07)')
assert.equal(readCostUsd({ cost_usd: Number.NaN }), null, 'NaN → no cost')
assert.equal(readCostUsd({ cost_usd: 0.0123 }), 0.0123, 'numeric snake_case is honoured')
assert.equal(readCostUsd({ costUsd: 0 }), 0, 'a real zero is a real value')
assert.equal(
  steps[0].costUsd,
  null,
  'steps without a cost payload expose null so the row is hidden',
)

// ---- duration formatting is reused, not re-implemented (R-3) ----------------

assert.equal(elapsedRunMs(null, null, 5_000), null, 'no start → no duration')
assert.equal(formatRunDuration(2_500, 'zh'), '2秒')
assert.equal(formatRunDuration(2_500, 'en'), '2s')
assert.equal(formatRunDuration(null, 'zh'), '')

// ---- drill-ability guard ---------------------------------------------------

assert.equal(
  isDrillableEvent({ v: 3, event_id: 'e', ts: 0, type: 'item.completed', item_id: 'x', item_kind: 'tool', revision: 1, payload: {} } as any),
  true,
)
assert.equal(
  isDrillableEvent({ v: 3, event_id: 'e', ts: 0, type: 'run.started', revision: 1, payload: {} } as any),
  false,
)

console.log('session-replay: all assertions passed')
