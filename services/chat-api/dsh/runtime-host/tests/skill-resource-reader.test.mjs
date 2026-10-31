import assert from 'node:assert/strict'
import { mkdtemp, mkdir, rm, symlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import { readSkillTextResource } from '../src/skill-resource-reader.mjs'

test('reads and paginates UTF-8 files inside a Skill package', async () => {
  const root = await mkdtemp(join(tmpdir(), 'mogo-skill-resource-'))
  try {
    await mkdir(join(root, 'assets'))
    await writeFile(join(root, 'assets', 'contacts.json'), '{\n  "phone": "0757-123456"\n}\n')
    assert.deepEqual(await readSkillTextResource(root, 'assets/contacts.json', {
      startLine: 2, lineCount: 1,
    }), {
      path: 'assets/contacts.json', content: '  "phone": "0757-123456"',
      startLine: 2, endLine: 2, totalLines: 4, truncated: true,
    })
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test('rejects traversal, symlink escapes, and binary package resources', async () => {
  const parent = await mkdtemp(join(tmpdir(), 'mogo-skill-resource-boundary-'))
  const root = join(parent, 'skill')
  try {
    await mkdir(root)
    await writeFile(join(parent, 'outside.txt'), 'secret')
    let symlinkAvailable = true
    try {
      await symlink(join(parent, 'outside.txt'), join(root, 'escape.txt'))
    } catch (error) {
      if (process.platform !== 'win32' || !['EPERM', 'EACCES'].includes(error.code)) throw error
      symlinkAvailable = false
    }
    await writeFile(join(root, 'binary.dat'), Buffer.from([0xff, 0xfe, 0xfd]))
    await assert.rejects(readSkillTextResource(root, '../outside.txt'), /escapes the package/)
    await assert.rejects(readSkillTextResource(root, join(parent, 'outside.txt')), /relative path/)
    if (symlinkAvailable) {
      await assert.rejects(readSkillTextResource(root, 'escape.txt'), /escapes the package/)
    }
    await assert.rejects(readSkillTextResource(root, 'binary.dat'), /UTF-8 text/)
  } finally {
    await rm(parent, { recursive: true, force: true })
  }
})
