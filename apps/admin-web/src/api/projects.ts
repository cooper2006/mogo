/**
 * 047-quota-discoverability: 项目管理页 API（项目列表 + 用量成本合并请求）
 */
import { apiClient } from './client';
import type { QuotaProject, QuotaPeriod } from './traffic-allocations';

export interface ProjectUsageCost {
  projectId: string;
  totalTokens: number;
  totalCostUsd: number;
  requestCount: number;
}

export interface ProjectWithUsage extends QuotaProject {
  usage?: ProjectUsageCost;
}

export interface ProjectListResponse {
  items: ProjectWithUsage[];
  total: number;
}

export async function fetchProjectsWithUsage(): Promise<ProjectListResponse> {
  const { data } = await apiClient.get<ProjectListResponse>(
    '/api/v1/traffic-allocations/projects-with-usage',
  );
  return data;
}

export async function updateProjectQuotaPolicy(projectId: string, payload: {
  quotaTokens: number;
  period: QuotaPeriod;
}) {
  const { data } = await apiClient.put<QuotaProject>(
    `/api/v1/traffic-allocations/projects/${projectId}/policy`,
    payload,
  );
  return data;
}

export async function deleteProjectQuotaPolicy(projectId: string) {
  await apiClient.delete(
    `/api/v1/traffic-allocations/projects/${projectId}/policy`,
  );
}
