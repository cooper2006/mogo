import type { EvidenceBundleItem, EvidenceSourceItem } from '../features/execution-v3/domain/delivery'

function hasSourceContent(source: EvidenceSourceItem): boolean {
  return Boolean(
    String(source.title || '').trim() ||
    String(source.snippet || '').trim() ||
    String(source.content || '').trim() ||
    String(source.source_url || '').trim() ||
    (source.document_id && source.chunk_id),
  )
}

// 判断值是否为非空对象。
function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : null
}

// 判断是否为知识库类型的证据源。
function isKbSourceType(source: EvidenceSourceItem): boolean {
  const type = String(source.source_type || '').toLowerCase()
  return type === 'kb' || type === 'internal'
}

// 是否带可定位证据的引用（URL 或 document_id+chunk_id）。
function hasEvidenceLocator(source: EvidenceSourceItem): boolean {
  return Boolean(source.source_url || (source.document_id && source.chunk_id))
}

// 是否带非空的证据文本。
function hasEvidenceText(source: EvidenceSourceItem): boolean {
  return Boolean(String(source.snippet || '').trim() || String(source.content || '').trim())
}

// 从知识库解析结果取计数（兼容 camelCase 与 snake_case）。
function readParsedCount(parsed: Record<string, unknown> | null, camel: string, snake: string): number {
  return Number(parsed ? (parsed[camel] || parsed[snake] || 0) : 0)
}

// 判断知识库 JSON 载荷是否为空结果。
function isKnowledgePayloadEmpty(parsed: Record<string, unknown> | null, sources: unknown): boolean {
  const provider = String(parsed ? (parsed.provider || '') : '').toLowerCase()
  const usedCount = readParsedCount(parsed, 'usedCount', 'used_count')
  const retrievedCount = readParsedCount(parsed, 'retrievedCount', 'retrieved_count')
  return provider.includes('knowledge')
    && usedCount === 0
    && retrievedCount === 0
    && Array.isArray(sources)
    && sources.length === 0
}

// 判断 content 是否为「空知识库结果」JSON。
function isEmptyKbPayload(content: string): boolean {
  if (!content.startsWith('{') && !content.startsWith('[')) return false
  try {
    const parsed = asRecord(JSON.parse(content))
    const sources = asRecord(parsed?.evidenceBundle)?.sources
    return isKnowledgePayloadEmpty(parsed, sources)
  } catch {
    // Fall back to the plain empty-source check below.
  }
  return false
}

function isEmptyKbSource(source: EvidenceSourceItem): boolean {
  if (!isKbSourceType(source)) return false
  if (isEmptyKbPayload(String(source.content || '').trim())) return true
  const title = String(source.title || source.source_name || '').trim().toLowerCase()
  return !hasEvidenceLocator(source) && !hasEvidenceText(source) && ['kb_search', 'knowledge_search'].includes(title)
}

function sourceSignature(source: EvidenceSourceItem): string {
  const url = String(source.source_url || '').trim()
  if (url) return `url:${url}`
  if (source.document_id && source.chunk_id) return `doc:${source.document_id}:${source.chunk_id}`
  return [
    'text',
    String(source.source_type || '').trim(),
    String(source.title || '').trim(),
    String(source.snippet || '').trim().slice(0, 120),
  ].join(':')
}

// 收集去重后的证据源。
function collectSources(bundles: EvidenceBundleItem[], sink: EvidenceSourceItem[], seen: Set<string>): void {
  for (const bundle of bundles) {
    for (const source of bundle.sources || []) {
      if (!hasSourceContent(source) || isEmptyKbSource(source)) continue
      const key = sourceSignature(source)
      if (seen.has(key)) continue
      seen.add(key)
      sink.push(source)
    }
  }
}

// 收集去重后的字符串列表。
function collectStrings(
  bundles: EvidenceBundleItem[],
  pick: (bundle: EvidenceBundleItem) => unknown[],
  sink: string[],
  seen: Set<string>,
): void {
  for (const bundle of bundles) {
    for (const raw of pick(bundle) || []) {
      const text = String(raw || '').trim()
      if (!text || seen.has(text)) continue
      seen.add(text)
      sink.push(text)
    }
  }
}

export function mergeEvidenceBundles(bundles: EvidenceBundleItem[]): EvidenceBundleItem | null {
  if (!bundles.length) return null

  const sources: EvidenceSourceItem[] = []
  const seenSources = new Set<string>()
  const confirmedFacts: string[] = []
  const seenFacts = new Set<string>()
  const openQuestions: string[] = []
  const seenQuestions = new Set<string>()

  collectSources(bundles, sources, seenSources)
  collectStrings(bundles, (bundle) => bundle.confirmed_facts, confirmedFacts, seenFacts)
  collectStrings(bundles, (bundle) => bundle.open_questions, openQuestions, seenQuestions)

  if (!sources.length && !confirmedFacts.length && !openQuestions.length) return null
  return {
    id: `merged_${bundles.map((bundle) => bundle.id).join('_')}`,
    ts: bundles[bundles.length - 1]?.ts || Date.now(),
    summary: '',
    sources,
    confirmed_facts: confirmedFacts,
    open_questions: openQuestions,
  }
}
