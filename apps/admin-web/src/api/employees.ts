import { apiClient } from './client';

/** 051 数字员工（B1 前端）。admin-api 契约见 services/admin-api/app/api/routes/employees.py。 */

export type EmployeeStatus = 'active' | 'disabled' | 'archived';
export type EmployeeCapabilityKey =
  | 'content_generation'
  | 'image_generation'
  | 'code_generation'
  | 'browser_automation'
  | 'internal_knowledge';
export type EmployeeAccessMode = 'all' | 'selected';
export type EmployeeMemoryScope = 'personal' | 'project' | 'department';

export interface EmployeeCapabilities {
  content_generation: boolean;
  image_generation: boolean;
  code_generation: boolean;
  browser_automation: boolean;
  internal_knowledge: boolean;
}

export interface EmployeeItem {
  id: string;
  name: string;
  description: string;
  status: EmployeeStatus;
  capabilities: EmployeeCapabilities;
  toolAccessMode: EmployeeAccessMode;
  toolIds: string[];
  skillAccessMode: EmployeeAccessMode;
  skillIds: string[];
  knowledgeBaseIds: string[];
  memoryScope: EmployeeMemoryScope;
  modelConfig: Record<string, any>;
  harnessProfileRef: string;
  creatorId: string;
  memberUserIds: string[];
  createdAt: string;
  updatedAt: string;
  deletedAt?: string;
}

export interface EmployeePayload {
  name: string;
  description: string;
  status: EmployeeStatus;
  capabilities: Record<string, boolean>;
  toolAccessMode: EmployeeAccessMode;
  toolIds: string[];
  skillAccessMode: EmployeeAccessMode;
  skillIds: string[];
  knowledge_base_ids: string[];
  memory_scope: EmployeeMemoryScope;
  model_settings: Record<string, any>;
  harness_profile_ref: string;
  member_user_ids: string[];
}

export interface EmployeeCatalogResource {
  id: string;
  name: string;
  type: string;
}

export interface EmployeeCatalogResources {
  tools: EmployeeCatalogResource[];
  skills: EmployeeCatalogResource[];
}

export interface EmployeeListPage {
  items: EmployeeItem[];
  total: number;
}

export async function listEmployees(): Promise<EmployeeListPage> {
  const { data } = await apiClient.get<EmployeeListPage>('/api/v1/employees');
  return data;
}

export async function getEmployee(id: string): Promise<EmployeeItem> {
  const { data } = await apiClient.get<EmployeeItem>(`/api/v1/employees/${id}`);
  return data;
}

export async function createEmployee(payload: EmployeePayload): Promise<EmployeeItem> {
  const { data } = await apiClient.post<EmployeeItem>('/api/v1/employees', payload);
  return data;
}

export async function updateEmployee(id: string, payload: EmployeePayload): Promise<EmployeeItem> {
  const { data } = await apiClient.put<EmployeeItem>(`/api/v1/employees/${id}`, payload);
  return data;
}

export async function setEmployeeStatus(id: string, status: EmployeeStatus): Promise<{ success: boolean }> {
  const { data } = await apiClient.patch<{ success: boolean }>(`/api/v1/employees/${id}/status`, { status });
  return data;
}

export async function deleteEmployee(id: string): Promise<{ success: boolean }> {
  const { data } = await apiClient.delete<{ success: boolean }>(`/api/v1/employees/${id}`);
  return data;
}

export async function getEmployeeCatalogResources(): Promise<EmployeeCatalogResources> {
  const { data } = await apiClient.get<EmployeeCatalogResources>('/api/v1/employees/catalog/resources');
  return data;
}
