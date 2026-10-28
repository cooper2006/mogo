import { apiClient } from './client';

export interface EvalCase {
  id: string;
  agentTag: string;
  input: string;
  expectations: string[];
  expectedRefs: string[];
  expectRefusal: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface EvalCasePayload {
  input: string;
  expectations: string[];
  expectedRefs: string[];
  expectRefusal: boolean;
  agentTag: string;
}

export interface EvalMetrics {
  citation_support: number;
  refusal_accuracy: number;
  task_success: number;
}

export interface EvalPolicy {
  tenantId: string;
  skillId: string | null;
  minCitationSupport: number;
  minRefusalAccuracy: number;
  minTaskSuccess: number;
  minCases: number;
  maxCases: number;
  timeoutSeconds: number;
  enabled: boolean;
}

export interface EvalReport {
  id: string;
  dryRun: boolean;
  passed: boolean;
  metrics: EvalMetrics;
  thresholds: Partial<EvalMetrics> & Record<string, any>;
  failedMetrics: string[];
  blockedReason: string;
  durationMs: number;
  caseResults: Array<Record<string, any>>;
  createdAt: string;
}

export interface EvalCaseResultView {
  caseId: string;
  kind: string;
  citationSupport: boolean | null;
  refusalAccuracy: boolean | null;
  taskSuccess: boolean | null;
  reasons: string[];
  durationMs: number;
}

// ---------------------------------------------------------------------------
// test-set CRUD (US1)
// ---------------------------------------------------------------------------

export async function listEvalCases(skillId: string, agentTag?: string): Promise<EvalCase[]> {
  const { data } = await apiClient.get<{ items: EvalCase[] }>(`/api/v1/skills/${skillId}/eval/cases`, {
    params: agentTag ? { agent_tag: agentTag } : undefined,
  });
  return data.items ?? [];
}

export async function createEvalCase(skillId: string, payload: EvalCasePayload): Promise<EvalCase> {
  const { data } = await apiClient.post<EvalCase>(`/api/v1/skills/${skillId}/eval/cases`, payload);
  return data;
}

export async function updateEvalCase(skillId: string, caseId: string, payload: EvalCasePayload): Promise<EvalCase> {
  const { data } = await apiClient.put<EvalCase>(`/api/v1/skills/${skillId}/eval/cases/${caseId}`, payload);
  return data;
}

export async function deleteEvalCase(skillId: string, caseId: string): Promise<{ deleted: boolean }> {
  const { data } = await apiClient.delete<{ deleted: boolean }>(`/api/v1/skills/${skillId}/eval/cases/${caseId}`);
  return data;
}

// ---------------------------------------------------------------------------
// dry-run + reports (US2 / US3)
// ---------------------------------------------------------------------------

export async function dryRunEval(skillId: string, model?: string): Promise<EvalReport> {
  const { data } = await apiClient.post<EvalReport>(`/api/v1/skills/${skillId}/eval/dry-run`, { model }, { timeout: 300000 });
  return data;
}

export async function fetchLatestEvalReport(skillId: string): Promise<EvalReport | null> {
  try {
    const { data } = await apiClient.get<EvalReport>(`/api/v1/skills/${skillId}/eval/reports/latest`);
    return data;
  } catch (e: any) {
    if (e?.response?.status === 404) return null;
    throw e;
  }
}

export async function fetchEvalReports(skillId: string, limit = 5): Promise<EvalReport[]> {
  const { data } = await apiClient.get<{ items: EvalReport[] }>(`/api/v1/skills/${skillId}/eval/reports`, { params: { limit } });
  return data.items ?? [];
}

// ---------------------------------------------------------------------------
// policy (US3)
// ---------------------------------------------------------------------------

export async function fetchEvalPolicy(skillId: string): Promise<EvalPolicy> {
  const { data } = await apiClient.get<EvalPolicy>(`/api/v1/skills/${skillId}/eval/policy`);
  return data;
}

export async function updateEvalPolicy(skillId: string, payload: Partial<EvalPolicy>): Promise<EvalPolicy> {
  const { data } = await apiClient.put<EvalPolicy>(`/api/v1/skills/${skillId}/eval/policy`, payload);
  return data;
}