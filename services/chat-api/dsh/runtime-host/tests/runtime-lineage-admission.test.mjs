import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import { KernelRuntime } from '../src/kernel-runtime.mjs'
import { sendText, waitFor } from './support/runtime-admission.mjs'

function turnEnded(runtime, sessionId) {
  return runtime.events(sessionId, -1).some(event => event.nativeType === 'turn/end')
}

test('runtime forks a completed conversation through the stable MOVO lineage contract', async () => {
  const root = await mkdtemp(join(tmpdir(), 'askai-runtime-lineage-admission-'))
  const runtime = new KernelRuntime({
    runtimeId: 'runtime-lineage-admission',
    isolationKey: 'tenant:runtime-lineage-admission',
    profileVersion: 'runtime-admission-v1',
    storageRoot: root,
  })
  try {
    await runtime.start()
    await runtime.createSession({ sessionId: 'parent', presetId: 'code', cwd: root })
    sendText(runtime, 'parent', 'parent context marker')
    await waitFor(() => turnEnded(runtime, 'parent'), 'parent Session did not finish')

    const seed = await runtime.exportCompletedSeed('parent')
    assert.ok(seed.length > 0)
    const child = await runtime.createSession({
      sessionId: 'child',
      presetId: 'code',
      cwd: root,
      seed,
      parentSessionId: 'parent',
    })
    assert.equal(child.seedLength, seed.length)
    assert.equal(child.presetId, 'code')
    assert.ok(child.modelTools.includes('subagent'))

    sendText(runtime, 'child', 'child continuation marker')
    await waitFor(() => turnEnded(runtime, 'child'), 'child Session did not execute')
    assert.ok(runtime.events('child', -1).some(event => (
      event.nativeType === 'assistant/message'
      && JSON.stringify(event.data).includes('child continuation marker')
    )))
  } finally {
    await runtime.dispose()
    await rm(root, { recursive: true, force: true })
  }
})
