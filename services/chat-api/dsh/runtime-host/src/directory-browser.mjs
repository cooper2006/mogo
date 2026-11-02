/**
 * Server-side directory browsing for the Web client.
 *
 * MOGO's user-web is a pure web client: it never runs on the employee's own
 * machine, so the DSH desktop's native OS chooser is unreachable from it. The
 * DSH platform already models this case — its `directoryPicker` seam offers a
 * `browse` capability beside the `native` one, documented as the interaction
 * that "works for remote clients — nothing renders on the host display"
 * (`@deepseek-ai/dsh-host-directory-picker`).
 *
 * This module is that `browse` capability expressed as plain Node stdlib
 * calls, so the runtime host can serve one directory level at a time to the
 * web client. The listing shape and the failure vocabulary mirror the DSH
 * seam exactly (`DirectoryListing` / `DirectoryEntry`, and the closed codes
 * `directory-unreadable` / `directory-exists` / `directory-create-failed`),
 * so a future swap to the official backend is a drop-in change.
 *
 * Two deliberate differences from the DSH backend:
 *
 * 1. Scope. The official backend browses the whole host filesystem, which is
 *    right for a developer tool running on the employee's own machine. Here
 *    the host is a shared server, so listing is confined to an allow-listed
 *    root (`MOGO_WORKSPACE_ROOT`, default `/workspaces`). A path outside that
 *    root is refused exactly like an unreadable directory.
 * 2. No hidden-entry flag. The root is a workspace area rather than a home
 *    directory, so there is no dot-file convention to honour; every child
 *    directory is listed.
 */

import { mkdir, opendir, stat } from 'node:fs/promises'
import { homedir } from 'node:os'
import { basename, join, relative, resolve, sep } from 'node:path'

/** Default root for browsable workspaces when the environment says nothing. */
const DEFAULT_WORKSPACE_ROOT = '/workspaces'

/** The closed failure vocabulary the DSH directory-picker seam defines. */
export const DIRECTORY_ERROR_CODES = {
  unreadable: 'directory-unreadable',
  exists: 'directory-exists',
  createFailed: 'directory-create-failed',
}

/** A failure carrying one of the closed codes and the path it is about. */
export class DirectoryBrowseError extends Error {
  constructor(code, path, message) {
    super(message)
    this.name = 'DirectoryBrowseError'
    this.code = code
    this.path = path
  }
}

/** The browsable root; every listed path must live inside it. */
export function workspaceRoot() {
  const configured = String(process.env.MOGO_WORKSPACE_ROOT || '').trim()
  return resolve(configured || DEFAULT_WORKSPACE_ROOT)
}

/**
 * Whether the path is a fully qualified location.
 *
 * On POSIX that means a leading `/`. On Windows only drive-qualified
 * (`C:\…`) or complete UNC (`\\server\share…`) forms qualify — a rooted
 * drive-less form (`\foo`) still resolves against the process's current
 * drive, so it is not a stable target for a client to browse.
 */
export function fullyQualified(path, platform = process.platform) {
  const value = String(path || '').trim()
  if (value === '') return false
  if (platform === 'win32') {
    return /^[A-Za-z]:[\\/]/.test(value) || /^\\\\[^\\/]+\\[^\\/]+/.test(value)
  }
  return value.startsWith('/')
}

/**
 * Resolve a client-supplied path inside the browsable root.
 *
 * A relative path is taken against the root rather than the process cwd — a
 * wire value must never resolve against wherever the host happens to run.
 * A path that escapes the root is refused as unreadable.
 */
function resolveInsideRoot(path) {
  const root = workspaceRoot()
  if (path === undefined || path === null || String(path).trim() === '') {
    return { root, target: root }
  }
  const raw = String(path).trim()
  const target = fullyQualified(raw) ? resolve(raw) : resolve(root, raw)
  // `path.relative` is the containment test: a target outside the root yields
  // a relative path that starts with `..` (or is absolute on a different
  // drive). Slicing the target string instead would mis-measure a path that
  // merely shares a prefix with the root.
  const relative = relativeInside(root, target)
  if (relative === null) {
    throw new DirectoryBrowseError(
      DIRECTORY_ERROR_CODES.unreadable, target,
      `cannot list "${target}": outside the browsable workspace root`,
    )
  }
  return { root, target }
}

/**
 * The target's path relative to the root, or null when it lies outside.
 *
 * @param {string} root the browsable root.
 * @param {string} target the resolved candidate path.
 * @returns {string|null} the relative path ('' means the root itself).
 */
function relativeInside(root, target) {
  const relativePath = relative(root, target)
  if (relativePath === '') return relativePath
  if (relativePath.startsWith('..')) return null
  if (fullyQualified(relativePath)) return null
  return relativePath
}

/** One ancestor crumb of the listed path, from the root down to it. */
function ancestryCrumbs(target, root) {
  const crumbs = []
  const relative = target === root ? '' : target.slice(root.length + 1)
  let current = root
  crumbs.push({ name: basename(root) || root, path: current, hidden: false })
  if (relative === '') return crumbs
  for (const segment of relative.split(sep)) {
    if (segment === '') continue
    current = join(current, segment)
    crumbs.push({ name: segment, path: current, hidden: false })
  }
  return crumbs
}

/**
 * List one directory level: its child directories plus the ancestry crumbs.
 *
 * @param {string} [path] absolute directory to list; absent lists the root.
 * @returns {Promise<{path: string, home: string, crumbs: Array<{name: string, path: string, hidden: boolean}>, entries: Array<{name: string, path: string, hidden: boolean}>, truncated: boolean}>}
 */
export async function listDirectory(path) {
  const { root, target } = resolveInsideRoot(path)
  let level
  try {
    level = await opendir(target)
  } catch (error) {
    throw new DirectoryBrowseError(
      DIRECTORY_ERROR_CODES.unreadable, target,
      `cannot list ${target}: ${error instanceof Error ? error.message : String(error)}`,
    )
  }
  const entries = []
  try {
    for (;;) {
      const dirent = await level.read()
      if (dirent === null) break
      if (!dirent.isDirectory() && !dirent.isSymbolicLink()) continue
      const child = join(target, dirent.name)
      // A symlink is listed only when it actually resolves to a directory:
      // the browser shows what can be entered, and a broken link cannot.
      let enterable = dirent.isDirectory()
      if (!enterable) {
        try {
          enterable = (await stat(child)).isDirectory()
        } catch {
          continue
        }
      }
      entries.push({ name: dirent.name, path: child, hidden: false })
    }
  } finally {
    await level.close().catch(() => {})
  }
  entries.sort((left, right) => left.name.localeCompare(right.name))
  return {
    path: target,
    home: homedir(),
    crumbs: ancestryCrumbs(target, root),
    entries,
    truncated: false,
  }
}

/**
 * Create one child directory under an existing parent.
 *
 * @param {string} path absolute existing parent directory.
 * @param {string} name single non-blank path segment (no separators).
 * @returns {Promise<string>} the created directory's absolute path.
 */
export async function createDirectory(path, name) {
  const { target: parent } = resolveInsideRoot(path)
  const segment = String(name ?? '').trim()
  if (segment === '' || segment === '.' || segment === '..' || /[/\\]/.test(segment)) {
    throw new DirectoryBrowseError(
      DIRECTORY_ERROR_CODES.createFailed, parent,
      `"${segment}" is not a single path segment`,
    )
  }
  const target = join(parent, segment)
  try {
    await mkdir(target)
  } catch (error) {
    const code = error && typeof error === 'object' && error.code === 'EEXIST'
      ? DIRECTORY_ERROR_CODES.exists
      : DIRECTORY_ERROR_CODES.createFailed
    throw new DirectoryBrowseError(
      code, target,
      code === DIRECTORY_ERROR_CODES.exists
        ? `${target} already exists`
        : `cannot create ${target}: ${error instanceof Error ? error.message : String(error)}`,
    )
  }
  return target
}
