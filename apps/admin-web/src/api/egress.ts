import { apiClient } from './client';

// 038 egress-sandbox 出站白名单 + 审计日志的 admin-web 客户端。
// 字段命名严格对齐后端契约定稿（services/admin-api/app/api/routes/egress.py 与
// app/services/egress_store.py）：snake_case 直传，不做 camelCase 映射。

export type EgressScope = 'tool' | 'tenant' | 'platform';

/** 白名单条目（egress_allowlist 集合，scope ∈ platform|tenant|tool）。 */
export interface EgressRule {
  entry_id: string;
  scope: EgressScope;
  match_domain: string;
  tenant_id: string;
  tool_id: string;
  path_prefix: string;
  enabled: boolean;
  note: string;
  updated_at: string;
}

/** GET /api/egress/allowlist 信封。 */
export interface EgressAllowlistPage {
  items: EgressRule[];
  total: number;
}

/** POST /api/egress/allowlist 请求体（scope/tool_id 由服务端按调用者身份归一）。 */
export interface EgressRuleCreatePayload {
  scope: EgressScope;
  match_domain: string;
  path_prefix?: string;
  enabled?: boolean;
  note?: string;
  tool_id?: string;
}

/** PATCH /api/egress/allowlist/{id} 请求体（部分更新，只传要改的字段）。 */
export interface EgressRuleUpdatePayload {
  match_domain?: string;
  path_prefix?: string;
  enabled?: boolean;
  note?: string;
}

/** 审计事件 details 载荷（chat-api egress_guard.audit 写入）。 */
export interface EgressLogDetails {
  egress?: string;
  capability?: string;
  domain?: string;
  url_safe?: string;
  allowed?: boolean;
  reason?: string;
  matched_scope?: string;
  matched_entry_id?: string;
  matched_path_prefix?: string;
  scheme?: string;
}

/** 审计日志行（enterprise_tool_audit，事件 egress.allowed / egress.denied）。 */
export interface EgressLogEntry {
  event: string;
  tenant_id: string;
  user_id: string;
  action_id: string;
  occurred_at: string;
  details: EgressLogDetails;
}

/** GET /api/egress/logs 信封。 */
export interface EgressLogPage {
  items: EgressLogEntry[];
  total: number;
  page: number;
  page_size: number;
}

export async function fetchEgressAllowlist(params: { scope?: EgressScope | ''; enabled?: boolean } = {}) {
  const { data } = await apiClient.get<EgressAllowlistPage>('/api/v1/egress/allowlist', { params });
  return data;
}

export async function fetchEgressRule(entryId: string) {
  const { data } = await apiClient.get<EgressRule>(`/api/v1/egress/allowlist/${entryId}`);
  return data;
}

export async function createEgressRule(payload: EgressRuleCreatePayload) {
  const { data } = await apiClient.post<EgressRule>('/api/v1/egress/allowlist', payload);
  return data;
}

export async function updateEgressRule(entryId: string, payload: EgressRuleUpdatePayload) {
  const { data } = await apiClient.patch<EgressRule>(`/api/v1/egress/allowlist/${entryId}`, payload);
  return data;
}

export async function deleteEgressRule(entryId: string) {
  await apiClient.delete(`/api/v1/egress/allowlist/${entryId}`);
}

export async function fetchEgressLogs(
  params: { page?: number; page_size?: number; event?: string; domain?: string } = {},
) {
  const { data } = await apiClient.get<EgressLogPage>('/api/v1/egress/logs', { params });
  return data;
}