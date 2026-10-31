import { apiClient, redirectToLogin } from './client';
import { useAuthStore } from '@/stores/auth';

export type ModelStatus = 'active' | 'disabled';
export type HealthStatus = 'unknown' | 'healthy' | 'failed';
export type ImageRuntimeKind = 'openai_images' | 'azure_openai_images' | 'dashscope_image' | 'custom_images';
export interface ModelPricing { currency: 'CNY' | 'USD'; inputPerMillion: number; outputPerMillion: number }

/**
 * 供应商协议类型全集（后端 `provider_type` 枚举）。
 *
 * 后端 `ModelDiscoverPayload.providerType` 用正则
 * `^(openai_compatible|azure_openai|anthropic|gemini|ollama)$` 约束，
 * 种子 `DEFAULT_PROVIDERS` 也覆盖这五类；此处是前端唯一权威声明，
 * 首次配置向导（api/setup.ts）与模型管理页（api/models.ts）共用，
 * 避免两处各自抄一份而漏改（031 曾因 setup.ts 漏改导致 typecheck 报错）。
 */
export type ModelProviderType = 'openai_compatible' | 'azure_openai' | 'anthropic' | 'gemini' | 'ollama';

const IMAGE_MODEL_TEST_TIMEOUT_MS = 10 * 60 * 1000;

export interface ImageModelSettings {
  size?: string;
  quality?: string;
  outputFormat?: string;
  responseFormat?: string;
  n?: number | null;
  ratio?: string;
  requestPath?: string;
  responseUrlPath?: string;
  responseBase64Path?: string;
  extraParamsJson?: string;
  apiStyle?: 'v1' | 'deployment';
  includeApiVersion?: boolean;
}

export interface ModelProviderItem {
  id: string;
  name: string;
  code: string;
  providerType: ModelProviderType;
  defaultBaseUrl: string;
  authType: string;
  status: ModelStatus;
  updatedAt: string;
}

export interface ModelInstanceItem {
  id: string;
  groupId?: string;
  tenantId: string;
  providerId: string;
  providerName: string;
  providerCode: string;
  providerType: string;
  orgId: string;
  displayName: string;
  modelName: string;
  baseUrl: string;
  apiVersion: string;
  apiKeyMasked: string;
  apiSecretMasked: string;
  capabilities: string[];
  runtimeKind: ImageRuntimeKind | '';
  imageSettings: ImageModelSettings;
  maxContextTokens: number;
  status: ModelStatus;
  healthStatus: HealthStatus;
  lastError: string;
  isDefault: boolean;
  priority: number;
  pricing?: ModelPricing | null;
  updatedAt: string;
}

export interface ModelInstancePayload {
  providerId: string;
  groupId?: string;
  orgId: string;
  displayName: string;
  modelName: string;
  baseUrl: string;
  apiVersion: string;
  apiKey: string;
  apiSecret?: string;
  capabilities: string[];
  runtimeKind?: ImageRuntimeKind | '';
  imageSettings?: ImageModelSettings;
  maxContextTokens?: number;
  status: ModelStatus;
  isDefault: boolean;
  priority?: number;
  pricing?: ModelPricing | null;
}

export async function fetchModelProviders() {
  const { data } = await apiClient.get<ModelProviderItem[]>('/api/v1/models/providers');
  return data;
}

export async function fetchModelInstances() {
  const { data } = await apiClient.get<ModelInstanceItem[]>('/api/v1/models/instances');
  return data;
}

export async function createModelInstance(payload: ModelInstancePayload) {
  const { data } = await apiClient.post<ModelInstanceItem>('/api/v1/models/instances', payload);
  return data;
}

export async function updateModelInstance(id: string, payload: ModelInstancePayload) {
  const { data } = await apiClient.put<ModelInstanceItem>(`/api/v1/models/instances/${id}`, payload);
  return data;
}

export async function deleteModelInstance(id: string) {
  const { data } = await apiClient.delete<{ success: boolean }>(`/api/v1/models/instances/${id}`);
  return data;
}

export async function setDefaultModelInstance(id: string) {
  const { data } = await apiClient.post<{ success: boolean }>(`/api/v1/models/instances/${id}/default`);
  return data;
}

export async function testModelInstance(id: string) {
  const { data } = await apiClient.post<{ success: boolean; status: string; message: string }>(
    `/api/v1/models/instances/${id}/test`,
  );
  return data;
}

export async function testModelVision(id: string): Promise<boolean> {
  const { data } = await apiClient.post<{ supported: boolean }>(`/api/v1/models/instances/${id}/test-vision`);
  return data.supported === true;
}

export async function enableModelVision(id: string): Promise<void> {
  await apiClient.post(`/api/v1/models/instances/${id}/enable-vision`);
}

export async function testImageModelInstance(id: string, prompt: string) {
  const { data } = await apiClient.post<{
    success: boolean;
    status: string;
    message: string;
    imageUrl?: string;
    providerType?: string;
    runtimeKind?: string;
  }>(`/api/v1/models/instances/${id}/test-image`, { prompt }, { timeout: IMAGE_MODEL_TEST_TIMEOUT_MS });
  return data;
}

export async function testKnowledgeModelInstance(id: string, capability: 'embedding' | 'rerank') {
  const { data } = await apiClient.post<{
    success: boolean;
    status: string;
    message: string;
    capability: 'embedding' | 'rerank';
    dimension?: number;
  }>(`/api/v1/models/instances/${id}/test-knowledge`, { capability });
  return data;
}

export async function streamModelInstanceTest(
  id: string,
  prompt: string,
  onEvent: (event: { type: string; content?: string; message?: string }) => void,
) {
  const authStore = useAuthStore();
  const baseURL = import.meta.env.VITE_ADMIN_API_BASE_URL || '/admin-api';
  const response = await fetch(`${baseURL}/api/models/instances/${id}/test/stream`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${authStore.token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ prompt }),
  });
  if (response.status === 401 || response.status === 403) {
    const isPlatformAdmin = authStore.isPlatformAdmin;
    authStore.clearSession();
    redirectToLogin(isPlatformAdmin);
    throw new Error('认证已过期，请重新登录');
  }
  if (!response.ok || !response.body) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop() || '';
    for (const part of parts) {
      const line = part
        .split('\n')
        .find((item) => item.startsWith('data:'));
      if (!line) {
        continue;
      }
      onEvent(JSON.parse(line.slice(5).trim()));
    }
  }
}

export interface DiscoveredModel {
  id: string;
  name: string;
  ownedBy?: string;
}

/**
 * 代理探测 provider 真实可用的模型列表（参考 dsh 的模型库交互）。
 * OpenAI 兼容走 `/v1/models`，Azure 走 deployments 列表。返回该账户可调用的模型，
 * 供「新增模型配置」中「获取模型列表」直接点选，免去手填模型 ID。
 */
export async function discoverProviderModels(payload: {
  providerType: ModelProviderType;
  baseUrl: string;
  apiKey: string;
  apiVersion?: string;
  // 编辑已保存配置且未重填 Key 时带上实例 ID，后端复用已存密钥解密，免去每次重输
  instanceId?: string;
}): Promise<DiscoveredModel[]> {
  const { data } = await apiClient.post<{ models: DiscoveredModel[] }>('/api/v1/models/discover', payload);
  return data?.models ?? [];
}

export interface ModelGroupItem {
  id: string;
  name: string;
  providerId: string;
  baseUrl: string;
  apiVersion: string;
  apiKeyMasked: string;
  status: ModelStatus;
}

export interface ModelGroupPayload {
  name: string;
  providerId: string;
  baseUrl: string;
  apiVersion: string;
  apiKey: string;
  status: ModelStatus;
}

export async function fetchModelGroups() {
  const { data } = await apiClient.get<ModelGroupItem[]>('/api/v1/models/groups');
  return data;
}

export async function createModelGroup(payload: ModelGroupPayload) {
  const { data } = await apiClient.post<ModelGroupItem>('/api/v1/models/groups', payload);
  return data;
}

export async function updateModelGroup(id: string, payload: ModelGroupPayload) {
  const { data } = await apiClient.put<ModelGroupItem>(`/api/v1/models/groups/${id}`, payload);
  return data;
}

export async function deleteModelGroup(id: string) {
  await apiClient.delete(`/api/v1/models/groups/${id}`);
}
