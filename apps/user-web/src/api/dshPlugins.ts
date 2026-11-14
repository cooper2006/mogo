import { createApiClient } from './client'

export interface DshPlugin {
  id: string
  name: string
  version: string
  spec: string
  description: string
  enabled: boolean
  scope: 'organization' | 'personal'
  engine: 'dsh'
  source: string
  updatedAt?: string
  archive_id?: string
  availability?: PluginAvailability
}

export interface PluginAvailability {
  status: 'verified' | 'session_exposed' | 'not_exposed' | 'unsupported' | 'unverified' | 'failed'
  reason: string
  checks: Record<string, boolean>
  discovered_tools?: string[]
  session_tools?: string[]
}

type Response<T> = { code: number; data: T }
const api = createApiClient({ baseURL: '/askai-api/api', timeout: 330000 })
const path = '/dsh-plugins/personal'

export async function listDshPlugins(): Promise<DshPlugin[]> {
  const { data } = await api.get<Response<DshPlugin[]>>(path)
  return data.data
}

export async function installDshPlugin(spec: string): Promise<DshPlugin> {
  const { data } = await api.post<Response<DshPlugin>>(`${path}/install`, { spec })
  return data.data
}

export async function uploadDshPlugin(file: File): Promise<DshPlugin> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post<Response<DshPlugin>>(`${path}/upload`, form)
  return data.data
}

export async function verifyDshPlugin(id: string): Promise<DshPlugin> {
  const { data } = await api.post<Response<DshPlugin>>(`${path}/${encodeURIComponent(id)}/verify`, {})
  return data.data
}

export async function setDshPluginEnabled(id: string, enabled: boolean): Promise<DshPlugin> {
  const { data } = await api.patch<Response<DshPlugin>>(`${path}/${encodeURIComponent(id)}/enabled`, { enabled })
  return data.data
}

export async function removeDshPlugin(id: string): Promise<void> {
  await api.delete(`${path}/${encodeURIComponent(id)}`)
}
