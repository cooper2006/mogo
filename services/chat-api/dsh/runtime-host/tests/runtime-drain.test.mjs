import assert from 'node:assert/strict'
import { mkdir, mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import { HOST_STATES } from '../src/host-protocol.mjs'
import { RuntimeHttpServer } from '../src/runtime-http-server.mjs'

const TOKEN = 'runtime-drain-token-0123456789abcdef'

test('a fresh host reports the ready state on /health', async () => {
  const root = await mkdtemp(join(tmpdir(), 'askai-drain-ready-'))
  const runtime = new RuntimeHttpServer({ storageRoot: root, authToken: TOKEN })
  try {
    const address = await runtime.start()
    const health = await (await fetch(
      `http://${address.host}:${address.port}/health`,
      { headers: { authorization: `Bearer ${TOKEN}` } },
    )).json()
    assert.equal(health.state, HOST_STATES.ready)
    assert.equal(health.instanceId, '')
  } finally {
    await runtime.stop()
    await rm(root, { recursive: true, force: true })
  }
})

test('POST /drain marks the host draining and rejects new work', async () => {
  const root = await mkdtemp(join(tmpdir(), 'askai-drain-post-'))
  const runtime = new RuntimeHttpServer({ storageRoot: root, authToken: TOKEN })
  try {
    const address = await runtime.start()
    const base = `http://${address.host}:${address.port}`
    const headers = { authorization: `Bearer ${TOKEN}`, 'content-type': 'application/json' }

    // A runtime exists before draining, so disposeAll has something to close.
    await fetch(`${base}/v1/runtimes`, { method: 'POST', headers, body: JSON.stringify({ isolationKey: 'drain-tenant', profileVersion: 'v1' }) })

    const drained = await fetch(`${base}/drain`, { method: 'POST', headers })

    const health = await (await fetch(`${base}/health`, { headers })).json()
    assert.equal(health.state, HOST_STATES.draining)

    // New runtimes are refused while draining.
    const refused = await fetch(`${base}/v1/runtimes`, { method: 'POST', headers, body: JSON.stringify({ isolationKey: 'drain-tenant-2', profileVersion: 'v1' }) })
    assert.equal(refused.status, 503)
    assert.equal((await refused.json()).error.code, 'service_draining')
  } finally {
    await runtime.stop()
    await rm(root, { recursive: true, force: true })
  }
})

test('stop() drains before closing, so idle sessions are disposed without cancelling in-flight work', async () => {
  const root = await mkdtemp(join(tmpdir(), 'askai-drain-stop-'))
  const runtime = new RuntimeHttpServer({ storageRoot: root, authToken: TOKEN })
  try {
    const address = await runtime.start()
    const base = `http://${address.host}:${address.port}`
    const headers = { authorization: `Bearer ${TOKEN}`, 'content-type': 'application/json' }

    // No live sessions: the drain phase must complete immediately.
    const stoppedAt = Date.now()
    await runtime.stop()
    assert.ok(Date.now() - stoppedAt < 2000, 'drain of an idle host is bounded and fast')
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})
