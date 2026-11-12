import { createApiClient } from './client'
import { errorMessage } from './orchestration'

/**
 * 编排运行与审批待办 —— 端用户侧 API（特性 050）。
 *
 * 对应 chat-api `services/chat-api/app/api/endpoints/orchestration_runs.py`
 * （prefix `/api/v1/orchestration-runs`）。待办按当前 principal 的
 * tenant + approver 过滤；决策走 `POST /{run_id}/decisions`。
 *
 * 契约要点：
 * - body 键用 camelCase `nodeId`（后端 `DecisionPayload` 只有 validation_alias，
 *   无 populate_by_name，snake_case 会被 422 拒绝）；
 * - 不传 userId/tenantId —— 后端 `_assert_end_user_scope` 对请求体里出现的
 *   身份字段做一致性校验，身份一律来自 Bearer 会话。
 */

const api = createApiClient({ baseURL: '/askai-api/api/v1', timeout: 30000 })
const dataOf = <T>(res: { data?: any }): T => res.data?.data ?? res.data

export type ApprovalDecision = 'approve' | 'reject'

export interface OrchestrationTodo {
  run_id: string
  orchestration_id: string
  node_id: string
  initiator_id: string
  approver: string
  prompt?: string
  on_reject?: string | null
  created_at?: string | null
  deadline?: string | null
  /** 后端渲染好的可读提醒文本（notifications.render_approval_reminder）。 */
  rendered?: string
}

export interface DecisionOutcome {
  runId: string
  nodeId: string
  decision: ApprovalDecision
  status: string
}

/** 当前用户作为审批人的跨运行待办列表（050 R-4 站内待办入口）。 */
export async function listApprovalTodos(): Promise<OrchestrationTodo[]> {
  return dataOf<OrchestrationTodo[]>(await api.get('/orchestration-runs/todos'))
}

/**
 * 决策请求体构造（纯函数，供 `decideApproval` 与单测共用）。
 * 键必须是 camelCase `nodeId`（后端 validation_alias 口径），且不得携带
 * userId/tenantId（身份来自 Bearer 会话，body 出现即 403）。
 */
export function buildDecisionPayload(decision: ApprovalDecision, reason: string, nodeId: string) {
  return { decision, reason, nodeId }
}

/** 提交审批决策（批准 / 驳回；驳回 reason 必填，否则后端 403 fail-closed）。 */
export async function decideApproval(
  runId: string,
  payload: { decision: ApprovalDecision; reason: string; nodeId: string }
): Promise<DecisionOutcome> {
  return dataOf<DecisionOutcome>(
    await api.post(
      `/orchestration-runs/${encodeURIComponent(runId)}/decisions`,
      buildDecisionPayload(payload.decision, payload.reason, payload.nodeId)
    )
  )
}

export { errorMessage }
