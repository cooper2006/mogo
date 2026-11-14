import { strict as assert } from 'node:assert'
import { once } from 'node:events'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import { RuntimeHttpServer } from '../src/runtime-http-server.mjs'
import { HOP_HEADER } from '../src/replica-forward.mjs'

const TOKEN = 'test-token-that-is-long-enough-0123456789'

async function withServer(options, fn) {
  const storageRoot = await mkdtemp(join(tmpdir(), 'dsh-forward-'))
  const server = new RuntimeHttpServer({
    host: '127.0.0.1',
    port: 0,
    storageRoot,
    authToken: TOKEN,
    instanceId: 'host-local',
    peers: '',
    ...options,
  })
  const address = await server.start()
  try {
    await fn(`http://127.0.0.1:${address.port}`)
  } finally {
    await server.stop()
    await rm(storageRoot, { recursive: true, force: true })
  }
}

async function call(url, { method = 'GET', body, headers = {} } = {}) {
  const response = await fetch(url, {
    method,
    headers: { authorization: `Bearer ${TOKEN}`, 'content-type': 'application/json', ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  let parsed = null
  const text = await response.text()
  try { parsed = text === '' ? null : JSON.parse(text) } catch { parsed = text }
  return { status: response.status, body: parsed, headers: response.headers }
}

test('the holds probe reports whether this replica owns the runtime', async () => {
  await withServer({}, async (base) => {
    const missing = await call(`${base}/v1/runtimes/unknown-id/holds`)
    assert.equal(missing.status, 200)
    assert.equal(missing.body.holds, false)
    assert.equal(missing.body.instanceId, 'host-local')

    const created = await call(`${base}/v1/runtimes`, {
      method: 'POST',
      body: { tenantId: 't', profileVersion: 'v1', isolationKey: 'iso-holds' },
    })
    assert.equal(created.status, 201)
    const rid = created.body.runtimeId

    const held = await call(`${base}/v1/runtimes/${rid}/holds`)
    assert.equal(held.status, 200)
    assert.equal(held.body.holds, true)
  })
})

test('an unknown runtime with no peers still fails honestly (and does not crash)', async () => {
  await withServer({ peers: '' }, async (base) => {
    const response = await call(`${base}/v1/runtimes/definitely-unknown/sessions`)
    assert.equal(response.status, 400)
    assert.match(JSON.stringify(response.body), /runtime not found/)

    // The server must survive: a follow-up request still works.
    const health = await call(`${base}/health`)
    assert.equal(health.status, 200)
  })
})

test('a runtime-scoped request at the hop limit is not forwarded again', async () => {
  await withServer({ peers: 'http://127.0.0.1:1' }, async (base) => {
    const response = await call(`${base}/v1/runtimes/unknown-id`, {
      headers: { [HOP_HEADER]: '9' },
    })
    // Must be a local honest failure, never a forwarded success.
    assert.equal(response.status, 400)
    assert.equal(response.headers.get('x-dsh-forwarded-to'), null)
  })
})

test('an unreachable peer does not break the request path', async () => {
  // Port 1 is closed, so discovery exhausts and falls through to the local
  // error. The response must still be well formed and the process alive.
  await withServer({ peers: 'http://127.0.0.1:1' }, async (base) => {
    const response = await call(`${base}/v1/runtimes/unknown-id/sessions`, {
      method: 'POST',
      body: { sessionId: 's', presetId: 'askai-enterprise' },
      headers: { 'x-isolation-key': 'iso-x' },
    })
    assert.equal(response.status, 400)
    const health = await call(`${base}/health`)
    assert.equal(health.status, 200)
  })
})
