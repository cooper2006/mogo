import assert from 'node:assert/strict'
import test from 'node:test'

import { compatibleSessionEvents } from '../src/official-host/event-compat.mjs'
import { stableModelRequest } from '../src/official-host/model-request-compat.mjs'

test('V3 compact assistant streams retain MOVO text deltas and completion', () => {
  const completed = {
    type: 'assistant/message',
    seq: 12,
    data: {
      turn: 2,
      step: 3,
      message: { role: 'assistant', content: [{ type: 'text', text: 'hello world' }] },
      stream: [
        { type: 'chunk', chunk: { type: 'block-start', index: 0, blockType: 'text' } },
        { type: 'text-chunks', index: 0, texts: ['hello ', 'world'] },
        { type: 'chunk', chunk: { type: 'finish', reason: { kind: 'stop' } } },
      ],
    },
  }

  const events = compatibleSessionEvents(completed)
  assert.deepEqual(
    events.filter(event => event.type === 'assistant/chunk').map(event => event.data.chunk.type),
    ['block-start', 'text-delta', 'text-delta', 'finish'],
  )
  assert.deepEqual(
    events.filter(event => event.data?.chunk?.type === 'text-delta').map(event => event.data.chunk.text),
    ['hello ', 'world'],
  )
  assert.equal(events.at(-1), completed)
})

test('V3 failed assistant attempts retain MOVO model failure events', () => {
  const failed = {
    type: 'assistant/attempt',
    data: {
      turn: 1,
      step: 2,
      stream: [{
        type: 'chunk',
        chunk: {
          type: 'finish',
          reason: { kind: 'error', failure: { code: 'MODEL_AUTHENTICATION_FAILED' } },
        },
      }],
    },
  }
  const events = compatibleSessionEvents(failed)
  assert.equal(events[0].type, 'assistant/chunk')
  assert.equal(events[0].data.chunk.reason.failure.code, 'MODEL_AUTHENTICATION_FAILED')
  assert.equal(events.at(-1), failed)
})

test('V3 in-history system nodes keep the MOVO Model Gateway envelope stable', () => {
  const user = { role: 'user', content: [{ type: 'text', text: 'question' }] }
  const request = stableModelRequest({
    messages: [
      { role: 'system', content: [{ type: 'text', text: 'older' }] },
      user,
      { role: 'system', content: [{ type: 'text', text: 'current policy' }] },
    ],
  })

  assert.equal(request.system, 'current policy')
  assert.deepEqual(request.messages, [user])
})

test('an explicit DSH system option remains authoritative', () => {
  const messages = [{ role: 'user', content: [] }]
  assert.deepEqual(stableModelRequest({ system: 'explicit', messages }), {
    system: 'explicit',
    messages,
  })
})
