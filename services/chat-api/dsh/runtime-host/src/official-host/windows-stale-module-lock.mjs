import { readFile, rm, stat } from 'node:fs/promises'
import { join } from 'node:path'

// DSH's atomic writer intentionally leaves orphan recovery to its caller.
// A killed Windows host can leave this profile-local lock behind indefinitely.
export async function recoverWindowsStaleModuleLock(moduleHome, {
  platform = process.platform,
  isAlive = pid => {
    try { process.kill(pid, 0); return true }
    catch (error) { return error?.code !== 'ESRCH' }
  },
} = {}) {
  if (platform !== 'win32') return false
  const lockPath = join(moduleHome, 'profiles', 'node_modules.lock')
  let owner
  let original
  try {
    original = await stat(lockPath)
    owner = (await readFile(lockPath, 'utf8')).trim()
  } catch (error) {
    if (error?.code === 'ENOENT') return false
    throw error
  }
  if (!/^[1-9]\d*$/.test(owner) || isAlive(Number(owner))) return false
  // Do not remove a replacement lock written between the owner check and removal.
  const current = await stat(lockPath).catch(error => {
    if (error?.code === 'ENOENT') return null
    throw error
  })
  if (!current || current.mtimeMs !== original.mtimeMs || current.size !== original.size) return false
  if ((await readFile(lockPath, 'utf8')).trim() !== owner) return false
  await rm(lockPath, { force: true })
  return true
}
