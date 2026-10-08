/**
 * 009 钩子规则页 admin-web API client（/api/hooks）。
 * 与 admin-api `app/api/routes/hooks.py` 对应（009 T015-T016，admin-api 为权威实现）。
 *
 * 后端字段为 snake_case：rule_id / rule_type / rule_config / tenant_id。
 * admin-web 页面层直接以该命名展示，避免再做一次 camelCase 转换。
 *
 * 契约要点（与早期 chat-api 草案不同，调用方需注意）：
 * - 列表返回 `{ items, total }` 信封，而非裸数组；
 * - 更新走 `PATCH`（非 `PUT`）；
 * - 删除返回 `204`，无响应体；
 * - 列表查询参数为 `scope` / `enabled`（列表本身已按当前管理员 tenant_id 过滤）。
 *
 * 路径拼装：apiClient baseURL `/admin-api` + gateway 剥掉 `/admin-api`，
 * 故 admin-api 侧实际收到 `/api/hooks/...`（api_router 以 `/api` 挂载 + 路由前缀 `/hooks`）。
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

export interface HookRuleListResult {
  items: HookRule[];
  total: number;
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
export async function fetchHookRules(params?: { scope?: string; enabled?: boolean }): Promise<HookRule[]> {
  const { data } = await apiClient.get<HookRuleListResult>('/api/hooks/rules', { params });
  return data?.items ?? [];
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
  const { data } = await apiClient.patch<HookRule>(`/api/hooks/rules/${ruleId}`, patch);
  return data!;
}

/** 删除一条规则；成功返回被删的 rule_id（后端为 204，无响应体）。 */
export async function deleteHookRule(ruleId: string): Promise<string> {
  await apiClient.delete(`/api/hooks/rules/${ruleId}`);
  return ruleId;
}
