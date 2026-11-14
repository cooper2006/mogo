import assert from 'node:assert/strict'
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'

import { recoverWindowsStaleModuleLock } from '../src/official-host/windows-stale-module-lock.mjs'

test('Windows removes only an orphaned DSH module fallback lock', async () => {
  const home = await mkdtemp(join(tmpdir(), 'mogo-stale-lock-'))
  const lock = join(home, 'profiles', 'node_modules.lock')
  try {
    await mkdir(join(home, 'profiles'))
    await writeFile(lock, '12345\n')
    assert.equal(await recoverWindowsStaleModuleLock(home, { platform: 'darwin', isAlive: () => false }), false)
    assert.equal(await recoverWindowsStaleModuleLock(home, { platform: 'win32', isAlive: () => true }), false)
    assert.equal(await readFile(lock, 'utf8'), '12345\n')
    assert.equal(await recoverWindowsStaleModuleLock(home, { platform: 'win32', isAlive: () => false }), true)
    assert.equal(await recoverWindowsStaleModuleLock(home, { platform: 'win32', isAlive: () => false }), false)
  } finally {
    await rm(home, { recursive: true, force: true })
  }
})

test('Windows retains a lock without a verified numeric owner', async () => {
  const home = await mkdtemp(join(tmpdir(), 'mogo-stale-lock-'))
  const lock = join(home, 'profiles', 'node_modules.lock')
  try {
    await mkdir(join(home, 'profiles'))
    await writeFile(lock, 'pending')
    assert.equal(await recoverWindowsStaleModuleLock(home, { platform: 'win32', isAlive: () => false }), false)
    assert.equal(await readFile(lock, 'utf8'), 'pending')
  } finally {
    await rm(home, { recursive: true, force: true })
  }
})
