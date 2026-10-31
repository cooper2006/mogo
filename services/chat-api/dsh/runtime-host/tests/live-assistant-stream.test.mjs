import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import { EventJournal } from '../src/event-journal.mjs'
import { KernelRuntime } from '../src/kernel-runtime.mjs'
import { LiveAssistantStream } from '../src/official-host/live-assistant-stream.mjs'
import { modelProfile, sendText, waitFor, withModelServer } from './support/runtime-admission.mjs'

const session = { id: 'session-a' }

function settledEvent() {
  return {
    type: 'assistant/message',
    seq: 7,
    data: {
      turn: 1,
      step: 2,
      message: { role: 'assistant', content: [{ type: 'text', text: 'hello' }] },
      stream: [{ type: 'text-chunks', index: 0, texts: ['hello'] }],
    },
  }
}

test('live chunks arrive before settlement and are not replayed twice', () => {
  const journal = new EventJournal()
  const bridge = new LiveAssistantStream(journal)
  bridge.observeFrame(session.id, { type: 'start', attemptId: 'attempt-a', revision: 1, turn: 1, step: 2 })
  bridge.observeFrame(session.id, {
    type: 'chunk', attemptId: 'attempt-a', revision: 2, index: 0, time: 100,
    chunk: { type: 'text-delta', index: 0, text: 'hello' },
  })
  assert.deepEqual(journal.replay(session.id).map(event => event.nativeType), ['assistant/chunk'])
  assert.deepEqual(journal.replay(session.id)[0].data.live, {
    attemptId: 'attempt-a', revision: 2, index: 0, time: 100,
  })

  bridge.observeSessionEvent(session, settledEvent())
  bridge.observeFrame(session.id, {
    type: 'end', attemptId: 'attempt-a', revision: 3, index: 1,
    outcome: { kind: 'committed', eventType: 'assistant/message', seq: 7 },
  })
  assert.deepEqual(journal.replay(session.id).map(event => event.nativeType), [
    'assistant/chunk', 'assistant/message',
  ])
})

test('settled events without an active live attempt still expand for replay compatibility', () => {
  const journal = new EventJournal()
  const bridge = new LiveAssistantStream(journal)
  bridge.observeSessionEvent(session, settledEvent())
  assert.deepEqual(journal.replay(session.id).map(event => event.nativeType), [
    'assistant/chunk', 'assistant/message',
  ])
})

test('KernelRuntime receives actual DSH live frames before its durable assistant message', async () => {
  const root = await mkdtemp(join(tmpdir(), 'mogo-live-assistant-stream-'))
  const runtime = new KernelRuntime({
    runtimeId: 'live-stream-test', isolationKey: 'live-stream-test',
    profileVersion: 'test-v1', storageRoot: root,
  })
  try {
    await runtime.start()
    await runtime.createSession({ sessionId: 'live-test' })
    sendText(runtime, 'live-test', 'show live text')
    await waitFor(
      () => runtime.events('live-test', -1).some(event => event.nativeType === 'turn/end'),
      'DSH did not finish the turn',
    )
    const events = runtime.events('live-test', -1)
    const liveText = events.filter(event => event.nativeType === 'assistant/chunk'
      && event.data.chunk?.type === 'text-delta')
    const message = events.find(event => event.nativeType === 'assistant/message')
    assert.equal(liveText.length, 1)
    assert.ok(liveText[0].data.live.attemptId)
    assert.ok(liveText[0].cursor < message.cursor)
    assert.equal(liveText[0].data.chunk.text, message.data.message.content[0].text)
  } finally {
    await runtime.dispose()
    await rm(root, { recursive: true, force: true })
  }
})

test('a model gateway text chunk reaches MOGO while the provider response is still open', async () => {
  const root = await mkdtemp(join(tmpdir(), 'mogo-live-gateway-stream-'))
  let providerFinished = false
  try {
    await withModelServer((_request, response) => {
      response.writeHead(200, { 'content-type': 'application/x-ndjson' })
      response.write(`${JSON.stringify({ type: 'text-delta', text: 'first ' })}\n`)
      setTimeout(() => {
        response.write(`${JSON.stringify({ type: 'text-delta', text: 'second' })}\n`)
        response.end(`${JSON.stringify({ type: 'finish', reason: { kind: 'stop' } })}\n`)
        providerFinished = true
      }, 500)
    }, async baseUrl => {
      const runtime = new KernelRuntime({
        runtimeId: 'live-gateway-test', isolationKey: 'live-gateway-test',
        profileVersion: 'test-v1', storageRoot: root,
        modelProfile: modelProfile(baseUrl),
      })
      try {
        await runtime.start()
        await runtime.createSession({ sessionId: 'gateway-live-test' })
        sendText(runtime, 'gateway-live-test', 'stream two pieces')
        await waitFor(
          () => runtime.events('gateway-live-test', -1).some(event =>
            event.nativeType === 'assistant/chunk' && event.data.chunk?.text === 'first '),
          'first live chunk did not arrive',
        )
        assert.equal(providerFinished, false)
        assert.equal(runtime.events('gateway-live-test', -1).some(event =>
          event.nativeType === 'assistant/message'), false)
        await waitFor(
          () => runtime.events('gateway-live-test', -1).some(event => event.nativeType === 'turn/end'),
          'streaming turn did not finish',
        )
        const events = runtime.events('gateway-live-test', -1)
        assert.deepEqual(events.filter(event => event.nativeType === 'assistant/chunk'
          && event.data.chunk?.type === 'text-delta').map(event => event.data.chunk.text),
        ['first ', 'second'])
      } finally {
        await runtime.dispose()
      }
    })
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})
