/**
 * 009 钩子规则页 admin-web API client（/api/hooks）。
 * 与 chat-api `app/api/endpoints/dsh_hooks.py` 对应。
 *
 * 后端字段为 snake_case：rule_id / rule_type / rule_config / tenant_id。
 * admin-web 页面层直接以该命名展示，避免再做一次 camelCase 转换。
 */
import { apiClient } from './client';

export type HookRuleType = 'deny_tool' | 'require_field' | 'observe';
export type HookScope = 'tool' | 'session' | 'tenant';

export interface HookRule {
  rule_id: string;
  scope: string;
  rule_type: HookRuleType;
  rule_config: Record<string, unknown>;
  enabled: boolean;
  tenant_id: string;
}

export interface HookRuleCreatePayload {
  scope: HookScope;
  rule_type: HookRuleType;
  rule_config?: Record<string, unknown>;
  enabled?: boolean;
}

export interface HookRuleUpdatePayload {
  enabled?: boolean;
  rule_config?: Record<string, unknown>;
  scope?: HookScope;
  rule_type?: HookRuleType;
}

/** 列出全部钩子规则（后端无记录时返回空列表）。 */
export async function fetchHookRules(params?: { tenant_id?: string }): Promise<HookRule[]> {
  const { data } = await apiClient.get<HookRule[]>('/api/hooks/rules', { params });
  return data ?? [];
}

/** 创建一条规则。 */
export async function createHookRule(payload: HookRuleCreatePayload): Promise<HookRule> {
  const { data } = await apiClient.post<HookRule>('/api/hooks/rules', payload);
  return data!;
}

/** 更新一条规则（enabled / rule_config / scope / rule_type）。 */
export async function updateHookRule(
  ruleId: string,
  patch: HookRuleUpdatePayload,
): Promise<HookRule> {
  const { data } = await apiClient.put<HookRule>(`/api/hooks/rules/${ruleId}`, patch);
  return data!;
}

/** 删除一条规则；成功返回被删的 rule_id。 */
export async function deleteHookRule(ruleId: string): Promise<string> {
  const { data } = await apiClient.delete<{ deleted: string }>(
    `/api/hooks/rules/${ruleId}`,
  );
  return data?.deleted ?? ruleId;
}
