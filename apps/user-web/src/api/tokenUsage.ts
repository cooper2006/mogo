import axios from 'axios'
import { installAuthExpiryInterceptor } from './authExpiry'

const client = axios.create({
  timeout: 20000,
})
installAuthExpiryInterceptor(client)

export type TokenUsageSummary = {
  total_calls: number
  internal_calls: number
  total_tokens: number
  prompt_tokens: number
  completion_tokens: number
  avg_tokens: number
  last_called_at?: string | null
  last_24h_calls: number
  last_24h_internal_calls: number
  last_24h_tokens: number
  top_models: Array<{ model_name: string; calls: number; tokens: number }>
}

export type TokenUsageItem = {
  request_id: string
  user_request_id?: string
  tenant_id: string
  user_id: string
  session_id: string
  trace_id: string
  stage: string
  intent: string
  node_id: string
  status: string
  model_name: string
  model_names?: string[]
  model_id: string
  prompt: string
  request_title_zh: string
  request_title_en: string
  start_time: number
  end_time: number
  total_tokens: number
  prompt_tokens: number
  completion_tokens: number
  calls?: number
  push_status: string
  push_error: string
  created_at?: string | null
  updated_at?: string | null
}

export type TokenUsagePage = {
  summary: TokenUsageSummary
  items: TokenUsageItem[]
  offset: number
  limit: number
  total: number
  has_more: boolean
}

// 列表查询参数（与函数签名中的内联类型结构一致）。
type TokenUsageListOptions = {
  tenantId?: string
  limit?: number
  offset?: number
  q?: string
  stage?: string
  status?: string
  token?: string
}

// 组装列表接口的查询串。
function buildTokenUsageQuery(userId: string, options: TokenUsageListOptions): URLSearchParams {
  const query = new URLSearchParams({
    userId,
    limit: String(options.limit ?? 12),
    offset: String(options.offset ?? 0),
  })
  if (options.tenantId) query.set('tenantId', options.tenantId)
  if (options.q) query.set('q', options.q)
  if (options.stage) query.set('stage', options.stage)
  if (options.status) query.set('status', options.status)
  return query
}

// 组装请求头（可选 Bearer token）。
function tokenUsageHeaders(options: TokenUsageListOptions): Record<string, string> {
  return options.token ? { Authorization: `Bearer ${options.token}` } : {}
}

// 归一化汇总数据（summary 缺失时按空对象处理）。
function normalizeUsageSummary(summary?: Partial<TokenUsageSummary>): TokenUsageSummary {
  const s = summary || {}
  return {
    total_calls: Number(s.total_calls || 0),
    internal_calls: Number(s.internal_calls || 0),
    total_tokens: Number(s.total_tokens || 0),
    prompt_tokens: Number(s.prompt_tokens || 0),
    completion_tokens: Number(s.completion_tokens || 0),
    avg_tokens: Number(s.avg_tokens || 0),
    last_called_at: s.last_called_at || null,
    last_24h_calls: Number(s.last_24h_calls || 0),
    last_24h_internal_calls: Number(s.last_24h_internal_calls || 0),
    last_24h_tokens: Number(s.last_24h_tokens || 0),
    top_models: Array.isArray(s.top_models) ? s.top_models : [],
  }
}

// 归一化分页数据（limit 的三重回退保持 || 语义）。
function normalizeUsagePage(data?: Partial<TokenUsagePage>, options: TokenUsageListOptions = {}): TokenUsagePage {
  const body = data || {}
  return {
    summary: normalizeUsageSummary(body.summary),
    items: Array.isArray(body.items) ? body.items : [],
    offset: Number(body.offset || 0),
    limit: Number(body.limit || options.limit || 12),
    total: Number(body.total || 0),
    has_more: Boolean(body.has_more),
  }
}

export async function listTokenUsage(
  userId: string,
  options: TokenUsageListOptions = {}
): Promise<TokenUsagePage> {
  const query = buildTokenUsageQuery(userId, options)
  const response = await client.get(`/askai-api/api/token-usage?${query.toString()}`, {
    headers: tokenUsageHeaders(options),
  })
  return normalizeUsagePage(response.data?.data, options)
}
