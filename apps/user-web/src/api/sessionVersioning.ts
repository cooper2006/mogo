/**
 * 002 会话版本化 UI API client（commit / versions / share / co-presence）。
 * 与 chat-api `app/api/endpoints/dsh_session_versioning.py` 对应。
 */
import axios from 'axios'

const client = axios.create({ timeout: 30000 })

function authHeaders(authToken?: string | null) {
  return authToken ? { Authorization: `Bearer ${authToken}` } : {}
}

export interface SessionVersion {
  snapshotId: string
  sessionId: string
  seq: number
  trigger: string
  actor: string
  summary: string
  changedRefs: string[]
  attachmentRefs: { name: string; storageRef: string; sizeBytes: number }[]
  createdAt: string | null
  preview?: unknown
}

export interface ShareView {
  share_id: string
  session_id: string
  snapshot_id: string
  visibility: string
  receiver_role: string
  handover: boolean
  active: boolean
  revoked: boolean
  redeemed: boolean
  expires_at: string | null
  changedRefs: string[]
  summary: string
}

export interface PresenceView {
  sessionId: string
  onlineUsers: string[]
}

export function sessionVersionUrl(sessionId: string) {
  return `/askai-api/api/sessions/${encodeURIComponent(sessionId)}`
}

export async function commitSession(
  sessionId: string,
  payload: {
    seq: number
    trigger?: string
    summary?: string
    changedRefs?: string[]
  },
  authToken?: string | null,
): Promise<SessionVersion> {
  const response = await client.post(
    `${sessionVersionUrl(sessionId)}/commit`,
    {
      seq: payload.seq,
      trigger: payload.trigger ?? 'manual',
      summary: payload.summary ?? '',
      changed_refs: payload.changedRefs ?? [],
      attachments: [],
    },
    { headers: authHeaders(authToken) },
  )
  return response.data
}

export async function listSessionVersions(
  sessionId: string,
  authToken?: string | null,
): Promise<SessionVersion[]> {
  const response = await client.get(
    `${sessionVersionUrl(sessionId)}/versions`,
    { headers: authHeaders(authToken) },
  )
  return response.data ?? []
}

export async function resumeSessionFrom(
  sessionId: string,
  snapshotId?: string,
  authToken?: string | null,
): Promise<{ sessionId: string; resumeAfterSeq: number; resumedFromSnapshot: string | null }> {
  const query = new URLSearchParams()
  if (snapshotId) query.set('snapshot_id', snapshotId)
  const suffix = query.size ? `?${query.toString()}` : ''
  const response = await client.post(
    `${sessionVersionUrl(sessionId)}/resume${suffix}`,
    {},
    { headers: authHeaders(authToken) },
  )
  return response.data
}

export async function shareSession(
  sessionId: string,
  payload: {
    snapshot_id?: string
    receiver?: string
    visibility?: string
    receiver_role?: string
    ttl_seconds?: number
  },
  authToken?: string | null,
): Promise<ShareView> {
  const response = await client.post(
    `${sessionVersionUrl(sessionId)}/share`,
    {
      snapshot_id: payload.snapshot_id ?? '',
      receiver: payload.receiver ?? '',
      visibility: payload.visibility ?? 'user',
      receiver_role: payload.receiver_role ?? 'viewer',
      ttl_seconds: payload.ttl_seconds ?? 300,
    },
    { headers: authHeaders(authToken) },
  )
  return response.data
}

export async function redeemShare(
  sessionId: string,
  token: string,
  authToken?: string | null,
): Promise<ShareView> {
  const response = await client.post(
    `${sessionVersionUrl(sessionId)}/share/redeem`,
    { token },
    { headers: authHeaders(authToken) },
  )
  return response.data
}

export async function getCoPresence(
  sessionId: string,
  authToken?: string | null,
): Promise<PresenceView> {
  const response = await client.get(
    `${sessionVersionUrl(sessionId)}/co-presence`,
    { headers: authHeaders(authToken) },
  )
  return response.data
}

export async function upsertCoPresence(
  sessionId: string,
  payload: { userId: string; messageSeqs: number[] },
  authToken?: string | null,
): Promise<PresenceView & { mergedSeqs: number[] }> {
  const response = await client.post(
    `${sessionVersionUrl(sessionId)}/co-presence`,
    { user_id: payload.userId, message_seqs: payload.messageSeqs },
    { headers: authHeaders(authToken) },
  )
  return response.data
}
