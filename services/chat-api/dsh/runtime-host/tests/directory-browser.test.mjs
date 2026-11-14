import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { basename, join } from 'node:path'
import test from 'node:test'

import {
  createDirectory,
  DirectoryBrowseError,
  ensureWorkspaceRoot,
  listDirectory,
  workspaceRoot,
} from '../src/directory-browser.mjs'

// Each test gets its own ephemeral root so a fresh install (no pre-seeded
// volume) is exercised every time. The default root is `/data/dsh-runtime/
// workspaces` on the read-only host's one writable volume; pointing it at a
// temp dir here validates the same create-on-first-use logic. `mkdtemp` gives
// a base dir; the actual root is a not-yet-created child of it, so the
// create-on-first-use path is genuinely exercised.
async function withRoot(fn) {
  const base = await mkdtemp(join(tmpdir(), 'askai-dir-browser-'))
  const root = join(base, 'ws-root')
  const previous = process.env.MOGO_WORKSPACE_ROOT
  process.env.MOGO_WORKSPACE_ROOT = root
  try {
    await fn(root)
  } finally {
    if (previous === undefined) delete process.env.MOGO_WORKSPACE_ROOT
    else process.env.MOGO_WORKSPACE_ROOT = previous
    await rm(base, { recursive: true, force: true })
  }
}

test('workspace root is created on first use when absent', async () => {
  await withRoot(async (root) => {
    assert.equal(workspaceRoot(), root)
    // Nothing exists yet.
    const before = await import('node:fs/promises').then((m) => m.stat(root).then(() => true).catch(() => false))
    assert.equal(before, false)
    await ensureWorkspaceRoot()
    const after = await import('node:fs/promises').then((m) => m.stat(root).then((s) => s.isDirectory()).catch(() => false))
    assert.equal(after, true)
  })
})

test('listing an empty root returns no entries and a root crumb', async () => {
  await withRoot(async (root) => {
    const listing = await listDirectory(null)
    assert.equal(listing.path, root)
    assert.deepEqual(listing.entries, [])
    assert.equal(listing.crumbs.length, 1)
    assert.equal(listing.crumbs[0].name, basename(root))
    assert.equal(listing.crumbs[0].path, root)
  })
})

test('createDirectory then listDirectory reflects the new folder', async () => {
  await withRoot(async (root) => {
    const created = await createDirectory(root, 'proj-alpha')
    assert.equal(created, join(root, 'proj-alpha'))
    const listing = await listDirectory(null)
    assert.deepEqual(listing.entries.map((e) => e.name), ['proj-alpha'])
    const nested = await createDirectory(created, 'sub')
    assert.equal(nested, join(root, 'proj-alpha', 'sub'))
    const inside = await listDirectory(created)
    assert.deepEqual(inside.entries.map((e) => e.name), ['sub'])
  })
})

test('a path outside the root is refused as directory-unreadable', async () => {
  await withRoot(async (root) => {
    await assert.rejects(
      () => listDirectory('/etc'),
      (error) => error instanceof DirectoryBrowseError && error.code === 'directory-unreadable',
    )
  })
})

test('an invalid directory segment is refused', async () => {
  await withRoot(async (root) => {
    await assert.rejects(
      () => createDirectory(root, '../escape'),
      (error) => error instanceof DirectoryBrowseError,
    )
    await assert.rejects(
      () => createDirectory(root, 'has/slash'),
      (error) => error instanceof DirectoryBrowseError,
    )
  })
})
