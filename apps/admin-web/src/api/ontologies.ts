import { apiClient } from './client';

/**
 * 本体数据权限 API（设计 §5.7 / §5.9）。
 *
 * 对应后端 `services/admin-api/app/api/routes/ontologies.py`（prefix `/ontologies`）。
 * 「本体清单」只做展示，**不提供本体 CRUD**（本体定义与数据都在业务系统）。
 */

export type OntologyCatalogItem = {
  ontologyId: string;
  entityCount: number;
  entityTypes: string[];
  grantCount: number;
};

export type OntologyPermissionConfig = {
  enforce: boolean;
  defaultMode: 'allow' | 'deny';
  rev: number;
  /** enforce=true 时固定为 deny；enforce=false 时等于 defaultMode。 */
  effectiveDefault: 'allow' | 'deny';
};

export type MyOntologyScope = {
  tenantId: string;
  userId: string;
  ontologies: string[];
  count: number;
};

export type OntologyGrant = {
  id: string;
  subjectType: 'tenant' | 'org' | 'role' | 'user';
  subjectId: string;
  ontologyId: string;
  accessMode: 'none' | 'read' | 'write';
  priority: number;
  enabled: boolean;
  remark: string;
  updatedAt: string;
};

export type OntologyClassDetail = {
  id: string;
  subjectType: string;
  subjectId: string;
  ontologyId: string;
  className: string;
  accessMode: 'inherit' | 'none' | 'read' | 'write';
  columnMode: 'all' | 'selected';
  columnList: string[];
  rowCondition: unknown;
  priority: number;
  enabled: boolean;
  remark: string;
  updatedAt: string;
};

export type SubjectPermissionBundle = {
  subjectType: string;
  subjectId: string;
  grants: OntologyGrant[];
  details: OntologyClassDetail[];
};

export type GrantPayload = {
  ontologyIds: string[];
  accessMode?: 'none' | 'read' | 'write';
  priority?: number;
  remark?: string;
};

export type OntologySyncResult = {
  source: string;
  synced: number;
  pushed: number;
  ontologies: OntologyCatalogItem[];
  note: string;
};

/** 当前账号可见的本体清单（登录即可）。 */
export async function fetchMyOntologies(): Promise<MyOntologyScope> {
  return (await apiClient.get('/api/ontologies/mine')).data;
}

/** 全量本体清单（授权时勾选）。 */
export async function fetchOntologyCatalog(): Promise<OntologyCatalogItem[]> {
  return (await apiClient.get('/api/ontologies')).data;
}

/** 同步只读副本（业务系统未接入时按 MOGO 侧索引聚合）。 */
export async function syncOntologies(): Promise<OntologySyncResult> {
  return (await apiClient.post('/api/ontologies/sync', { ontologies: [] })).data;
}

export async function fetchOntologyPermissionConfig(): Promise<OntologyPermissionConfig> {
  return (await apiClient.get('/api/ontologies/config')).data;
}

export async function updateOntologyPermissionConfig(payload: {
  enforce: boolean;
  defaultMode?: 'allow' | 'deny';
}): Promise<OntologyPermissionConfig> {
  return (await apiClient.put('/api/ontologies/config', payload)).data;
}

export async function fetchUserOntologyPermissions(userId: string): Promise<SubjectPermissionBundle> {
  return (await apiClient.get(`/api/ontologies/users/${userId}/permissions`)).data;
}

export async function grantUserOntologyPermissions(
  userId: string,
  payload: GrantPayload,
): Promise<{ granted: number; ontologyIds: string[] }> {
  return (await apiClient.post(`/api/ontologies/users/${userId}/permissions`, payload)).data;
}

export async function revokeUserOntologyPermission(
  userId: string,
  ontologyId: string,
): Promise<{ deleted: number; detailsDeleted: number }> {
  return (await apiClient.delete(`/api/ontologies/users/${userId}/permissions/${encodeURIComponent(ontologyId)}`)).data;
}

/** 四态主体（tenant / org / role / user）通用读写，供后续扩展使用。 */
export async function fetchSubjectOntologyPermissions(
  subjectType: string,
  subjectId: string,
): Promise<SubjectPermissionBundle> {
  return (await apiClient.get(`/api/ontologies/subjects/${subjectType}/${subjectId}/permissions`)).data;
}

export async function grantSubjectOntologyPermissions(
  subjectType: string,
  subjectId: string,
  payload: GrantPayload,
): Promise<{ granted: number; ontologyIds: string[] }> {
  return (await apiClient.post(`/api/ontologies/subjects/${subjectType}/${subjectId}/permissions`, payload)).data;
}

export async function revokeSubjectOntologyPermission(
  subjectType: string,
  subjectId: string,
  ontologyId: string,
): Promise<{ deleted: number; detailsDeleted: number }> {
  return (
    await apiClient.delete(
      `/api/ontologies/subjects/${subjectType}/${subjectId}/permissions/${encodeURIComponent(ontologyId)}`,
    )
  ).data;
}
