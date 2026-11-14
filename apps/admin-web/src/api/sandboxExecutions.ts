import { apiClient } from './client';

// ③ Sandbox 执行记录 admin-web 客户端。
// 字段命名严格对齐后端契约（services/admin-api/app/api/routes/sandbox_executions.py）：
// snake_case 直传，不做 camelCase 映射。

/** 单条 Sandbox 执行记录（sandbox_execution_records 扁平文档）。 */
export interface SandboxExecutionRecord {
  record_id: string;
  tenant_id: string;
  user_id: string;
  agent_id: string;
  message_id: string;
  conversation_id: string;
  call_id: string;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  exit_code: number | null;
  status: string;
  rejected: boolean;
  skill_digest: string;
  image_ref: string;
}

/** GET /api/v1/sandbox-executions 信封。 */
export interface SandboxExecutionPage {
  items: SandboxExecutionRecord[];
  total: number;
  page: number;
  page_size: number;
  degraded?: boolean;
  reason?: string;
}

export async function fetchSandboxExecutions(
  params: { page?: number; page_size?: number; agent_id?: string; status?: string } = {},
) {
  const { data } = await apiClient.get<SandboxExecutionPage>('/api/v1/sandbox-executions', { params });
  return data;
}

export async function fetchSandboxExecution(recordId: string) {
  const { data } = await apiClient.get<SandboxExecutionRecord>(
    `/api/v1/sandbox-executions/${encodeURIComponent(recordId)}`,
  );
  return data;
}
