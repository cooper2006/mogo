import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'
import { zipSync, strToU8 } from 'fflate'

import { SkillBundleMaterializer } from '../src/skill-bundle-materializer.mjs'
import { fetchSkillBundle } from '../src/skill-bundle-fetcher.mjs'

test('materializes an immutable nested Skill bundle for DSH directory resources', async () => {
  const root = await mkdtemp(join(tmpdir(), 'mogo-skill-bundle-'))
  const archive = Buffer.from(zipSync({
    'sample/SKILL.md': strToU8('---\nname: sample\ndescription: Sample\n---\nBody'),
    'sample/references/a.txt': strToU8('resource'),
  }))
  const digest = createHash('sha256').update(archive).digest('hex')
  try {
    const path = await new SkillBundleMaterializer(root).materialize({
      name: 'sample', bundle_digest: digest, bundle_root: 'sample/',
      bundle_archive_base64: archive.toString('base64'),
    })
    assert.equal(await readFile(join(path, 'references/a.txt'), 'utf8'), 'resource')
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test('rejects a bundle whose immutable digest does not match', async () => {
  const root = await mkdtemp(join(tmpdir(), 'mogo-skill-bundle-'))
  try {
    await assert.rejects(
      new SkillBundleMaterializer(root).materialize({
        name: 'sample', bundle_digest: '0'.repeat(64), bundle_archive_base64: Buffer.from('bad').toString('base64'),
      }),
      /digest mismatch/,
    )
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test('referenced bundle is fetched once and then reused from the digest cache', async () => {
  const root = await mkdtemp(join(tmpdir(), 'mogo-referenced-skill-'))
  const archive = Buffer.from(zipSync({
    'sample/SKILL.md': strToU8('---\nname: sample\ndescription: Sample\n---\nBody'),
    'sample/references/a.txt': strToU8('cached resource'),
  }))
  const digest = createHash('sha256').update(archive).digest('hex')
  const skill = { bundle_archive_id: 'a'.repeat(32), bundle_digest: digest, bundle_root: 'sample/' }
  let downloads = 0
  const materializer = new SkillBundleMaterializer(root, {
    bundleGatewayUrl: 'http://localhost/bundles',
    fetchBundle: async () => { downloads += 1; return archive },
  })
  try {
    const first = await materializer.materialize(skill)
    const second = await materializer.materialize(skill)
    assert.equal(first, second)
    assert.equal(downloads, 1)
    assert.equal(await readFile(join(first, 'references/a.txt'), 'utf8'), 'cached resource')
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test('remote bundle fetch rejects a digest mismatch', async () => {
  const archive = Buffer.from('untrusted archive')
  await assert.rejects(fetchSkillBundle({
    bundle_archive_id: 'a'.repeat(32), bundle_digest: '0'.repeat(64),
  }, 'http://localhost/bundles', {
    fetchImpl: async () => new Response(archive, { status: 200 }),
  }), /digest mismatch/)
})

test('materializes a package with more than 256 resources', async () => {
  const root = await mkdtemp(join(tmpdir(), 'mogo-large-skill-'))
  const files = { 'sample/SKILL.md': strToU8('---\nname: sample\ndescription: Sample\n---\nBody') }
  for (let index = 0; index < 300; index += 1) {
    files[`sample/templates/layout-${index}.txt`] = strToU8(`layout ${index}`)
  }
  const archive = Buffer.from(zipSync(files))
  try {
    const path = await new SkillBundleMaterializer(root).materialize({
      name: 'sample', bundle_digest: createHash('sha256').update(archive).digest('hex'),
      bundle_root: 'sample/', bundle_archive_base64: archive.toString('base64'),
    })
    assert.equal(await readFile(join(path, 'templates/layout-299.txt'), 'utf8'), 'layout 299')
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})
