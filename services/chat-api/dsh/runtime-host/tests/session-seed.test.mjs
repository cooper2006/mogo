import assert from 'node:assert/strict'
import test from 'node:test'

import { resolveSessionSeed, sealSeed, seedMac } from '../src/session-seed.mjs'

const TOKEN = 'a'.repeat(40)

test('ordinary Session creation remains unchanged', async () => {
  const manager = { exportCompletedSeed: async () => assert.fail('must not export a seed') }
  assert.deepEqual(
    await resolveSessionSeed(manager, { sessionId: 'next', presetId: 'askai-enterprise' }),
    { sessionId: 'next', presetId: 'askai-enterprise' },
  )
})

test('predecessor identity becomes a native DSH seed without exposing raw events', async () => {
  const calls = []
  const events = [{ type: 'message', data: { role: 'user', content: 'prior context' } }]
  const manager = {
    exportCompletedSeed: async (runtimeId, sessionId) => {
      calls.push([runtimeId, sessionId])
      return events
    },
  }
  const resolved = await resolveSessionSeed(manager, {
    sessionId: 'next',
    seedRuntimeId: 'runtime-old',
    seedSessionId: 'session-old',
  })
  assert.deepEqual(calls, [['runtime-old', 'session-old']])
  assert.deepEqual(resolved, {
    sessionId: 'next',
    seed: events,
    parentSessionId: 'session-old',
  })
})

test('a sealed cross-replica seed is accepted when the MAC matches', async () => {
  const events = [{ type: 'message', data: { role: 'user', content: 'prior context' } }]
  const manager = { exportCompletedSeed: async () => assert.fail('must stay remote') }
  const body = sealSeed(TOKEN, 'instance-b', 'session-old', events)
  const resolved = await resolveSessionSeed(manager, { sessionId: 'next', ...body }, { authToken: TOKEN })
  assert.deepEqual(resolved.seed, events)
  assert.equal(resolved.parentSessionId, 'session-old')
  assert.ok(!('seedSignature' in resolved))
  assert.ok(!('seedSourceInstanceId' in resolved))
})

test('a sealed seed signed with a different token is rejected', async () => {
  const events = [{ type: 'message', data: { role: 'user', content: 'prior context' } }]
  const manager = { exportCompletedSeed: async () => [] }
  const body = sealSeed('b'.repeat(40), 'instance-b', 'session-old', events)
  await assert.rejects(
    () => resolveSessionSeed(manager, { sessionId: 'next', ...body }, { authToken: TOKEN }),
    /seedSignature does not match/,
  )
})

test('a tampered sealed seed is rejected even with a valid signature shape', async () => {
  const events = [{ type: 'message', data: { role: 'user', content: 'prior context' } }]
  const manager = { exportCompletedSeed: async () => [] }
  const body = sealSeed(TOKEN, 'instance-b', 'session-old', events)
  body.seed.push({ type: 'system', data: { role: 'user', content: 'injected' } })
  await assert.rejects(
    () => resolveSessionSeed(manager, { sessionId: 'next', ...body }, { authToken: TOKEN }),
    /seedSignature does not match/,
  )
})

test('raw seed fields without a signature are rejected', async () => {
  const manager = { exportCompletedSeed: async () => [] }
  await assert.rejects(
    () => resolveSessionSeed(manager, { sessionId: 'next', seed: [] }, { authToken: TOKEN }),
    /seedSignature requires a Runtime Host authentication token/,
  )
})

test('seed events must be plain objects with a string type', async () => {
  const manager = { exportCompletedSeed: async () => [] }
  const bad = sealSeed(TOKEN, 'instance-b', 'session-old', [
    { type: 'message' },
    { payload: 'no type' },
  ])
  await assert.rejects(
    () => resolveSessionSeed(manager, { sessionId: 'next', ...bad }, { authToken: TOKEN }),
    /seed events must/,
  )
})

test('incomplete local predecessor identity is still rejected', async () => {
  const manager = { exportCompletedSeed: async () => [] }
  await assert.rejects(() => resolveSessionSeed(manager, { seedRuntimeId: 'runtime-old' }), /supplied together/)
  await assert.rejects(() => resolveSessionSeed(manager, { seedSessionId: 'session-old' }), /supplied together/)
})

test('sealSeed binds the seed to the pool token and source instance', () => {
  const events = [{ type: 'message', data: { role: 'user', content: 'x' } }]
  const a = sealSeed(TOKEN, 'instance-a', 'session-x', events)
  const b = sealSeed(TOKEN, 'instance-b', 'session-x', events)
  assert.notEqual(a.seedSignature, b.seedSignature)
  assert.equal(seedMac(TOKEN, 'instance-a', 'session-x', events), a.seedSignature)
})
