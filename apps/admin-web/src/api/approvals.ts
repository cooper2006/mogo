import { apiClient } from './client';

export type ApprovalSourceType = 'tool' | 'portal' | 'sop';

export interface ApprovalTodo {
  ticketId: string;
  sourceType: ApprovalSourceType;
  sourceId: string;
  approverId: string;
  deadline: string;
  state: string;
  runId?: string;
  nodeId?: string;
}

export interface ApprovalTodoList {
  items: ApprovalTodo[];
  total: number;
  shadowOnly: boolean;
  kernelEnabled: boolean;
}

export interface FetchApprovalTodosParams {
  tenantId?: string;
  approver?: string;
  status?: 'pending' | 'all';
}

/**
 * 056 — 统一审批待办列表（管理端浏览器调用，使用管理员 JWT）。
 * 路径相对 apiClient 的 baseURL（/admin-api/api/v1），即 /admin/approvals/todos/admin。
 */
export async function fetchApprovalTodos(
  params: FetchApprovalTodosParams = {},
): Promise<ApprovalTodoList> {
  const { data } = await apiClient.get<{
    code: number;
    message: string;
    data: ApprovalTodoList;
  }>('/api/v1/admin/approvals/todos/admin', { params });
  return data.data;
}
