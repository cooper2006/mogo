import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'
import { collectTrajectoryRounds } from '../src/features/execution-v3/domain/trajectoryRounds'

// 028 — session-level "conversation / trajectory" tabs (route C).
// The aggregation is unit-tested for real; the runtime store and App wiring are
// contract-tested on source text, matching the established pattern for
// composables that pull in axios (see chat-cancellation-contract.test.ts).

const root = process.cwd()
const runtime = readFileSync(resolve(root, 'src/composables/useChatRuntimeStore.ts'), 'utf8')
const app = readFileSync(resolve(root, 'src/App.vue'), 'utf8')
const tabs = readFileSync(resolve(root, 'src/components/chat/ChatViewTabs.vue'), 'utf8')
const trajectory = readFileSync(resolve(root, 'src/features/execution-v3/components/SessionTrajectoryView.vue'), 'utf8')
const localeMessages = readFileSync(resolve(root, 'src/locales/messages.ts'), 'utf8')

// ---- pure aggregation: only assistant messages become rounds ----
test('only assistant messages become trajectory rounds', () => {
  const messages = [
    { _id: 'u1', role: 'user' },
    { _id: 'a1', role: 'assistant' },
    { _id: 'u2', role: 'user' },
    { _id: 'a2', role: 'assistant' },
    { _id: 'a3', role: 'assistant' },
  ]
  const rounds = collectTrajectoryRounds(messages)
  assert.equal(rounds.length, 3, 'non-assistant messages are skipped')
  assert.deepEqual(rounds.map((round) => round.index), [1, 2, 3])
  assert.deepEqual(rounds.map((round) => round.key), ['a1', 'a2', 'a3'])
  assert.equal(rounds[0].message._id, 'a1', 'the round keeps its source message')
})

test('empty or missing input never throws', () => {
  assert.deepEqual(collectTrajectoryRounds(undefined), [])
  assert.deepEqual(collectTrajectoryRounds([]), [])
  assert.equal(collectTrajectoryRounds([{ role: 'user' }]).length, 0)
})

test('rounds without an id get a stable positional key', () => {
  const rounds = collectTrajectoryRounds([{ role: 'assistant' }, { role: 'assistant' }])
  assert.deepEqual(rounds.map((round) => round.key), ['trajectory_round_1', 'trajectory_round_2'])
})

// ---- contract: the pane owns its tab, not global state ----
test('runtime store owns the per-pane view tab', () => {
  assert.match(runtime, /activeView: 'chat' \| 'trajectory'/, 'the pane must carry the view tab')
  assert.match(
    runtime,
    /function setPaneView\(key: string, view: 'chat' \| 'trajectory'\)/,
    'a per-pane setter must exist',
  )
  assert.match(runtime, /setPaneView,/, 'the setter must be exported')
  assert.match(runtime, /activeView: 'chat',/, 'a new pane must default to the conversation tab')
})

// ---- contract: App mounts the switcher and keeps ChatWindow mounted ----
test('App mounts the tab switcher for both views', () => {
  assert.match(app, /<ChatViewTabs/, 'the tab switcher must be mounted per pane')
  assert.match(app, /chatRuntime\.setPaneView\(pane\.key, view\)/, 'the switcher must drive pane state')
  assert.match(app, /<SessionTrajectoryView/, 'the trajectory view must be mounted')
  assert.match(app, /v-show="pane\.activeView !== 'trajectory'"/, 'the conversation view toggles by pane state')
  assert.match(app, /v-show="pane\.activeView === 'trajectory'"/, 'the trajectory view toggles by pane state')
  assert.doesNotMatch(app, /v-if="pane\.activeView/, 'views must toggle with v-show, never v-if (FR-007)')

  // Regression guard (found by the 2026-10-15 visual check): `v-show` placed on
  // an async component (defineAsyncComponent) is silently dropped once the
  // component resolves, because the async placeholder vnode gets replaced and the
  // directive lives on the outer vnode. The views then never hide. Both
  // components must therefore be wrapped in a plain div that carries the v-show.
  const chatWindowBlock = app.slice(app.indexOf('<ChatWindow'), app.indexOf('/>', app.indexOf('<ChatWindow')) + 2)
  const trajectoryBlock = app.slice(
    app.indexOf('<SessionTrajectoryView'),
    app.indexOf('/>', app.indexOf('<SessionTrajectoryView')) + 2,
  )
  assert.doesNotMatch(chatWindowBlock, /v-show=/, 'v-show must not sit on the async ChatWindow component')
  assert.doesNotMatch(trajectoryBlock, /v-show=/, 'v-show must not sit on the async trajectory component')
  assert.match(app, /<div v-show="pane\.activeView !== 'trajectory'"/, 'a plain wrapper div must carry the v-show')
})

// ---- contract: the trajectory view reuses the shared store, read-only ----
test('trajectory view reuses the execution store without approvals', () => {
  assert.match(trajectory, /collectTrajectoryRounds\(props\.messages\)/, 'rounds come from the pure domain helper')
  assert.match(trajectory, /ensureMessageExecutionV3\(/, 'each round reuses ChatWindow\'s execution store')
  assert.match(trajectory, /<ExecutionViewV3 /, 'stage 1 renders the existing per-message timeline')
  assert.doesNotMatch(trajectory, /resolve-permission/, 'approval stays in the conversation tab')
})

// ---- contract: the switcher is a controlled, accessible component ----
test('tab switcher emits the selected view', () => {
  assert.match(tabs, /'update:view'/, 'the switcher must emit the new view')
  assert.match(tabs, /role="tablist"/, 'the switcher must expose a tablist role')
  assert.match(tabs, /:aria-selected=/, 'each tab must expose its selected state')
})

// ---- contract: bilingual copy ----
test('trajectory copy exists in both locales', () => {
  assert.match(localeMessages, /'chat\.view\.chat': \{ zh: '对话', en: 'Chat' \}/)
  assert.match(localeMessages, /'chat\.view\.trajectory': \{ zh: '轨迹', en: 'Trajectory' \}/)
})
