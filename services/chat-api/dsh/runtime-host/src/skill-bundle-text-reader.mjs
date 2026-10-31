import { isAbsolute, normalize, sep } from 'node:path'
import { unzipSync } from 'fflate'

import { pageSkillTextResource } from './skill-resource-reader.mjs'

const MAX_TEXT_BYTES = 1024 * 1024

function safeRelativePath(value) {
  const raw = String(value ?? '').trim()
  const normalized = normalize(raw)
  if (!raw || raw.includes('\0') || raw.includes('\\') || isAbsolute(raw) ||
      normalized === '.' || normalized !== raw || normalized === '..' || normalized.startsWith(`..${sep}`)) {
    throw new Error('Skill resource path must be a non-empty package-relative path')
  }
  return raw
}

export function readTextFromSkillArchive(archive, rootPrefix, resourcePath, options = {}) {
  const relative = safeRelativePath(resourcePath)
  const prefix = rootPrefix === '.' ? '' : `${rootPrefix.replace(/\/$/, '')}/`
  const target = `${prefix}${relative}`
  let oversize = false
  const extracted = unzipSync(new Uint8Array(archive), {
    filter: file => {
      if (file.name !== target) return false
      if (file.originalSize > MAX_TEXT_BYTES) { oversize = true; return false }
      return true
    },
  })
  if (oversize) throw new Error(`Skill resource exceeds the ${MAX_TEXT_BYTES}-byte text limit: ${relative}`)
  const bytes = extracted[target]
  if (!bytes) throw new Error(`Skill resource does not exist: ${relative}`)
  return pageSkillTextResource(bytes, relative, options)
}
