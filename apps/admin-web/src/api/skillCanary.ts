import { apiClient } from './client';

/**
 * 033-canary-rollout: admin-web 灰度配置页使用的 canary API 客户端。
 *
 * 后端 `services/admin-api/app/api/routes/skill_canary.py` 的端点（FR-012/FR-013）：
 * 创建 / 查询（含档位、推进历史、影子统计）/ 手动推进 / 影子开关 / 手动回滚。
 */

export interface LadderStepDto {
  ratio: number;
  min_samples?: number | null;
  entered_at?: string;
  promoted_at?: string | null;
}

export interface ShadowStatsDto {
  skill_id: string;
  version: number;
  total: number;
  ok: number;
  success_rate: number;
  avg_duration_ms: number;
}

export interface CanaryEvaluateDto {
  skill_id: string;
  state: string;
  error_rate: number;
  should_rollback: boolean;
  reason: string;
  sample_sufficient: boolean;
  traffic_ratio: number;
  current_step: number;
  ladder: LadderStepDto[];
  ladder_history: Array<Record<string, any>>;
  shadow_enabled: boolean;
  shadow_stats: ShadowStatsDto;
}

export interface CanaryCreatePayload {
  skill_id: string;
  version: number;
  stable_version?: number;
  target_tenants?: string[];
  traffic_ratio?: number;
  ladder?: Array<{ ratio: number; min_samples?: number | null }>;
  shadow_enabled?: boolean;
}

/** 创建 / upsert 一个 canary rollout（016 FR-4 + 033 比例/阶梯/影子维度）。 */
export async function createCanaryRollout(payload: CanaryCreatePayload): Promise<CanaryEvaluateDto> {
  const { data } = await apiClient.post<{ code: number; data: CanaryEvaluateDto }>(
    '/api/skills/canary',
    payload,
    { timeout: 15000 },
  );
  return data.data;
}

/** 查询 rollout 状态：当前档位、推进历史与影子统计（FR-012）。 */
export async function fetchCanaryRollout(skillId: string): Promise<CanaryEvaluateDto> {
  const { data } = await apiClient.get<{ code: number; data: CanaryEvaluateDto }>(
    `/api/skills/canary/${skillId}`,
    { timeout: 15000 },
  );
  return data.data;
}

/** 手动推进阶梯（033 FR-004，5 分钟扫描之外的显式触发）。 */
export async function advanceCanary(skillId: string): Promise<{
  advanced: boolean;
  promoted: boolean;
  current_step: number;
  traffic_ratio: number;
  reason: string;
}> {
  const { data } = await apiClient.post<{
    code: number;
    data: { advanced: boolean; promoted: boolean; current_step: number; traffic_ratio: number; reason: string };
  }>(`/api/skills/canary/${skillId}/advance`, {}, { timeout: 15000 });
  return data.data;
}

/** 开 / 关影子模式（033 FR-006，US4 影子开关）。 */
export async function toggleCanaryShadow(
  skillId: string,
  enabled: boolean,
): Promise<{ shadow_enabled: boolean }> {
  const { data } = await apiClient.post<{ code: number; data: { shadow_enabled: boolean } }>(
    `/api/skills/canary/${skillId}/shadow`,
    { enabled },
    { timeout: 15000 },
  );
  return data.data;
}

/** 手动一键回滚（016 FR-11 / FR-10，033 US3 场景 2）。 */
export async function rollbackCanary(skillId: string): Promise<{
  skillId: string;
  fromVersion: number;
  toVersion: number;
  errorRate: number;
}> {
  const { data } = await apiClient.post<{
    code: number;
    data: { skillId: string; fromVersion: number; toVersion: number; errorRate: number };
  }>(`/api/skills/canary/${skillId}/rollback`, {}, { timeout: 15000 });
  return data.data;
}