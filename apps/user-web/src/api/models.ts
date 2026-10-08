import { createApiClient } from './client'

const client = createApiClient({
  baseURL: '/askai-api',
  timeout: 15000,
})

export interface ChatModelOption {
  id: string
  displayName: string
  modelName: string
  providerName: string
  providerType: string
  runtimeKind?: string
  capabilities?: string[]
  isDefault: boolean
  healthStatus: string
}

export async function fetchChatModels(tenantId = 'default'): Promise<ChatModelOption[]> {
  const response = await client.get('/api/models/available', { params: { tenant_id: tenantId, capability: 'chat' } })
  return Array.isArray(response.data) ? response.data : response.data?.data || []
}

export async function fetchImageModels(tenantId = 'default'): Promise<ChatModelOption[]> {
  const response = await client.get('/api/models/images/available', { params: { tenant_id: tenantId } })
  return Array.isArray(response.data) ? response.data : response.data?.data || []
}
