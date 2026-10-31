import { createHash } from 'node:crypto'
import { mkdir, mkdtemp, readFile, rename, rm, stat, writeFile } from 'node:fs/promises'
import { dirname, join, normalize, resolve, sep } from 'node:path'
import { unzipSync } from 'fflate'
import { fetchSkillBundle } from './skill-bundle-fetcher.mjs'
import { readTextFromSkillArchive } from './skill-bundle-text-reader.mjs'

const MAX_FILES = 20_000
const MAX_EXPANDED_BYTES = 200 * 1024 * 1024
const MAX_FILE_BYTES = 100 * 1024 * 1024

function safeRelativePath(value) {
  const raw = String(value ?? '').replaceAll('\\', '/')
  const normalized = normalize(raw)
  if (!raw || raw.startsWith('/') || normalized === '..' || normalized.startsWith(`..${sep}`)) {
    throw new Error(`unsafe Skill bundle path: ${raw}`)
  }
  return normalized
}

async function exists(path) {
  try {
    return (await stat(path)).isDirectory()
  } catch (error) {
    if (error?.code === 'ENOENT') return false
    throw error
  }
}

export class SkillBundleMaterializer {
  constructor(storageRoot, { bundleGatewayUrl = '', accessToken = '', fetchBundle = fetchSkillBundle } = {}) {
    this.root = resolve(storageRoot, 'imported-skills')
    this.bundleGatewayUrl = bundleGatewayUrl
    this.accessToken = accessToken
    this.fetchBundle = fetchBundle
  }

  updateCredential(accessToken) { this.accessToken = accessToken }

  async readTextResource(skill, resourcePath, options = {}) {
    const digest = String(skill?.bundle_digest ?? '')
    if (!/^[0-9a-f]{64}$/.test(digest)) throw new Error(`Invalid Skill bundle digest: ${skill?.name ?? 'unknown'}`)
    const rootPrefix = safeRelativePath(String(skill?.bundle_root || '.'))
    const archivePath = resolve(this.root, `${digest}.zip`)
    let archive
    try {
      archive = await readFile(archivePath)
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error
      archive = skill.bundle_archive_id
        ? await this.fetchBundle(skill, this.bundleGatewayUrl, { token: this.accessToken })
        : Buffer.from(String(skill.bundle_archive_base64 || ''), 'base64')
      if (createHash('sha256').update(archive).digest('hex') !== digest) {
        throw new Error(`Skill bundle digest mismatch: ${skill?.name ?? 'unknown'}`)
      }
      await mkdir(this.root, { recursive: true })
      const temporary = await mkdtemp(join(this.root, '.archive-'))
      try {
        await writeFile(join(temporary, 'bundle.zip'), archive, { mode: 0o600 })
        try { await rename(join(temporary, 'bundle.zip'), archivePath) }
        catch (renameError) {
          if (renameError?.code !== 'EEXIST') throw renameError
        }
      } finally {
        await rm(temporary, { recursive: true, force: true })
      }
    }
    if (createHash('sha256').update(archive).digest('hex') !== digest) {
      throw new Error(`Skill bundle digest mismatch: ${skill?.name ?? 'unknown'}`)
    }
    return readTextFromSkillArchive(archive, rootPrefix, resourcePath, options)
  }

  async materialize(skill) {
    const encoded = String(skill?.bundle_archive_base64 ?? '')
    const archiveId = String(skill?.bundle_archive_id ?? '')
    if (!encoded && !archiveId) return undefined
    const digest = String(skill?.bundle_digest ?? '')
    if (!/^[0-9a-f]{64}$/.test(digest)) throw new Error(`Invalid Skill bundle digest: ${skill?.name ?? 'unknown'}`)
    const destination = resolve(this.root, digest)
    const rootPrefix = safeRelativePath(String(skill?.bundle_root || '.'))
    const resourceRoot = resolve(destination, rootPrefix)
    if (archiveId && await exists(destination)) return resourceRoot
    const archive = archiveId
      ? await this.fetchBundle(skill, this.bundleGatewayUrl, { token: this.accessToken })
      : Buffer.from(encoded, 'base64')
    if (createHash('sha256').update(archive).digest('hex') !== digest) {
      throw new Error(`Skill bundle digest mismatch: ${skill?.name ?? 'unknown'}`)
    }
    if (await exists(destination)) return resourceRoot

    let declaredCount = 0
    let declaredTotal = 0
    const entries = Object.entries(unzipSync(new Uint8Array(archive), {
      filter: file => {
        if (file.name.endsWith('/')) return false
        safeRelativePath(file.name)
        declaredCount += 1
        declaredTotal += file.originalSize
        if (declaredCount > MAX_FILES) throw new Error('Skill bundle contains too many files')
        if (file.originalSize > MAX_FILE_BYTES || declaredTotal > MAX_EXPANDED_BYTES) {
          throw new Error('Skill bundle expands beyond the runtime limit')
        }
        return true
      },
    }))
    let total = 0
    await mkdir(this.root, { recursive: true })
    const temporary = await mkdtemp(join(this.root, '.install-'))
    try {
      for (const [entryName, bytes] of entries) {
        if (entryName.endsWith('/')) continue
        const relative = safeRelativePath(entryName)
        total += bytes.byteLength
        if (total > MAX_EXPANDED_BYTES) throw new Error('Skill bundle expands beyond the runtime limit')
        const target = resolve(temporary, relative)
        if (target !== temporary && !target.startsWith(`${temporary}${sep}`)) {
          throw new Error(`Skill bundle path escapes materialization root: ${entryName}`)
        }
        await mkdir(dirname(target), { recursive: true })
        await writeFile(target, bytes, { mode: 0o600 })
      }
      try {
        await rename(temporary, destination)
      } catch (error) {
        if (error?.code !== 'EEXIST' && error?.code !== 'ENOTEMPTY') throw error
      }
    } finally {
      await rm(temporary, { recursive: true, force: true })
    }
    return resourceRoot
  }
}
