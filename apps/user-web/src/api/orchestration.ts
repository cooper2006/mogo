import { createApiClient } from './client'
import type { CanvasDocument } from '../components/orchestration/canvasSchema'

/**
 * 可视化编排画布 —— 端用户侧读写 API（特性 039）。
 *
 * 对应 chat-api `services/chat-api/app/api/endpoints/orchestrations.py`
 * （prefix `/api/orchestrations`）。与 010 引擎联动：`document` 保存后可由
 * `load_orchestration_persisted` 原样装载并被引擎真实执行；发布走 001
 * `orchestration:publish` 权限码门禁（画布不绕过 gatekeeper）。
 */

const api = createApiClient({ baseURL: '/askai-api/api', timeout: 60000 })
const dataOf = <T>(res: { data?: any }): T => res.data?.data ?? res.data

export type OrchestrationStatus = 'draft' | 'published'

export interface OrchestrationOverview {
  orchestrationId: string
  version: number
  status: OrchestrationStatus
  mode?: string
  updatedAt?: string | null
  detail?: {
    orchestrationId?: string
    version?: string
    mode?: string
    nodeCount?: number
    edgeCount?: number
  }
}

export interface OrchestrationDetail {
  orchestrationId: string
  version: number
  status: OrchestrationStatus
  document: CanvasDocument
  layout: Record<string, { x: number; y: number }>
  history: Array<{ version: number; status: OrchestrationStatus; updatedAt?: string; releaseNotes?: string }>
  updatedAt?: string | null
}

export interface SaveDraftResult {
  orchestrationId: string
  version: number
  status: OrchestrationStatus
}

/** 当前用户可见的编排清单。 */
export async function listOrchestrations(): Promise<OrchestrationOverview[]> {
  return dataOf<OrchestrationOverview[]>(await api.get('/orchestrations'))
}

/** 读取单个编排（文档 + 投影布局 + 版本历史）。 */
export async function fetchOrchestration(orchestrationId: string): Promise<OrchestrationDetail> {
  return dataOf<OrchestrationDetail>(await api.get(`/orchestrations/${encodeURIComponent(orchestrationId)}`))
}

/** 保存草稿（编排权 = 本人；校验与 010 引擎同口径）。 */
export async function saveOrchestrationDraft(
  orchestrationId: string,
  canvas: CanvasDocument,
  layout: Record<string, { x: number; y: number }> = {},
): Promise<SaveDraftResult> {
  return dataOf<SaveDraftResult>(
    await api.post(`/orchestrations/${encodeURIComponent(orchestrationId)}/drafts`, {
      document: canvas,
      layout,
    }),
  )
}

/** 发布（001 权限码 `orchestration:publish` 门禁，未持有返回 403）。 */
export async function publishOrchestration(
  orchestrationId: string,
  canvas: CanvasDocument,
  layout: Record<string, { x: number; y: number }> = {},
  releaseNotes = '',
): Promise<SaveDraftResult> {
  return dataOf<SaveDraftResult>(
    await api.post(`/orchestrations/${encodeURIComponent(orchestrationId)}/publish`, {
      document: canvas,
      layout,
      releaseNotes,
    }),
  )
}

/** 从 API 错误中提取可展示的消息（后端 422/403 detail 或网络错误）。 */
export function errorMessage(error: unknown, fallback: string): string {
  const err = error as { response?: { data?: { detail?: string; message?: string } }; message?: string }
  return err?.response?.data?.detail || err?.response?.data?.message || err?.message || fallback
}