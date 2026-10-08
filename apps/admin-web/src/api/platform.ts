import { apiClient } from './client';

export type TenantStatus = 'active' | 'disabled' | 'archived' | 'purged';

/**
 * Lifecycle-only view of a tenant. The platform console deliberately sees no
 * business metrics (decision 7) — the backend strips them in `tenant_view`.
 */
export interface PlatformTenant {
  tenantId: string;
  name: string;
  status: TenantStatus;
  edition: string;
  adminUsername: string;
  memberLimit: number | null;
  createdAt: string;
  createdBy: string;
  archivedAt?: string;
  archiveReason?: string;
  purgedAt?: string;
}

export interface TenantListPage {
  items: PlatformTenant[];
  total: number;
}

export interface TenantListQuery {
  page?: number;
  pageSize?: number;
  keyword?: string;
  status?: TenantStatus | '';
}

export interface TenantEmployeePayload {
  username: string;
  password?: string;
  name?: string;
}

export interface TenantQuotaPayload {
  totalTokens: number;
  defaultUserTokens: number;
}

export interface TenantCreatePayload {
  orgName: string;
  adminUsername: string;
  adminPassword: string;
  adminDisplayName?: string;
  employee?: TenantEmployeePayload | null;
  model?: string | Record<string, unknown> | null;
  additionalModels?: Array<string | Record<string, unknown>> | null;
  quota?: TenantQuotaPayload | null;
}

/**
 * ``provision_tenant`` returns a plain dataclass that serializes as snake_case
 * (no aliases are configured), unlike the lifecycle views which are camelCase.
 */
export interface TenantCreateResult {
  tenant_id: string;
  org_name: string;
  model_instance_id?: string | null;
  additional_model_instance_ids?: string[];
}

export interface TenantUpdatePayload {
  name?: string;
  status?: 'active' | 'disabled';
  memberLimit?: number | 'null';
}

export interface PurgeStartResult {
  taskId: string;
  status: string;
}

export interface PurgePhaseProgress {
  done: boolean;
  deleted?: number;
  total?: number;
  message?: string;
}

export interface PurgeProgress {
  status: 'running' | 'done' | 'failed' | 'unknown';
  mongo?: PurgePhaseProgress;
  vectors?: PurgePhaseProgress;
  files?: PurgePhaseProgress;
  errors?: string[];
  startedAt?: string;
  finishedAt?: string;
}

export interface SystemHealthService {
  key: string;
  label: string;
  ok: boolean;
  message: string;
  core: boolean;
}

export interface PlatformProfile {
  username: string;
  displayName: string;
  tenantId: string;
}

export async function fetchTenants(query: TenantListQuery = {}) {
  const params: Record<string, string | number> = {};
  if (query.page) params.page = query.page;
  if (query.pageSize) params.pageSize = query.pageSize;
  if (query.keyword) params.keyword = query.keyword;
  if (query.status) params.status = query.status;
  const { data } = await apiClient.get<TenantListPage>('/api/platform/tenants', { params });
  return data;
}

export async function fetchTenant(tenantId: string) {
  const { data } = await apiClient.get<PlatformTenant>(`/api/platform/tenants/${encodeURIComponent(tenantId)}`);
  return data;
}

export async function createTenant(payload: TenantCreatePayload) {
  const { data } = await apiClient.post<TenantCreateResult>('/api/platform/tenants', payload, {
    timeout: 120000,
  });
  return data;
}

export async function updateTenant(tenantId: string, payload: TenantUpdatePayload) {
  const { data } = await apiClient.patch<PlatformTenant>(
    `/api/platform/tenants/${encodeURIComponent(tenantId)}`,
    payload,
  );
  return data;
}

export async function resetTenantAdminPassword(tenantId: string, newPassword: string) {
  const { data } = await apiClient.post<{ success: boolean }>(
    `/api/platform/tenants/${encodeURIComponent(tenantId)}/admin/reset-password`,
    { newPassword },
  );
  return data;
}

export async function archiveTenant(tenantId: string, reason: string) {
  const { data } = await apiClient.delete<{ status: string; archivedAt: string }>(
    `/api/platform/tenants/${encodeURIComponent(tenantId)}`,
    { data: { reason } },
  );
  return data;
}

export async function restoreTenant(tenantId: string) {
  const { data } = await apiClient.post<PlatformTenant>(
    `/api/platform/tenants/${encodeURIComponent(tenantId)}/restore`,
  );
  return data;
}

export async function purgeTenant(tenantId: string, confirmName: string) {
  const { data } = await apiClient.post<PurgeStartResult>(
    `/api/platform/tenants/${encodeURIComponent(tenantId)}/purge`,
    { confirmName },
  );
  return data;
}

export async function fetchPurgeStatus(tenantId: string) {
  const { data } = await apiClient.get<PurgeProgress>(
    `/api/platform/tenants/${encodeURIComponent(tenantId)}/purge-status`,
  );
  return data;
}

export async function fetchPlatformProfile() {
  const { data } = await apiClient.get<PlatformProfile>('/api/platform/me');
  return data;
}

export async function fetchSystemHealth() {
  const { data } = await apiClient.get<SystemHealthService[]>('/api/platform/system/health', {
    timeout: 60000,
  });
  return data;
}
