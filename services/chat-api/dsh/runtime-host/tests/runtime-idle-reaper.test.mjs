import assert from 'node:assert/strict'
import test from 'node:test'

import { RuntimeIdleReaper } from '../src/runtime-idle-reaper.mjs'

test('reaps idle leases and preserves an active request', async () => {
  const removed = []
  const reaper = new RuntimeIdleReaper({
    idleMs: 1000, intervalMs: 60_000,
    onIdle: async entry => { removed.push(entry.id); reaper.delete(entry) },
  })
  try {
    const idle = { id: 'idle' }
    const active = { id: 'active' }
    reaper.add(idle)
    reaper.add(active)
    let release
    const task = reaper.use(active, () => new Promise(resolve => { release = resolve }))
    await reaper.sweep(Date.now() + 2000)
    assert.deepEqual(removed, ['idle'])
    release()
    await task
    await reaper.sweep(Date.now() + 2000)
    assert.deepEqual(removed, ['idle', 'active'])
  } finally { reaper.stop() }
})
