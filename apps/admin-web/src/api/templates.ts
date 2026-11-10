import { apiClient } from './client';

// 053-plaza-template-distribution —— 模板管理 / 广场查询 / 克隆 / 升级 API。
// 后端 `GET /api/v1/templates`（admin JWT）返回 `{code, message, data}` 信封，
// 与 capabilities / trust-ratings 同一约定，解包 `data.data`.

export type TemplateAssetType = 'employee_template' | 'sop_template';
export type TemplateState = 'draft' | 'published' | 'offline';

export interface TemplateSummary {
  template_id: string;
  name: string;
  asset_type: TemplateAssetType;
  version: number;
  state: TemplateState;
  category: string;
  description: string;
  owner_id: string;
  digest: string;
  readonly: boolean;
  updated_at: string;
}

export interface TemplateCloneRecord {
  clone_id: string;
  tenant_id: string;
  template_id: string;
  template_type: TemplateAssetType;
  template_version: number;
  cloner_id: string;
  target_type: string;
  target_key: string;
  template_ref: { template_id: string; asset_type: string; version: number };
  created_at: string;
  has_newer_version?: boolean;
  source_version?: number;
}

export interface TemplateDetail extends TemplateSummary {
  content: Record<string, unknown>;
  gate_report: Record<string, unknown>;
  versions: Array<Record<string, unknown>>;
  clones: TemplateCloneRecord[];
}

interface ApiEnvelope<T> {
  code: number;
  message: string;
  data: T;
}

/** 广场目录（租户内可见模板，默认已上架）。 */
export async function fetchTemplates(
  params?: { asset_type?: TemplateAssetType; state?: TemplateState },
): Promise<{ items: TemplateSummary[]; total: number }> {
  const { data } = await apiClient.get<ApiEnvelope<{ items: TemplateSummary[]; total: number }>>(
    '/api/v1/templates',
    { params: params as Record<string, string> | undefined },
  );
  return data.data;
}

/** 模板详情（含版本序列 + 克隆记录）。 */
export async function fetchTemplate(templateId: string): Promise<TemplateDetail> {
  const { data } = await apiClient.get<ApiEnvelope<TemplateDetail>>(`/api/v1/templates/${templateId}`);
  return data.data;
}

export interface CreateTemplatePayload {
  name: string;
  asset_type: TemplateAssetType;
  content: Record<string, unknown>;
  description?: string;
  category?: string;
}

/** 创建模板草稿。 */
export async function createTemplate(payload: CreateTemplatePayload): Promise<TemplateSummary> {
  const { data } = await apiClient.post<ApiEnvelope<TemplateSummary>>('/api/v1/templates', payload);
  return data.data;
}

/** 上架（032 门禁 + 001 审批接线）。 */
export async function publishTemplate(templateId: string): Promise<TemplateSummary> {
  const { data } = await apiClient.post<ApiEnvelope<TemplateSummary>>(
    `/api/v1/templates/${templateId}/publish`,
  );
  return data.data;
}

/** 下架（不伤副本）。 */
export async function unpublishTemplate(templateId: string): Promise<TemplateSummary> {
  const { data } = await apiClient.post<ApiEnvelope<TemplateSummary>>(
    `/api/v1/templates/${templateId}/unpublish`,
  );
  return data.data;
}

/** 克隆模板到克隆者名下。 */
export async function cloneTemplate(
  templateId: string,
  payload: { cloner_id: string; name?: string },
): Promise<{ clone: TemplateCloneRecord; target_type: string; target_key: string }> {
  const { data } = await apiClient.post<
    ApiEnvelope<{ clone: TemplateCloneRecord; target_type: string; target_key: string }>
  >(`/api/v1/templates/${templateId}/clone`, payload);
  return data.data;
}

/** 副本手动升级。 */
export async function upgradeTemplate(
  templateId: string,
  payload: { operator_id: string; target_type: string; target_key: string },
): Promise<Record<string, unknown>> {
  const { data } = await apiClient.post<ApiEnvelope<Record<string, unknown>>>(
    `/api/v1/templates/${templateId}/upgrade`,
    payload,
  );
  return data.data;
}

/** 克隆记录查询。 */
export async function fetchClones(templateId: string): Promise<TemplateCloneRecord[]> {
  const { data } = await apiClient.get<ApiEnvelope<{ items: TemplateCloneRecord[]; total: number }>>(
    `/api/v1/templates/${templateId}/clones`,
  );
  return data.data.items;
}
