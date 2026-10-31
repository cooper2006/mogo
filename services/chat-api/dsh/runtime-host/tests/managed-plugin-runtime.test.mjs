import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { createServer } from 'node:http'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import { RuntimeHttpServer } from '../src/runtime-http-server.mjs'

const fixture = join(dirname(fileURLToPath(import.meta.url)), 'fixtures', 'managed-plugin')

async function request(base, path, method = 'GET', body) {
  const response = await fetch(`${base}${path}`, {
    method,
    headers: { 'content-type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
  const value = await response.json()
  assert.ok(response.ok, `${response.status}: ${JSON.stringify(value)}`)
  return value
}

test('managed plugin activates only for its Runtime and preserves Session handoff', async () => {
  const root = await mkdtemp(join(tmpdir(), 'mogo-managed-plugin-'))
  const source = join(root, 'package')
  const archive = join(root, 'mogo-dsh-test-bundle-1.0.0.tgz')
  await mkdir(source)
  await cp(fixture, source, { recursive: true })
  execFileSync('tar', ['-czf', archive, 'package'], { cwd: root })
  const archiveBytes = await readFile(archive)
  const digest = createHash('sha256').update(archiveBytes).digest('hex')
  const archiveId = 'a'.repeat(32)
  const gateway = createServer((request, response) => {
    if (request.url?.startsWith(`/${archiveId}?digest=${digest}`)) {
      response.writeHead(200, { 'content-type': 'application/gzip' })
      response.end(archiveBytes)
    } else { response.writeHead(404); response.end() }
  })
  await new Promise(resolve => gateway.listen(0, '127.0.0.1', resolve))
  const gatewayUrl = `http://127.0.0.1:${gateway.address().port}`
  const host = new RuntimeHttpServer({ storageRoot: join(root, 'storage') })
  try {
    const { port } = await host.start()
    const base = `http://127.0.0.1:${port}`
    const materialized = await request(base, '/v1/plugin-archives/materialize', 'POST', {
      archiveId, digest, gatewayUrl,
    })
    assert.equal((await readFile(materialized.spec)).compare(archiveBytes), 0)
    await writeFile(materialized.spec, 'damaged cache')
    const repaired = await request(base, '/v1/plugin-archives/materialize', 'POST', {
      archiveId, digest, gatewayUrl,
    })
    assert.equal((await readFile(repaired.spec)).compare(archiveBytes), 0)
    await rm(materialized.spec)
    const plain = await request(base, '/v1/runtimes', 'POST', {
      isolationKey: 'plain-user', profileVersion: 'test',
    })
    const managed = await request(base, '/v1/runtimes', 'POST', {
      isolationKey: 'managed-user', profileVersion: 'test',
      modelProfile: {
        profileVersion: 'test', modelInstanceId: 'test', modelName: 'test',
        gatewayUrl: 'http://127.0.0.1/validation-only', accessToken: 'test',
        pluginGatewayUrl: gatewayUrl,
        plugins: [{
          name: 'mogo-dsh-test-bundle', version: '1.0.0',
          spec: 'uploaded-plugin', archive_id: archiveId, archive_digest: digest,
          source_scope: 'personal', tool_names: ['mogo_plugin_smoke'],
        }],
      },
    })
    const managedPath = `/v1/runtimes/${managed.runtimeId}`
    const plainPath = `/v1/runtimes/${plain.runtimeId}`
    const discovered = await request(base, '/v1/runtimes?isolationKey=managed-user')
    assert.equal(discovered.runtime.modelInstanceId, 'test')
    const active = await request(base, `${managedPath}/managed-plugins`)
    assert.ok(active.bundles.some(bundle => bundle.name === 'mogo-dsh-test-bundle' && bundle.enabled))
    assert.ok(active.globalTools.includes('mogo_plugin_smoke'))
    const other = await request(base, `${plainPath}/managed-plugins`)
    assert.ok(other.bundles.every(bundle => bundle.name !== 'mogo-dsh-test-bundle'))

    const plainSession = await request(base, `${plainPath}/sessions`, 'POST', { sessionId: 'plain-session' })
    assert.ok(!plainSession.capabilityTools.includes('mogo_plugin_smoke'))
    const continued = await request(base, `${managedPath}/sessions`, 'POST', {
      sessionId: 'managed-session', seedRuntimeId: plain.runtimeId, seedSessionId: 'plain-session',
    })
    assert.equal(continued.sessionId, 'managed-session')
    assert.ok(continued.capabilityTools.includes('mogo_plugin_smoke'), JSON.stringify(continued.capabilityTools))
    const back = await request(base, `${plainPath}/sessions`, 'POST', {
      sessionId: 'plain-successor', seedRuntimeId: managed.runtimeId, seedSessionId: 'managed-session',
    })
    assert.equal(back.sessionId, 'plain-successor')
  } finally {
    await host.stop()
    await new Promise(resolve => gateway.close(resolve))
    await rm(root, { recursive: true, force: true })
  }
})
