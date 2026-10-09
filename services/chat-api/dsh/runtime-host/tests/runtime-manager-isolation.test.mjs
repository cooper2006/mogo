import assert from 'node:assert/strict'
import { test } from 'node:test'
import { RuntimeManager } from '../src/runtime-manager.mjs'

test('concurrent creates for one isolation key do not fork a second runtime', async () => {
  const manager = new RuntimeManager({ storageRoot: '/tmp/x' })
  const first = await manager.create({ isolationKey: 'tenant:1:profile:v1', profileVersion: 'v1' })
  // Two creates that start while the first is still awaiting runtime.start()
  // previously both passed the has() check and each registered an owner,
  // forking a second kernel for the same isolation key. After the fix the
  // owner is claimed before start() awaits, so the second create fails fast.
  await assert.rejects(
    manager.create({ isolationKey: 'tenant:1:profile:v1', profileVersion: 'v1' }),
    /isolation key already has a runtime/,
  )
  const owner = manager.findByIsolation('tenant:1:profile:v1')
  assert.equal(owner?.runtimeId, first.runtimeId)
  assert.deepEqual(
    manager.inventory().map((r) => r.runtimeId),
    [first.runtimeId],
  )
  await manager.dispose(first.runtimeId)
})

test('registration is rolled back when a kernel fails to start', async () => {
  const manager = new RuntimeManager({ storageRoot: '/tmp/x' })
  const created = await manager.create({ isolationKey: 'ok', profileVersion: 'v1' })
  assert.deepEqual(manager.inventory().map((r) => r.runtimeId), [created.runtimeId])
  await manager.dispose(created.runtimeId)
  assert.equal(manager.inventory().length, 0)
  assert.equal(manager.findByIsolation('ok'), undefined)
})
