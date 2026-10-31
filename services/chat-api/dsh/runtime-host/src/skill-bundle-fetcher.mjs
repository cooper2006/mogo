import { createHash } from 'node:crypto'

const MAX_ARCHIVE_BYTES = 100 * 1024 * 1024

export async function fetchSkillBundle(skill, gatewayUrl, { fetchImpl = fetch, token = process.env.DSH_RUNTIME_HOST_TOKEN || '' } = {}) {
  const id = String(skill?.bundle_archive_id ?? '')
  const digest = String(skill?.bundle_digest ?? '')
  if (!/^[0-9a-f]{32}$/.test(id) || !/^[0-9a-f]{64}$/.test(digest) || !gatewayUrl) {
    throw new Error('Invalid Skill bundle reference')
  }
  const url = new URL(`${gatewayUrl.replace(/\/$/, '')}/${id}`)
  url.searchParams.set('digest', digest)
  const response = await fetchImpl(url, {
    headers: token ? { authorization: `Bearer ${token}` } : {},
    signal: AbortSignal.timeout(120_000),
  })
  if (!response.ok || !response.body) throw new Error(`Skill bundle fetch failed: HTTP ${response.status}`)
  const chunks = []
  const hash = createHash('sha256')
  let total = 0
  for await (const chunk of response.body) {
    total += chunk.byteLength
    if (total > MAX_ARCHIVE_BYTES) throw new Error('Skill bundle exceeds the archive limit')
    hash.update(chunk)
    chunks.push(chunk)
  }
  if (hash.digest('hex') !== digest) throw new Error('Skill bundle digest mismatch')
  return Buffer.concat(chunks, total)
}
