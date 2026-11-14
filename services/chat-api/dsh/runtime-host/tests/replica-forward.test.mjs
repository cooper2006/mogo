import { strict as assert } from 'node:assert'
import test from 'node:test'

import {
  HOP_HEADER,
  MAX_HOPS,
  findOwner,
  findOwnerByIsolation,
  forwardRequest,
  parsePeers,
  shouldForward,
} from '../src/replica-forward.mjs'

test('parsePeers splits, trims and drops the replica itself', () => {
  const peers = parsePeers(
    ' http://dsh-runtime-host-1:8101 , http://dsh-runtime-host-2:8101 ,, http://dsh-runtime-host-3:8101/ ',
    'http://dsh-runtime-host-2:8101',
  )
  assert.deepEqual(peers, [
    'http://dsh-runtime-host-1:8101',
    'http://dsh-runtime-host-3:8101',
  ])
  assert.deepEqual(parsePeers('', 'http://x'), [])
  assert.deepEqual(parsePeers(undefined, 'http://x'), [])
})

test('shouldForward only hands off runtime-scoped paths under the hop limit', () => {
  const req = (hops) => ({ headers: hops === undefined ? {} : { [HOP_HEADER]: String(hops) } })
  // Runtime-scoped: forwarded when no hop budget has been consumed.
  assert.equal(shouldForward({ request: req(), selfUrl: '', path: '/v1/runtimes/abc/sessions' }), true)
  assert.equal(shouldForward({ request: req(0), selfUrl: '', path: '/v1/runtimes' }), true)
  assert.equal(shouldForward({ request: req(1), selfUrl: '', path: '/v1/runtimes/abc' }), true)
  // At the limit: do not forward again.
  assert.equal(shouldForward({ request: req(MAX_HOPS), selfUrl: '', path: '/v1/runtimes/abc' }), false)
  // Never forwarded: health, drain and non-runtime paths.
  assert.equal(shouldForward({ request: req(), selfUrl: '', path: '/health' }), false)
  assert.equal(shouldForward({ request: req(), selfUrl: '', path: '/drain' }), false)
  assert.equal(shouldForward({ request: req(), selfUrl: '', path: '/v1/other' }), false)
})

test('findOwner returns the peer whose holds probe reports the runtime', async () => {
  const original = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url) => {
    calls.push(url)
    if (url.startsWith('http://peer-1')) {
      return new Response(JSON.stringify({ holds: false, instanceId: 'host-1' }), { status: 200 })
    }
    return new Response(JSON.stringify({ holds: true, instanceId: 'host-2' }), { status: 200 })
  }
  try {
    const owner = await findOwner({
      peers: ['http://peer-1', 'http://peer-2'],
      runtimeId: 'rt-1',
      authorization: 'Bearer t',
      instanceId: 'host-0',
      selfUrl: '',
    })
    assert.ok(owner)
    assert.equal(owner.instanceId, 'host-2')
    assert.equal(owner.url, 'http://peer-2')
    assert.equal(calls.length, 2)
  } finally {
    globalThis.fetch = original
  }
})

test('findOwner skips unreachable peers and returns null when nobody holds it', async () => {
  const original = globalThis.fetch
  globalThis.fetch = async (url) => {
    if (url.startsWith('http://down')) throw new Error('ECONNREFUSED')
    return new Response(JSON.stringify({ holds: false, instanceId: 'host-2' }), { status: 200 })
  }
  try {
    const owner = await findOwner({
      peers: ['http://down', 'http://peer-2'],
      runtimeId: 'rt-1',
      authorization: 'Bearer t',
      instanceId: 'host-0',
      selfUrl: '',
    })
    assert.equal(owner, null)
  } finally {
    globalThis.fetch = original
  }
})

test('findOwnerByIsolation locates the peer and reports its runtime id', async () => {
  const original = globalThis.fetch
  globalThis.fetch = async (url) => {
    if (url.includes('isolationKey=key-7')) {
      return new Response(JSON.stringify({ runtime: { runtimeId: 'rt-remote' } }), { status: 200 })
    }
    return new Response(JSON.stringify({ runtime: null }), { status: 200 })
  }
  try {
    const owner = await findOwnerByIsolation({
      peers: ['http://peer-1', 'http://peer-2'],
      isolationKey: 'key-7',
      authorization: 'Bearer t',
      instanceId: 'host-0',
      selfUrl: '',
    })
    assert.ok(owner)
    assert.equal(owner.runtimeId, 'rt-remote')
  } finally {
    globalThis.fetch = original
  }
})

test('findOwner never asks the replica itself', async () => {
  const original = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url) => {
    calls.push(url)
    return new Response(JSON.stringify({ holds: false }), { status: 200 })
  }
  try {
    await findOwner({
      peers: ['http://self', 'http://peer-2'],
      runtimeId: 'rt-1',
      authorization: 'Bearer t',
      instanceId: 'host-0',
      selfUrl: 'http://self',
    })
    assert.ok(calls.every(url => !url.startsWith('http://self')), `asked itself: ${calls}`)
  } finally {
    globalThis.fetch = original
  }
})

test('forwardRequest relays the peer status and body verbatim', async () => {
  const original = globalThis.fetch
  let seen
  globalThis.fetch = async (url, init) => {
    seen = { url, init }
    return new Response(JSON.stringify({ ok: true, echoed: true }), { status: 201 })
  }
  try {
    const result = await forwardRequest({
      targetUrl: 'http://peer-2:8101',
      request: {
        method: 'POST',
        headers: { authorization: 'Bearer t', 'content-type': 'application/json', 'x-isolation-key': 'iso-1' },
      },
      path: '/v1/runtimes/rt-1/sessions',
      search: '?a=1',
      hops: 0,
      body: Buffer.from(JSON.stringify({ sessionId: 's' })),
    })
    assert.equal(result.forwarded, true)
    assert.equal(result.status, 201)
    assert.deepEqual(result.body, { ok: true, echoed: true })
    assert.equal(seen.url, 'http://peer-2:8101/v1/runtimes/rt-1/sessions?a=1')
    assert.equal(seen.init.method, 'POST')
    // Hop counter increments so a chain cannot loop forever.
    assert.equal(seen.init.headers[HOP_HEADER], '1')
    // The routing identity is preserved for the receiving replica.
    assert.equal(seen.init.headers['x-isolation-key'], 'iso-1')
    assert.equal(seen.init.body.toString(), JSON.stringify({ sessionId: 's' }))
  } finally {
    globalThis.fetch = original
  }
})

test('forwardRequest refuses to forward once the hop budget is spent', async () => {
  const original = globalThis.fetch
  let called = false
  globalThis.fetch = async () => { called = true; return new Response('{}', { status: 200 }) }
  try {
    const result = await forwardRequest({
      targetUrl: 'http://peer-2:8101',
      request: { method: 'GET', headers: { authorization: 'Bearer t' } },
      path: '/v1/runtimes/rt-1',
      search: '',
      hops: MAX_HOPS,
    })
    assert.equal(result.forwarded, false)
    assert.equal(result.status, 508)
    assert.equal(result.body.error.code, 'forward_loop_detected')
    assert.equal(called, false, 'must not reach the network once hops are exhausted')
  } finally {
    globalThis.fetch = original
  }
})

test('forwardRequest reports a transport failure instead of throwing', async () => {
  const original = globalThis.fetch
  globalThis.fetch = async () => { throw new Error('ECONNREFUSED') }
  try {
    const result = await forwardRequest({
      targetUrl: 'http://down:8101',
      request: { method: 'GET', headers: { authorization: 'Bearer t' } },
      path: '/v1/runtimes/rt-1',
      search: '',
      hops: 0,
    })
    assert.equal(result.forwarded, false)
    assert.equal(result.status, 502)
    assert.equal(result.body.error.code, 'forward_failed')
  } finally {
    globalThis.fetch = original
  }
})
