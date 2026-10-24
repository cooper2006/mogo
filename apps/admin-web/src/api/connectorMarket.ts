import { apiClient } from './client';

/**
 * 041-connector-market: 连接器市场前端 API 客户端。
 *
 * 后端 `services/admin-api/app/api/routes/connector_market.py` 的端点：
 * 模板目录（含分类 / 本租户安装计数 / 已安装标记）、模板详情、
 * 从模板创建连接器、已安装列表。
 */

export interface LocalizedText {
  zh: string;
  en: string;
}

export interface ConnectorParamDto {
  key: string;
  label: LocalizedText;
  type: string;
  required: boolean;
  secret: boolean;
  in: 'path' | 'query' | 'body' | 'headers';
  description: LocalizedText;
  example?: string;
}

export interface ConnectorTemplateDto {
  id: string;
  version: number;
  category: string;
  name: LocalizedText;
  description: LocalizedText;
  authType: 'none' | 'bearer' | 'api_key';
  credentialKey: string;
  apiKeyHeader: string;
  credentialManaged: boolean;
  params: ConnectorParamDto[];
  testHint: { probe: LocalizedText; expected_status: number };
  installCount: number;
  installed: boolean;
}

export interface ConnectorCatalogDto {
  templates: ConnectorTemplateDto[];
  /** 后端返回分类 key 列表（如 oa / erp / data / devops / im）。 */
  categories: string[];
  loadIssues: string[];
}

export interface ConnectorInstallDto {
  toolId: string;
  name: string;
  status: string;
  lastTestStatus: string;
  config: Record<string, any>;
  templateId: string;
  templateVersion: number;
  source: 'template' | 'manual';
  installedAt: string;
}

export interface ConnectorInstallPayload {
  name?: string;
  values: Record<string, string>;
  activate?: boolean;
  description?: string;
}

export async function fetchConnectorCatalog(params?: {
  category?: string;
  keyword?: string;
}): Promise<ConnectorCatalogDto> {
  const { data } = await apiClient.get<ConnectorCatalogDto>('/api/connectors/templates', {
    params: { category: params?.category || '', keyword: params?.keyword || '' },
  });
  return data;
}

export async function fetchConnectorTemplate(templateId: string): Promise<ConnectorTemplateDto> {
  const { data } = await apiClient.get<ConnectorTemplateDto>(
    `/api/connectors/templates/${encodeURIComponent(templateId)}`,
  );
  return data;
}

export async function installConnectorTemplate(
  templateId: string,
  payload: ConnectorInstallPayload,
): Promise<{ tool: Record<string, any>; templateId: string; credentialManaged: boolean }> {
  const { data } = await apiClient.post(
    `/api/connectors/templates/${encodeURIComponent(templateId)}/install`,
    payload,
  );
  return data;
}

export async function fetchConnectorInstalls(): Promise<{
  items: ConnectorInstallDto[];
  total: number;
}> {
  const { data } = await apiClient.get<{ items: ConnectorInstallDto[]; total: number }>(
    '/api/connectors/installs',
  );
  return data;
}

export async function fetchConnectorInstallCounts(): Promise<{
  counts: Record<string, number>;
  total: number;
}> {
  const { data } = await apiClient.get<{ counts: Record<string, number>; total: number }>(
    '/api/connectors/installs/counts',
  );
  return data;
}
