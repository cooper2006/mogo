import { apiClient } from './client';

export type QuotaPeriod = 'monthly' | 'daily' | 'hourly';
export type QuotaStatus = 'active' | 'disabled';

export interface TrafficAllocationOverview {
  orgPolicy: {
    totalTokens: number;
    unlimited: boolean;
    period: QuotaPeriod;
    timezone: string;
    status: QuotaStatus;
    usedTokens: number;
    remainingTokens: number;
    periodStartAt: string;
    resetAt: string;
  };
  defaultPolicy: {
    quotaTokens: number;
    unlimited: boolean;
    period: QuotaPeriod;
    status: QuotaStatus;
  };
  assignedTokens: number;
  assignedPolicyCount: number;
  // 042 三层配额：团队/项目层只增字段，既有字段语义不变。
  teamAssignedTokens?: number;
  teamPolicyCount?: number;
  projectAssignedTokens?: number;
  projectPolicyCount?: number;
  alertThresholdRatio?: number;
}

export interface ScopedQuotaPolicy {
  scopeType: 'team' | 'project';
  scopeId: string;
  name: string;
  quotaTokens: number;
  period: QuotaPeriod;
  status: QuotaStatus;
}

export interface QuotaProject {
  id: string;
  tenantId: string;
  name: string;
  note: string;
  memberUserIds: string[];
  memberCount: number;
  status: 'active' | 'disabled' | 'deleted';
  // list 接口附带：该项目已配置的周期额度（未配置时为 0 / 空串）
  quotaTokens?: number;
  period?: QuotaPeriod;
  policyStatus?: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface UserAllocationItem {
  userId: string;
  name: string;
  loginName: string;
  email: string;
  mobile: string;
  status: string;
  departmentName: string;
  quotaTokens: number;
  unlimited: boolean;
  usedTokens: number;
  remainingTokens: number;
  period: QuotaPeriod;
  resetAt: string;
}

export interface AllocationLogItem {
  id: string;
  userId: string;
  userName: string;
  action: string;
  beforeQuotaTokens: number;
  afterQuotaTokens: number;
  deltaTokens: number;
  reason: string;
  operator: string;
  createdAt: string;
}

export interface AllocationLogPage {
  page: number;
  pageSize: number;
  total: number;
  items: AllocationLogItem[];
}

export async function fetchTrafficAllocationOverview() {
  const { data } = await apiClient.get<TrafficAllocationOverview>('/api/traffic-allocations/overview');
  return data;
}

export async function updateOrgQuotaPolicy(payload: {
  totalTokens: number;
  unlimited: boolean;
  period: QuotaPeriod;
  timezone: string;
  status: QuotaStatus;
  alertThresholdRatio?: number;
}) {
  const { data } = await apiClient.put<{ success: boolean }>('/api/traffic-allocations/org-policy', payload);
  return data;
}

export async function updateDefaultQuotaPolicy(payload: {
  quotaTokens: number;
  unlimited: boolean;
  period: QuotaPeriod;
  status: QuotaStatus;
}) {
  const { data } = await apiClient.put<{ success: boolean }>('/api/traffic-allocations/default-policy', payload);
  return data;
}

export async function fetchUserAllocations(params: { keyword?: string; statusFilter?: string }) {
  const { data } = await apiClient.get<UserAllocationItem[]>('/api/traffic-allocations/users', { params });
  return data;
}

export async function updateUserQuotaPolicy(userId: string, payload: {
  userId: string;
  quotaTokens: number;
  unlimited: boolean;
  period: QuotaPeriod;
  reason: string;
}) {
  const { data } = await apiClient.put<{ success: boolean }>(`/api/traffic-allocations/users/${userId}/policy`, payload);
  return data;
}

export async function fetchAllocationLogs(params: { page?: number; pageSize?: number } = {}) {
  const { data } = await apiClient.get<AllocationLogPage>('/api/traffic-allocations/logs', { params });
  return data;
}

// ---------------------------------------------------------------------------
// 042 三层配额：团队（复用部门树）与项目分组
// ---------------------------------------------------------------------------

export async function fetchTeamQuotaPolicies() {
  const { data } = await apiClient.get<{ items: ScopedQuotaPolicy[]; total: number }>(
    '/api/traffic-allocations/teams',
  );
  return data;
}

export async function updateTeamQuotaPolicy(orgUnitId: string, payload: {
  quotaTokens: number;
  period: QuotaPeriod;
  status: QuotaStatus;
}) {
  const { data } = await apiClient.put<ScopedQuotaPolicy>(
    `/api/traffic-allocations/teams/${orgUnitId}/policy`,
    payload,
  );
  return data;
}

export async function deleteTeamQuotaPolicy(orgUnitId: string) {
  const { data } = await apiClient.delete<{ success: boolean }>(
    `/api/traffic-allocations/teams/${orgUnitId}/policy`,
  );
  return data;
}

export async function fetchQuotaProjects() {
  const { data } = await apiClient.get<{ items: QuotaProject[]; total: number }>(
    '/api/traffic-allocations/projects',
  );
  return data;
}

export async function createQuotaProject(payload: {
  name: string;
  note?: string;
  memberUserIds?: string[];
  status?: 'active' | 'disabled';
}) {
  const { data } = await apiClient.post<QuotaProject>('/api/traffic-allocations/projects', payload);
  return data;
}

export async function updateQuotaProject(projectId: string, payload: {
  name?: string;
  note?: string;
  memberUserIds?: string[];
  status?: 'active' | 'disabled';
}) {
  const { data } = await apiClient.put<QuotaProject>(
    `/api/traffic-allocations/projects/${projectId}`,
    payload,
  );
  return data;
}

export async function deleteQuotaProject(projectId: string) {
  const { data } = await apiClient.delete<{ success: boolean }>(
    `/api/traffic-allocations/projects/${projectId}`,
  );
  return data;
}

export async function updateProjectQuotaPolicy(projectId: string, payload: {
  quotaTokens: number;
  period: QuotaPeriod;
  status: QuotaStatus;
}) {
  const { data } = await apiClient.put<ScopedQuotaPolicy>(
    `/api/traffic-allocations/projects/${projectId}/policy`,
    payload,
  );
  return data;
}

export async function deleteProjectQuotaPolicy(projectId: string) {
  const { data } = await apiClient.delete<{ success: boolean }>(
    `/api/traffic-allocations/projects/${projectId}/policy`,
  );
  return data;
}
