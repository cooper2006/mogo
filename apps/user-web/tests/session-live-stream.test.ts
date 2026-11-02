import assert from 'node:assert/strict'

Object.defineProperty(globalThis, 'navigator', {
  configurable: true,
  value: { language: 'zh-CN', languages: ['zh-CN'] },
})
;(globalThis as any).localStorage = {
  getItem: () => null, setItem: () => undefined, removeItem: () => undefined,
}

const { startSessionLiveStream } = await import('../src/composables/useSessionLiveStream')

const encoder = new TextEncoder()
const streamOf = (text: string): ReadableStream<Uint8Array> => {
  let sent = false
  return new ReadableStream({
    pull(controller) {
      if (sent) { controller.close(); return }
      sent = true
      controller.enqueue(encoder.encode(text))
    },
  })
}

const frame = (name: string, id: string | null, data: string) =>
  `${name ? `event: ${name}\n` : ''}${id ? `id: ${id}\n` : ''}data: ${data}\n\n`

const seen: string[] = []
const malformed: string[] = []
const threadChanged: any[] = []
const accessLost: any[] = []
const members: string[] = []

let signalLastFrame: () => void = () => undefined
const lastFrameSeen = new Promise<void>((resolve) => { signalLastFrame = resolve })

const body = [
  ':heartbeat\n\n',
  frame('turn.started', '1', JSON.stringify({ session_id: 's1', revision: 'r1', run_id: 'run1', message_id: 'm1', initiator_user_id: 'u1', status: 'running' })),
  frame('execution', '2', JSON.stringify({ session_id: 's1', message_id: 'm1', event_id: 'e1', stream_seq: 7, event: { v: 3, type: 'assistant.text.delta', event_id: 'e1' } })),
  frame('execution', '3', JSON.stringify({ session_id: 's1', message_id: 'm1', event_id: 'e2', stream_seq: 8, event: { v: 2, type: 'legacy' } })),
  frame('turn.completed', '4', JSON.stringify({ session_id: 's1', message_id: 'm1', run_id: 'run1', status: 'completed', revision: 'r2' })),
  frame('members.changed', '5', JSON.stringify({ session_id: 's1', revision: 'r3' })),
].join('')

const handle = startSessionLiveStream({
  sessionId: 's1',
  paneKey: 'pane-a',
  authToken: 'token',
  fetchImpl: (async () => new Response(streamOf(body), { status: 200 })) as any,
  sleep: async () => undefined,
  onTurnStarted: (event) => seen.push(`started:${event.message_id}`),
  onExecution: (event) => seen.push(`exec:${event.stream_seq}`),
  onTurnCompleted: (event) => seen.push(`completed:${event.status}`),
  onMembersChanged: (paneKey) => { members.push(paneKey); signalLastFrame() },
  onThreadChanged: (event) => threadChanged.push(event),
  onAccessLost: (paneKey, reason) => accessLost.push({ paneKey, reason }),
  onMalformedFrame: (raw) => malformed.push(raw),
})

await lastFrameSeen
handle.stop()
await handle.done

assert.deepEqual(seen, ['started:m1', 'exec:7', 'completed:completed'])
assert.deepEqual(members, ['pane-a'])
assert.equal(handle.cursor(), '4')
assert.equal(malformed.length, 1, `expected the V2 execution event to be malformed, got ${JSON.stringify(malformed)}`)
assert.match(malformed[0], /"stream_seq":8/)

// Control frames end the response; the caller reopens from an authoritative cursor.
const controlBody = frame('thread.changed', '9', JSON.stringify({ session_id: 's1', revision: 'r9', last_message_seq: 42, reason: 'cursor_gap' }))
const controlHandle = startSessionLiveStream({
  sessionId: 's1',
  paneKey: 'pane-b',
  authToken: 'token',
  fetchImpl: (async () => new Response(streamOf(controlBody), { status: 200 })) as any,
  sleep: async () => undefined,
  onThreadChanged: (event) => { threadChanged.push(event); signalLastFrame() },
})
await lastFrameSeen
controlHandle.stop()
await controlHandle.done
assert.deepEqual(threadChanged, [{ session_id: 's1', revision: 'r9', last_message_seq: 42, reason: 'cursor_gap' }])

// Revocation is terminal: cursor cleared, never reconnects.
const revokedBody = frame('session.access.revoked', '10', JSON.stringify({ session_id: 's1', reason: 'participant_removed' }))
let revokedFetches = 0
const revokedHandle = startSessionLiveStream({
  sessionId: 's1',
  paneKey: 'pane-c',
  authToken: 'token',
  fetchImpl: (async () => { revokedFetches += 1; return new Response(streamOf(revokedBody), { status: 200 }) }) as any,
  sleep: async () => undefined,
  onAccessLost: (paneKey, reason) => accessLost.push({ paneKey, reason }),
})
await revokedHandle.done
assert.deepEqual(accessLost, [{ paneKey: 'pane-c', reason: 'participant_removed' }])
assert.equal(revokedHandle.cursor(), null)
assert.equal(revokedFetches, 1)

// Non-retryable HTTP status surfaces once and stops.
const errors: number[] = []
const httpHandle = startSessionLiveStream({
  sessionId: 's1',
  paneKey: 'pane-d',
  fetchImpl: (async () => new Response('nope', { status: 403 })) as any,
  sleep: async () => undefined,
  onError: (error) => errors.push(error.status),
})
await httpHandle.done
assert.deepEqual(errors, [403])

console.log('session live stream smoke passed')
