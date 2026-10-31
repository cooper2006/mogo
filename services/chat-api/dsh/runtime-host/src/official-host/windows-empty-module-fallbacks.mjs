import { lstat, readdir, rmdir } from 'node:fs/promises'
import { join } from 'node:path'

// A force-stopped DSH boot may leave an empty package directory where a
// generated junction should be. Never touch links or non-empty directories.
export async function recoverWindowsEmptyModuleFallbacks(moduleHome, platform = process.platform) {
  if (platform !== 'win32') return 0
  const modulesDir = join(moduleHome, 'profiles', 'node_modules')
  // Another host may currently be materializing the same fallback tree.
  try { await lstat(`${modulesDir}.lock`); return 0 }
  catch (error) { if (error?.code !== 'ENOENT') throw error }
  let entries
  try { entries = await readdir(modulesDir, { withFileTypes: true }) }
  catch (error) {
    if (error?.code === 'ENOENT') return 0
    throw error
  }
  let removed = 0
  for (const entry of entries) {
    if (entry.name.startsWith('@')) continue // Scope directories are structural.
    const path = join(modulesDir, entry.name)
    const info = await lstat(path).catch(() => null)
    if (!info?.isDirectory() || info.isSymbolicLink()) continue
    if ((await readdir(path)).length !== 0) continue
    try { await rmdir(path); removed += 1 }
    catch (error) { if (error?.code !== 'ENOTEMPTY' && error?.code !== 'ENOENT') throw error }
  }
  return removed
}
