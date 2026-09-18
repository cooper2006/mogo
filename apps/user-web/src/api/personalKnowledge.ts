import { createApiClient } from './client'

const api = createApiClient({ baseURL: '/askai-api/api', timeout: 120000 })
const dataOf = <T>(res: { data?: any }): T => res.data?.data ?? res.data

export interface KnowledgeDirectory { id: string; name: string; parentId: string; count: number; children: KnowledgeDirectory[] }
export interface PersonalKnowledge {
  id: string; ownerUserId: string; directoryId: string; name: string; description: string
  tags: string[]; status: string; error: string; activeDocumentId: string
  canReshare: boolean; accessStatus: 'owner' | 'active' | 'revoked' | 'deleted'; grantedByUserId: string
  owner?: { displayName?: string; username?: string }; grantedBy?: { displayName?: string; username?: string }
  seen: boolean; sharedAt: string; createdAt: string; updatedAt: string; deleted?: boolean; deletedAt?: string; isOwner?: boolean; canShare?: boolean
  feedback?: { unreadCount: number; latestUnreadAt: string }
  share?: { shared: boolean; recipientCount: number }
}
export interface KnowledgeGrant { userId: string; user?: { displayName?: string; username?: string }; grantedByUserId: string; grantedBy?: { displayName?: string; username?: string }; canReshare: boolean; status: string }

export async function fetchKnowledgeDirectories() {
  return dataOf<{ items: KnowledgeDirectory[]; rootCount: number }>(await api.get('/personal-knowledge/directories'))
}
export async function createKnowledgeDirectory(name: string, parentId = '') {
  return dataOf(await api.post('/personal-knowledge/directories', { name, parentId }))
}
export async function updateKnowledgeDirectory(id: string, name: string, parentId = '') {
  return dataOf(await api.patch(`/personal-knowledge/directories/${encodeURIComponent(id)}`, { name, parentId }))
}
export async function deleteKnowledgeDirectory(id: string) {
  return dataOf(await api.delete(`/personal-knowledge/directories/${encodeURIComponent(id)}`))
}
export async function fetchPersonalKnowledge(view: 'mine' | 'shared', directoryId = 'all', keyword = '', page = 1, pageSize = 12) {
  return dataOf<{ items: PersonalKnowledge[]; total: number; page: number; pageSize: number }>(await api.get('/personal-knowledge', { params: { view, directoryId, keyword, page, pageSize } }))
}
export async function fetchPersonalKnowledgeItem(id: string) {
  return dataOf<PersonalKnowledge>(await api.get(`/personal-knowledge/${encodeURIComponent(id)}`))
}
export async function uploadPersonalKnowledge(files: File[], directoryId = '', tags = '', onProgress?: (value: number) => void) {
  const form = new FormData()
  files.forEach(file => form.append('files', file))
  form.append('directoryId', directoryId); form.append('tags', tags)
  return dataOf<{ items: PersonalKnowledge[] }>(await api.post('/personal-knowledge', form, {
    onUploadProgress: event => onProgress?.(event.total ? Math.round(event.loaded * 100 / event.total) : 0),
  }))
}
export async function updatePersonalKnowledge(id: string, payload: Partial<Pick<PersonalKnowledge, 'name' | 'description' | 'tags' | 'directoryId'>>) {
  return dataOf<PersonalKnowledge>(await api.patch(`/personal-knowledge/${encodeURIComponent(id)}`, payload))
}
export async function relearnPersonalKnowledge(id: string) {
  return dataOf(await api.post(`/personal-knowledge/${encodeURIComponent(id)}/relearn`))
}
export async function replacePersonalKnowledge(id: string, file: File) {
  const form = new FormData(); form.append('file', file)
  return dataOf(await api.post(`/personal-knowledge/${encodeURIComponent(id)}/replace`, form))
}
export async function deletePersonalKnowledge(id: string) {
  return dataOf(await api.delete(`/personal-knowledge/${encodeURIComponent(id)}`))
}
export async function dismissDeletedPersonalKnowledge(id: string) {
  return dataOf(await api.delete(`/personal-knowledge/${encodeURIComponent(id)}/shared-record`))
}
export async function askPersonalKnowledge(id: string, query: string) {
  return dataOf<{ answer: string; citations: any[]; usedChunks: any[] }>(await api.post(`/personal-knowledge/${encodeURIComponent(id)}/ask`, { query }))
}
export async function fetchKnowledgeGrants(id: string) {
  return dataOf<{ items: KnowledgeGrant[] }>(await api.get(`/personal-knowledge/${encodeURIComponent(id)}/grants`))
}
export async function sharePersonalKnowledge(id: string, recipients: Array<{ userId: string; canReshare: boolean }>) {
  return dataOf(await api.post(`/personal-knowledge/${encodeURIComponent(id)}/grants`, { recipients }))
}
export async function revokePersonalKnowledge(id: string, userId: string, cascade = false) {
  return dataOf(await api.delete(`/personal-knowledge/${encodeURIComponent(id)}/grants/${encodeURIComponent(userId)}`, { params: { cascade } }))
}
export async function updatePersonalKnowledgeGrant(id: string, userId: string, canReshare: boolean) {
  return dataOf(await api.patch(`/personal-knowledge/${encodeURIComponent(id)}/grants/${encodeURIComponent(userId)}`, { canReshare }))
}
export async function fetchPersonalKnowledgeCounts() {
  return dataOf<{ unreadCount: number; shareCount: number; feedbackCount: number }>(await api.get('/personal-knowledge-counts'))
}
