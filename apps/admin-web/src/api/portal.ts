import { apiClient } from './client';

/**
 * 037 统一门户 —— 管理侧 API 客户端（上架 / 下架 / 审批队列 / 批准拒绝 / 回收）。
 *
 * 后端契约见 ``services/admin-api/app/api/routes/portal_admin.py``；
 * 终端用户侧（浏览 / 申领）在 user-web ``src/api/portal.ts``，走 chat-api。
 */

export type PortalAssetType = 'skill' | 'capability_asset';

export interface PortalListing {
  asset_type: PortalAssetType;
  asset_key: string;
  category: string;
  published_by: string;
  published_at: string | null;
  unpublished_at: string | null;
  published: boolean;
  name?: string;
  is_active_asset?: boolean;
}

export type PortalRequestStatus = 'applied' | 'approved' | 'rejected' | 'granted' | 'revoked' | 'expired';

export interface PortalApprovalItem {
  request_id: string;
  requester_id: string;
  asset_type: PortalAssetType;
  asset_key: string;
  asset_name?: string;
  reason: string;
  status: PortalRequestStatus;
  approver_id: string;
  applied_at: string | null;
  decided_at: string | null;
  decided_reason: string;
  granted_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  can_decide?: boolean;
}

export async function fetchPortalListings(params: { publishedOnly?: boolean } = {}): Promise<PortalListing[]> {
  const { data } = await apiClient.get<{ items: PortalListing[] }>('/api/portal/listings', {
    params: { published_only: params.publishedOnly ?? true },
  });
  return data?.items ?? [];
}

export async function publishPortalListing(payload: {
  assetType: PortalAssetType;
  assetKey: string;
  category?: string;
}): Promise<{ published: boolean; listing: PortalListing }> {
  const { data } = await apiClient.post('/api/portal/listings', {
    asset_type: payload.assetType,
    asset_key: payload.assetKey,
    category: payload.category ?? '',
  });
  return data;
}

export async function unpublishPortalListing(assetType: PortalAssetType, assetKey: string): Promise<{ unpublished: boolean }> {
  const { data } = await apiClient.delete(`/api/portal/listings/${encodeURIComponent(assetType)}/${encodeURIComponent(assetKey)}`);
  return data;
}

export async function fetchPortalApprovals(params: { status?: PortalRequestStatus | 'all' } = {}): Promise<PortalApprovalItem[]> {
  const { data } = await apiClient.get<{ items: PortalApprovalItem[] }>('/api/portal/approvals', {
    params: { status: params.status ?? 'applied' },
  });
  return data?.items ?? [];
}

export async function decidePortalApproval(
  requestId: string,
  payload: { approved: boolean; reason?: string },
): Promise<{ status: PortalRequestStatus; changed: boolean; request: PortalApprovalItem | null }> {
  const { data } = await apiClient.post(`/api/portal/approvals/${encodeURIComponent(requestId)}/decide`, {
    approved: payload.approved,
    reason: payload.reason ?? '',
  });
  return data;
}

export async function revokePortalGrant(requestId: string, reason = ''): Promise<{ revoked: boolean; grant_removed: boolean }> {
  const { data } = await apiClient.post(
    `/api/portal/requests/${encodeURIComponent(requestId)}/revoke`,
    { reason },
  );
  return data;
}

export const PORTAL_STATUS_LABELS: Record<PortalRequestStatus, string> = {
  applied: '待审批',
  approved: '已批准',
  rejected: '已拒绝',
  granted: '已开通',
  revoked: '已回收',
  expired: '已到期',
};

export function portalStatusLabel(status?: string): string {
  if (!status) return '';
  return PORTAL_STATUS_LABELS[status as PortalRequestStatus] || status;
}
