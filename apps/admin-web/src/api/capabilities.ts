import { apiClient } from './client';

// 045 资产中心 —— 能力资产 admin 只读 API（FR-1）。
// 后端 `GET /api/v1/capabilities/list`（admin JWT）返回 `{code, message, data}`
// 信封，与 trust-ratings / portal-admin 同一约定，因此解包 `data.data.items`。

export type CapabilityKind = 'rest' | 'mcp' | 'tool' | 'connector';
export type CapabilityState = 'active' | 'deprecated' | 'offline';

/** 018 `capability_assets` 集合文档（045 FR-1 投影字段）。 */
export interface CapabilityAsset {
  asset_id: string;
  name: string;
  kind: CapabilityKind | string;
  state: CapabilityState | string;
  contract: {
    input: Record<string, unknown>;
    output: Record<string, unknown>;
    errors: Record<string, unknown>;
    sla: Record<string, unknown>;
  };
  version: number;
  owner_role: string;
  endpoint: string;
  method: string;
  a2a_exposed: boolean;
  last_seen_at: string | null;
  updated_at: string | null;
}

export interface CapabilityListResult {
  items: CapabilityAsset[];
  total: number;
}

/** 后端统一信封 `{code, message, data}`（与 trust-ratings 同一约定）。 */
interface ApiEnvelope<T> {
  code: number;
  message: string;
  data: T;
}

/** 资产中心类型下拉 4 项（FR-4）：skill / mcp / tool / connector。 */
export type AssetCategory = 'skill' | 'mcp' | 'tool' | 'connector';

/**
 * `GET /api/v1/capabilities/list` → CapabilityAsset[]。
 * 支持 `kind` / `state` 过滤（FR-1）。后端返回 `{code, message, data}` 信封，
 * 与 trust-ratings 同一约定，因此解包 `data.data.items`。
 */
export async function fetchCapabilities(
  params?: { kind?: CapabilityKind | string; state?: CapabilityState | string },
): Promise<CapabilityAsset[]> {
  const { data } = await apiClient.get<ApiEnvelope<CapabilityListResult>>('/api/v1/capabilities/list', {
    params: params as Record<string, string> | undefined,
  });
  return data.data.items;
}
