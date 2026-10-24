import { apiClient } from './client';

// 036 trust-rating (L1–L4 资产评级) admin client. 与 traffic-allocations.ts
// 同一 apiClient 约定；后端 `/api/trust-ratings` 端点统一返回
// `{code, message, data}` 信封，因此这里解包 `data.data`。

export type TrustLevel = 'L1' | 'L2' | 'L3' | 'L4';
export type TrustAssetType = 'skill' | 'agent' | 'workflow';

/** 后端 `trust_ratings` 集合文档（`_view` 直接返回原始文档，字段为 snake_case）。 */
export interface TrustRating {
  tenant_id: string;
  asset_type: TrustAssetType;
  asset_key: string;
  level: TrustLevel;
  previous_level: TrustLevel | null;
  below_since: string | null;
  below_streak_days: number;
  reason: string;
  last_evidence: Record<string, unknown> | null;
  owner_id: string;
  created_by: string;
  updated_by: string;
  deprecate_pending: boolean;
  created_at: string;
  updated_at: string;
}

/** `GET /distribution` → `{L1, L2, L3, L4}` 计数。 */
export type TrustDistribution = Record<TrustLevel, number>;

/** `GET|PUT /settings`（FR-10 降级开关）。 */
export interface TrustRatingSettings {
  enabled: boolean;
  window_days: number;
  interval_seconds: number;
}

/** `POST /changes` 请求体（对外暴露 camelCase，内部映射到后端 snake_case）。 */
export interface TrustRatingChangePayload {
  targetLevel: TrustLevel;
  reason: string;
  ownerId?: string;
  evidence?: Record<string, unknown>;
}

/** `POST /recompute` 返回（人工重算：评级 + 质量信号 + 动作 + 决策）。 */
export interface TrustRatingRecomputeResult {
  rating: TrustRating;
  signal: Record<string, unknown>;
  action: string;
  decision: Record<string, unknown>;
}

interface ApiEnvelope<T> {
  code: number;
  message: string;
  data: T;
}

/** `GET /api/trust-ratings`（FR-14：后端默认按当前账号可见性过滤 L1）。 */
export async function fetchTrustRatings(params: { assetType?: TrustAssetType } = {}): Promise<TrustRating[]> {
  const { data } = await apiClient.get<ApiEnvelope<{ items: TrustRating[] }>>('/api/trust-ratings', {
    params: { asset_type: params.assetType },
  });
  return data.data.items;
}

/** `GET /api/trust-ratings/distribution`（FR-16，008 驾驶舱消费）。 */
export async function fetchTrustRatingDistribution(): Promise<TrustDistribution> {
  const { data } = await apiClient.get<ApiEnvelope<TrustDistribution>>('/api/trust-ratings/distribution');
  return data.data;
}

/** `GET /api/trust-ratings/settings`。 */
export async function fetchTrustRatingSettings(): Promise<TrustRatingSettings> {
  const { data } = await apiClient.get<ApiEnvelope<TrustRatingSettings>>('/api/trust-ratings/settings');
  return data.data;
}

/** `PUT /api/trust-ratings/settings`。 */
export async function updateTrustRatingSettings(payload: {
  enabled?: boolean;
  windowDays?: number;
}): Promise<TrustRatingSettings> {
  const { data } = await apiClient.put<ApiEnvelope<TrustRatingSettings>>('/api/trust-ratings/settings', {
    enabled: payload.enabled,
    window_days: payload.windowDays,
  });
  return data.data;
}

/** `GET /api/trust-ratings/{asset_type}/{asset_key}`。 */
export async function fetchTrustRating(assetType: TrustAssetType, assetKey: string): Promise<TrustRating> {
  const { data } = await apiClient.get<ApiEnvelope<TrustRating>>(
    `/api/trust-ratings/${assetType}/${encodeURIComponent(assetKey)}`,
  );
  return data.data;
}

/** `POST /api/trust-ratings/{asset_type}/{asset_key}/changes`。 */
export async function changeTrustRating(
  assetType: TrustAssetType,
  assetKey: string,
  payload: TrustRatingChangePayload,
): Promise<TrustRating> {
  const { data } = await apiClient.post<ApiEnvelope<TrustRating>>(
    `/api/trust-ratings/${assetType}/${encodeURIComponent(assetKey)}/changes`,
    {
      target_level: payload.targetLevel,
      reason: payload.reason,
      owner_id: payload.ownerId ?? '',
      evidence: payload.evidence ?? null,
    },
  );
  return data.data;
}

/** `POST /api/trust-ratings/{asset_type}/{asset_key}/recompute`。 */
export async function recomputeTrustRating(
  assetType: TrustAssetType,
  assetKey: string,
): Promise<TrustRatingRecomputeResult> {
  const { data } = await apiClient.post<ApiEnvelope<TrustRatingRecomputeResult>>(
    `/api/trust-ratings/${assetType}/${encodeURIComponent(assetKey)}/recompute`,
  );
  return data.data;
}