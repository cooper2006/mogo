import { createHash } from 'node:crypto'
import { createReadStream } from 'node:fs'
import { mkdir, rename, rm, stat, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'

const LIMIT = 100 * 1024 * 1024

async function cachedArchiveIsValid(path, digest) {
  const file = await stat(path)
  if (!file.isFile() || file.size > LIMIT) return false
  const hash = createHash('sha256')
  for await (const chunk of createReadStream(path)) hash.update(chunk)
  return hash.digest('hex') === digest
}

export class PluginArchiveMaterializer {
  constructor(storageRoot) { this.root = resolve(storageRoot, 'plugin-archives') }

  async materialize({ archiveId, digest, gatewayUrl, accessToken }) {
    if (!/^[0-9a-f]{32}$/.test(archiveId) || !/^[0-9a-f]{64}$/.test(digest) || !gatewayUrl) {
      throw new Error('Invalid plugin archive reference')
    }
    const destination = join(this.root, `${digest}.tgz`)
    try {
      if (await cachedArchiveIsValid(destination, digest)) return destination
      await rm(destination, { force: true })
    } catch (error) { if (error?.code !== 'ENOENT') throw error }
    const url = new URL(`${gatewayUrl.replace(/\/$/, '')}/${archiveId}`)
    url.searchParams.set('digest', digest)
    const response = await fetch(url, {
      headers: accessToken ? { authorization: `Bearer ${accessToken}` } : {},
      signal: AbortSignal.timeout(120_000),
    })
    if (!response.ok || !response.body) throw new Error(`Plugin archive fetch failed: HTTP ${response.status}`)
    const chunks = []
    const hash = createHash('sha256')
    let total = 0
    for await (const chunk of response.body) {
      total += chunk.byteLength
      if (total > LIMIT) throw new Error('Plugin archive exceeds 100 MiB')
      hash.update(chunk)
      chunks.push(chunk)
    }
    if (hash.digest('hex') !== digest) throw new Error('Plugin archive digest mismatch')
    await mkdir(this.root, { recursive: true })
    const temporary = join(this.root, `.${digest}-${process.pid}-${Date.now()}.tmp`)
    try {
      await writeFile(temporary, Buffer.concat(chunks, total), { mode: 0o600 })
      await rename(temporary, destination)
    } finally { await rm(temporary, { force: true }) }
    return destination
  }

  async prepareProfile(modelProfile) {
    if (!modelProfile?.plugins?.some(plugin => plugin.archive_id)) return modelProfile
    const plugins = []
    for (const plugin of modelProfile.plugins) {
      if (!plugin.archive_id) { plugins.push(plugin); continue }
      const spec = await this.materialize({
        archiveId: plugin.archive_id,
        digest: plugin.archive_digest,
        gatewayUrl: modelProfile.pluginGatewayUrl,
        accessToken: modelProfile.accessToken,
      })
      plugins.push({ ...plugin, spec })
    }
    return { ...modelProfile, plugins }
  }
}
