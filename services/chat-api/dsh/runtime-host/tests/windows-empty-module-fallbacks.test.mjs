import assert from 'node:assert/strict'
import { lstat, mkdtemp, mkdir, readFile, rm, symlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'

import { recoverWindowsEmptyModuleFallbacks } from '../src/official-host/windows-empty-module-fallbacks.mjs'

test('Windows clears only empty interrupted fallback package directories', async () => {
  const home = await mkdtemp(join(tmpdir(), 'mogo-fallback-'))
  const modules = join(home, 'profiles', 'node_modules')
  try {
    await mkdir(join(modules, 'empty'), { recursive: true })
    await mkdir(join(modules, 'owned'))
    await writeFile(join(modules, 'owned', 'package.json'), '{}')
    await symlink(join(modules, 'owned'), join(modules, 'linked'), 'junction')
    assert.equal(await recoverWindowsEmptyModuleFallbacks(home, 'darwin'), 0)
    await writeFile(`${modules}.lock`, '12345\n')
    assert.equal(await recoverWindowsEmptyModuleFallbacks(home, 'win32'), 0)
    await rm(`${modules}.lock`)
    assert.equal(await recoverWindowsEmptyModuleFallbacks(home, 'win32'), 1)
    await assert.rejects(lstat(join(modules, 'empty')), { code: 'ENOENT' })
    assert.equal(await readFile(join(modules, 'owned', 'package.json'), 'utf8'), '{}')
    assert.equal((await lstat(join(modules, 'linked'))).isSymbolicLink(), true)
  } finally {
    await rm(home, { recursive: true, force: true })
  }
})
