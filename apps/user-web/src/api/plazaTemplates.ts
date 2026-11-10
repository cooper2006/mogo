/**
 * 053-plaza-template-distribution —— 用户侧模板广场 API。
 *
 * 走 chat-api 既有 ``/askai-api`` 前缀（``end_user`` 会话，Authorization 由
 * ``createApiClient`` 统一注入）；租户由会话决定，前端**不传** tenantId。
 *
 * 后端契约见 ``services/chat-api/app/api/endpoints/plaza_templates.py``。
 */
import { createApiClient } from './client'

const api = createApiClient({ baseURL: '/askai-api/api', timeout: 30000 })

export type PlazaTemplateType = 'employee_template' | 'sop_template'

export interface PlazaTemplateItem {
  template_id: string
  name: string
  asset_type: PlazaTemplateType
  version: number
  state: string
  category: string
  description: string
  owner_id: string
  updated_at: string | null
}

export interface PlazaTemplateDetail extends PlazaTemplateItem {
  content: Record<string, unknown>
  gate_report: Record<string, unknown>
  versions: Array<Record<string, unknown>>
}

/** 模板广场目录（租户内已上架模板，只读）。 */
export async function fetchPlazaTemplates(
  params?: { asset_type?: PlazaTemplateType },
): Promise<{ items: PlazaTemplateItem[]; total: number }> {
  const { data } = await api.get<{
    code: number
    message: string
    data: { items: PlazaTemplateItem[]; total: number }
  }>('/v1/plaza/templates', { params: params as Record<string, string> | undefined })
  return data.data
}

/** 模板详情（含版本序列）。 */
export async function fetchPlazaTemplate(templateId: string): Promise<PlazaTemplateDetail> {
  const { data } = await api.get<{
    code: number
    message: string
    data: PlazaTemplateDetail
  }>(`/v1/plaza/templates/${templateId}`)
  return data.data
}
