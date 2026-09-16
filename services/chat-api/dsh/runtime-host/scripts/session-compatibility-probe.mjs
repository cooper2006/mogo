import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

import { KernelRuntime } from '../src/kernel-runtime.mjs'

const HISTORY_MARKER = 'DSH_UPGRADE_HISTORY_MARKER'
const CONTINUATION_MARKER = 'DSH_UPGRADE_CONTINUATION_MARKER'
const TEMPORAL_CONTEXT = Object.freeze({
  captured_at_utc: '2026-09-16T00:00:00Z',
  user_local_time: '2026-09-16T08:00:00+08:00',
  user_timezone: 'Asia/Shanghai',
})

function send(runtime, sessionId, text) {
  runtime.send({
    sessionId,
    mode: 'prompt',
    content: [{ type: 'text', data: { text } }],
    temporalContext: TEMPORAL_CONTEXT,
  })
}

async function waitForTurn(runtime, sessionId, previousTurns) {
  const deadline = Date.now() + 10_000
  while (Date.now() < deadline) {
    const turns = runtime.events(sessionId, -1).filter(event => event.nativeType === 'turn/end').length
    if (turns > previousTurns) return
    await new Promise(resolve => setTimeout(resolve, 20))
  }
  throw new Error('compatibility probe turn did not finish')
}

function options(argv) {
  const parsed = {}
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index]
    const value = argv[index + 1]
    if (!key?.startsWith('--') || value === undefined) throw new Error(`invalid argument: ${key ?? ''}`)
    parsed[key.slice(2)] = value
  }
  for (const required of ['mode', 'storage-root', 'session-id', 'isolation-key']) {
    if (!parsed[required]) throw new Error(`--${required} is required`)
  }
  if (!['create', 'resume'].includes(parsed.mode)) throw new Error('--mode must be create or resume')
  return parsed
}

const args = options(process.argv.slice(2))
const storageRoot = resolve(args['storage-root'])
await mkdir(storageRoot, { recursive: true })
const runtime = new KernelRuntime({
  runtimeId: `upgrade-probe-${args.mode}`,
  isolationKey: args['isolation-key'],
  profileVersion: 'upgrade-probe-v1',
  storageRoot,
})

try {
  await runtime.start()
  const session = args.mode === 'create'
    ? await runtime.createSession({
        sessionId: args['session-id'],
        presetId: args['preset-id'] ?? 'code',
        cwd: storageRoot,
      })
    : await runtime.resumeSession(args['session-id'])
  const priorEvents = runtime.events(args['session-id'], -1)
  const historyPreserved = args.mode === 'create'
    || priorEvents.some(event => JSON.stringify(event.data).includes(HISTORY_MARKER))
  const previousTurns = priorEvents.filter(event => event.nativeType === 'turn/end').length
  send(runtime, args['session-id'], args.mode === 'create' ? HISTORY_MARKER : CONTINUATION_MARKER)
  await waitForTurn(runtime, args['session-id'], previousTurns)
  const marker = args.mode === 'create' ? HISTORY_MARKER : CONTINUATION_MARKER
  const continuationCompleted = runtime.events(args['session-id'], -1)
    .some(event => JSON.stringify(event.data).includes(marker))
  process.stdout.write(`${JSON.stringify({
    ok: true, mode: args.mode, session, historyPreserved, continuationCompleted,
  })}\n`)
} finally {
  await runtime.dispose()
}
