/**
 * 037 统一门户 —— 终端用户侧 API 客户端。
 *
 * 全部走 chat-api 既有 ``/askai-api`` 前缀（``end_user`` 会话，Authorization 由
 * ``createApiClient`` 统一注入）；租户由会话决定，前端**不传** tenantId。
 *
 * 后端契约见 ``services/chat-api/app/api/endpoints/portal.py``。
 */
import { createApiClient } from './client'

const api = createApiClient({ baseURL: '/askai-api/api', timeout: 30000 })

export type PortalAssetType = 'skill' | 'capability_asset'

/** 016 效果分摘要（无数据时后端返回 null，前端隐藏）。 */
export interface PortalEffect {
  effect_score?: number | null
  samples?: number | null
  avg_latency_ms?: number | null
}

/** 036 信任评级摘要（L1 默认不进目录，开关由后端软裁剪控制）。 */
export interface PortalRating {
  level: string
  score?: number | null
}

export interface PortalCatalogItem {
  asset_type: PortalAssetType
  asset_key: string
  name: string
  description: string
  category: string
  owner: string
  owner_role: string
  tags: string[]
  state: string
  is_low_quality: boolean
  effect: PortalEffect | null
  rating: PortalRating | null
  kind: string
  endpoint?: string
  published_at?: string | null
}

export interface PortalCatalogPage {
  items: PortalCatalogItem[]
  total: number
  page: number
  page_size: number
}

export interface PortalCategory {
  category: string
  count: number
}

/** 申领单状态机：applied → approved → granted → revoked / expired（rejected 为终态分支）。 */
export type PortalRequestStatus = 'applied' | 'approved' | 'rejected' | 'granted' | 'revoked' | 'expired'

export interface PortalRequest {
  request_id: string
  asset_type: PortalAssetType
  asset_key: string
  reason: string
  status: PortalRequestStatus
  approver_id: string
  applied_at: string | null
  decided_at: string | null
  decided_reason: string
  granted_at: string | null
  expires_at: string | null
  revoked_at: string | null
  is_terminal?: boolean
}

export interface PortalMyRequest extends PortalRequest {
  asset_name?: string
  is_expired?: boolean
}

export interface PortalMyRequestsPage {
  items: PortalMyRequest[]
  total: number
  page: number
  page_size: number
}

export interface PortalAssetDetail {
  item: PortalCatalogItem
  my_request: PortalRequest | null
  granted: boolean
}

export interface PortalRequestResult {
  /** created / pending / already_granted */
  status: 'created' | 'pending' | 'already_granted' | 'applied' | 'granted' | string
  created: boolean
  request: PortalRequest | null
}

export interface PortalCatalogQuery {
  category?: string
  keyword?: string
  page?: number
  pageSize?: number
}

export async function fetchPortalCatalog(query: PortalCatalogQuery = {}): Promise<PortalCatalogPage> {
  const { data } = await api.get('/portal/catalog', {
    params: {
      category: query.category || undefined,
      keyword: query.keyword || undefined,
      page: query.page || 1,
      page_size: query.pageSize || 20,
    },
  })
  return data as PortalCatalogPage
}

export async function fetchPortalCategories(): Promise<PortalCategory[]> {
  const { data } = await api.get('/portal/catalog/categories')
  return (data?.items || []) as PortalCategory[]
}

export async function fetchPortalAssetDetail(
  assetType: PortalAssetType,
  assetKey: string,
): Promise<PortalAssetDetail> {
  const { data } = await api.get(`/portal/catalog/${encodeURIComponent(assetType)}/${encodeURIComponent(assetKey)}`)
  return data as PortalAssetDetail
}

export async function applyPortalAsset(payload: {
  assetType: PortalAssetType
  assetKey: string
  reason?: string
}): Promise<PortalRequestResult> {
  const { data } = await api.post('/portal/requests', {
    asset_type: payload.assetType,
    asset_key: payload.assetKey,
    reason: payload.reason || '',
  })
  return data as PortalRequestResult
}

export async function fetchMyPortalRequests(params: {
  status?: PortalRequestStatus | ''
  page?: number
  pageSize?: number
} = {}): Promise<PortalMyRequestsPage> {
  const { data } = await api.get('/portal/requests/mine', {
    params: {
      status: params.status || undefined,
      page: params.page || 1,
      page_size: params.pageSize || 20,
    },
  })
  return data as PortalMyRequestsPage
}

export async function revokeMyPortalRequest(requestId: string, reason = ''): Promise<{ revoked: boolean }> {
  const { data } = await api.post(`/portal/requests/${encodeURIComponent(requestId)}/revoke`, { reason })
  return data as { revoked: boolean }
}

/** 申领状态 → 中文标签（组件内共享，避免各处重复映射）。 */
export const PORTAL_STATUS_LABELS: Record<PortalRequestStatus, string> = {
  applied: '待审批',
  approved: '已批准，开通中',
  rejected: '已拒绝',
  granted: '已开通',
  revoked: '已回收',
  expired: '已到期',
}

export function portalStatusLabel(status?: string): string {
  if (!status) return ''
  return PORTAL_STATUS_LABELS[status as PortalRequestStatus] || status
}
