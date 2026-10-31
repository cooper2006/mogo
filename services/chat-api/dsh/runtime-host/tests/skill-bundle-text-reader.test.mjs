import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdtemp, readdir, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'
import { strToU8, zipSync } from 'fflate'

import { SkillBundleMaterializer } from '../src/skill-bundle-materializer.mjs'

test('text reads from a large Skill archive do not materialize its resources', async () => {
  const root = await mkdtemp(join(tmpdir(), 'mogo-skill-text-'))
  const files = { 'ppt-master/SKILL.md': strToU8('Skill instructions') }
  for (let index = 0; index < 300; index += 1) {
    files[`ppt-master/templates/layout-${index}.svg`] = strToU8(`<svg>${index}</svg>`)
  }
  const archive = Buffer.from(zipSync(files))
  const digest = createHash('sha256').update(archive).digest('hex')
  const skill = { name: 'ppt-master', bundle_digest: digest, bundle_root: 'ppt-master/', bundle_archive_id: 'a'.repeat(32) }
  let fetches = 0
  const materializer = new SkillBundleMaterializer(root, {
    fetchBundle: async () => { fetches += 1; return archive },
  })
  try {
    assert.equal((await materializer.readTextResource(skill, 'SKILL.md')).content, 'Skill instructions')
    assert.equal((await materializer.readTextResource(skill, 'templates/layout-299.svg')).content, '<svg>299</svg>')
    assert.equal(fetches, 1)
    assert.deepEqual(await readdir(join(root, 'imported-skills')), [`${digest}.zip`])
    await assert.rejects(materializer.readTextResource(skill, '../other.txt'), /package-relative path/)
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test('archive text reader rejects binary resources', async () => {
  const root = await mkdtemp(join(tmpdir(), 'mogo-skill-binary-'))
  const archive = Buffer.from(zipSync({ 'skill/SKILL.md': strToU8('Body'), 'skill/image.png': new Uint8Array([0xff, 0x00]) }))
  try {
    const skill = { bundle_digest: createHash('sha256').update(archive).digest('hex'),
      bundle_root: 'skill/', bundle_archive_base64: archive.toString('base64') }
    await assert.rejects(new SkillBundleMaterializer(root).readTextResource(skill, 'image.png'), /valid UTF-8/)
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})
