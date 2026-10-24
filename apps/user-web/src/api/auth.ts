import axios from 'axios'
import { t } from '../composables/i18n'
import { installAuthExpiryInterceptor } from './authExpiry'

const client = axios.create({
  baseURL: '/askai-api/api',
  timeout: 15000,
})
installAuthExpiryInterceptor(client)

function isOk(payload: any): boolean {
  return payload?.code === 0 || payload?.success === true
}

export type AuthResult = {
  ok: boolean
  token?: string
  profile?: UserProfile
  message?: string
  requiresTenantSelection?: boolean
  challengeToken?: string
  tenantCandidates?: TenantCandidate[]
}

export type TenantCandidate = {
  tenantId: string
  orgName: string
  spaceType?: 'personal' | 'enterprise'
  userId: string
  displayName: string
  username: string
  canAccessAdmin?: boolean
  edition?: 'community' | 'cloud'
  billingEnabled?: boolean
  memberLimit?: number | null
}

export type UserProfile = {
  userId?: number | string
  name?: string
  username?: string
  phone?: string
  email?: string
  avatar?: string
  tenantId?: string
  orgName?: string
  spaceType?: 'personal' | 'enterprise'
  canAccessAdmin?: boolean
  tier?: 'community' | 'free' | 'plus' | 'pro' | 'enterprise'
  edition?: 'community' | 'cloud'
  billingEnabled?: boolean
  memberLimit?: number | null
  availableTenants?: TenantCandidate[]
  agentPolicy?: AgentPolicySnapshot
}

export type AgentCapabilityKey =
  | 'content_generation'
  | 'image_generation'
  | 'code_generation'
  | 'browser_automation'
  | 'internal_knowledge'

export type AgentPolicySnapshot = {
  capabilities: Record<AgentCapabilityKey, boolean>
  toolAccessMode: 'all' | 'selected'
  toolIds: string[]
  skillAccessMode: 'all' | 'selected'
  skillIds: string[]
  roleIds: string[]
  roleNames: string[]
  migrationPending?: boolean
  version?: string
}

/** 未类型化的 API 业务载荷（后端字段按需读取）。 */
type ApiPayload = {
  data?: {
    requiresTenantSelection?: boolean
    challengeToken?: string
    candidates?: TenantCandidate[]
    token?: string
    profile?: UserProfile
  }
  message?: string
}

/** 未类型化的 axios 异常（仅取 message 字段）。 */
type ApiError = { response?: { data?: { message?: string } }; message?: string }


/** 从 axios 异常中提取用户可读消息；保持原有回退顺序。 */
function errorMessageOf(error: ApiError, fallback: string): string {
  return error?.response?.data?.message || error?.message || fallback
}

/** 从业务载荷中提取失败消息；payload.message 缺失时回退到默认文案。 */
function failureMessage(payload: ApiPayload, fallback: string): string {
  return payload?.message || fallback
}

/** 多租户挑战分支：命中 requiresTenantSelection 时返回选租户结果，否则返回 null。 */
function tenantSelectionResult(payload: ApiPayload): AuthResult | null {
  const data = payload?.data
  if (data && data.requiresTenantSelection) {
    return {
      ok: false,
      requiresTenantSelection: true,
      challengeToken: data.challengeToken,
      tenantCandidates: data.candidates || [],
      message: failureMessage(payload, t('api.auth.select_org')),
    }
  }
  return null
}

/** 取 token/profile；缺 token 时返回缺省消息分支。 */
function tokenResult(payload: ApiPayload): AuthResult {
  const data = payload?.data
  const token = data?.token
  const profile = data?.profile
  if (!token) return { ok: false, message: t('api.auth.missing_token') }
  return { ok: true, token, profile }
}

export async function loginWithPassword(
  username: string,
  password: string,
  tenantId = ''
): Promise<AuthResult> {
  try {
    const response = await client.post('/auth/login', { username, password, tenantId })
    const payload = response.data
    const selection = tenantSelectionResult(payload)
    if (selection) return selection
    if (!isOk(payload)) {
      return { ok: false, message: failureMessage(payload, t('api.auth.login_failed')) }
    }
    return tokenResult(payload)
  } catch (error: any) {
    return { ok: false, message: errorMessageOf(error, t('api.auth.login_failed')) }
  }
}

export async function selectTenantAndLogin(challengeToken: string, tenantId: string): Promise<AuthResult> {
  try {
    const response = await client.post('/auth/login/select-tenant', { challengeToken, tenantId })
    const payload = response.data
    if (!isOk(payload)) {
      return { ok: false, message: failureMessage(payload, t('api.auth.login_failed')) }
    }
    return tokenResult(payload)
  } catch (error: any) {
    return { ok: false, message: errorMessageOf(error, t('api.auth.login_failed')) }
  }
}

/**
 * 029：门户 SSO 换票。前端把 `window.history.state.portalToken`（一次性票据，
 * 已由 portal-ticket 端点签发）POST 到 `/auth/portal-exchange` 换取会话。
 * - 单租户：返回 `{token, profile}`，与登录同构，可直接建会话。
 * - 多租户：返回 `requiresTenantSelection` + 挑战，交由选租户流程继续。
 * - 签名错 / 过期 / 复药 / 跨租户 / 未知用户：`ok:false`，前端回退登录弹窗。
 */
export async function exchangePortalTicket(portalToken: string): Promise<AuthResult> {
  try {
    const response = await client.post('/auth/portal-exchange', { portal_token: portalToken })
    const payload = response.data
    const selection = tenantSelectionResult(payload)
    if (selection) return selection
    if (!isOk(payload)) {
      return { ok: false, message: failureMessage(payload, t('api.auth.login_failed')) }
    }
    return tokenResult(payload)
  } catch (error: any) {
    return { ok: false, message: errorMessageOf(error, t('api.auth.login_failed')) }
  }
}

export type RegisterableTenant = {
  tenantId: string
  orgName: string
}

export type RegisterableDepartment = {
  id: string
  name: string
  parentId: string
  code: string
  depth: number
}

export async function listRegisterableTenants(): Promise<{ ok: boolean; tenants?: RegisterableTenant[]; message?: string }> {
  try {
    const response = await client.get('/auth/registerable-tenants')
    const payload = response.data
    if (!isOk(payload)) {
      return { ok: false, message: payload?.message || t('api.auth.login_failed') }
    }
    return { ok: true, tenants: payload?.data?.tenants || [] }
  } catch (error: any) {
    return { ok: false, message: error?.response?.data?.message || error?.message || t('api.auth.login_failed') }
  }
}

export async function listRegisterableDepartments(
  tenantId: string,
): Promise<{ ok: boolean; departments?: RegisterableDepartment[]; message?: string }> {
  try {
    const response = await client.get('/auth/registerable-departments', { params: { tenantId } })
    const payload = response.data
    if (!isOk(payload)) {
      return { ok: false, message: payload?.message || t('api.auth.login_failed') }
    }
    return { ok: true, departments: payload?.data?.departments || [] }
  } catch (error: any) {
    return { ok: false, message: error?.response?.data?.message || error?.message || t('api.auth.login_failed') }
  }
}

export async function register(
  tenantId: string,
  email: string,
  password: string,
  nickname = '',
  departmentId = '',
): Promise<AuthResult> {
  try {
    const response = await client.post('/auth/register', { tenantId, email, password, nickname, departmentId })
    const payload = response.data
    if (!isOk(payload)) {
      return { ok: false, message: failureMessage(payload, t('api.auth.register_failed')) }
    }
    return tokenResult(payload)
  } catch (error: any) {
    return { ok: false, message: errorMessageOf(error, t('api.auth.register_failed')) }
  }
}

export async function switchTenant(token: string, tenantId: string): Promise<AuthResult> {
  try {
    const response = await client.post(
      '/auth/switch-tenant',
      { tenantId },
      {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      }
    )
    const payload = response.data
    if (!isOk(payload)) {
      return { ok: false, message: failureMessage(payload, t('api.auth.switch_org_failed')) }
    }
    return tokenResult(payload)
  } catch (error: any) {
    return { ok: false, message: errorMessageOf(error, t('api.auth.switch_org_failed')) }
  }
}

/** 归一化 /auth/me 返回体：逐字段兜底默认值，字段顺序与既有实现一致。 */
function normalizeProfile(data: Partial<UserProfile>): UserProfile {
  return {
    userId: data.userId,
    name: data.name || '',
    username: data.username || '',
    phone: data.phone || '',
    email: data.email || '',
    avatar: data.avatar || '',
    tenantId: data.tenantId || 'default',
    orgName: data.orgName || '',
    spaceType: data.spaceType === 'personal' ? 'personal' : 'enterprise',
    canAccessAdmin: data.canAccessAdmin === true,
    edition: data.edition === 'community' ? 'community' : 'cloud',
    billingEnabled: data.billingEnabled !== false,
    memberLimit: typeof data.memberLimit === 'number' ? data.memberLimit : null,
    availableTenants: Array.isArray(data.availableTenants) ? data.availableTenants : [],
    agentPolicy: data.agentPolicy,
  }
}

export async function fetchUserProfile(token: string): Promise<{ ok: boolean; data?: UserProfile; message?: string }> {
  try {
    const response = await client.get('/auth/me', {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    })
    // 022 FR-15（T032）：GET /auth/me 只读；租户快照写回走显式 POST。
    // 放在 GET 之后、读取响应之前，保证返回给调用方的 availableTenants 是最新的。
    await refreshTenantSnapshot(token).catch(() => undefined)
    const payload = response.data
    if (!isOk(payload)) {
      return { ok: false, message: failureMessage(payload, t('api.auth.get_user_info_failed')) }
    }
    return { ok: true, data: normalizeProfile(payload.data || {}) }
  } catch (error: any) {
    return { ok: false, message: errorMessageOf(error, t('api.auth.get_user_info_failed')) }
  }
}

/**
 * 022 FR-15（T032）：刷新当前会话的租户快照（available_tenants）。
 * 原先由 GET /auth/me 顺手写入，GET 因此有写副作用；现在拆成显式 POST。
 */
export async function refreshTenantSnapshot(token: string): Promise<unknown> {
  const response = await client.post('/auth/me/refresh-tenants', undefined, {
    headers: { Authorization: `Bearer ${token}` },
  })
  return response.data?.data
}

export async function updateUserProfile(
  token: string,
  name: string,
): Promise<{ ok: boolean; data?: UserProfile; message?: string }> {
  try {
    const response = await client.patch(
      '/auth/profile',
      { name },
      { headers: { Authorization: `Bearer ${token}` } },
    )
    const payload = response.data
    if (!isOk(payload)) {
      return { ok: false, message: payload?.message || t('api.auth.update_profile_failed') }
    }
    return { ok: true, data: payload?.data, message: payload?.message }
  } catch (error: any) {
    return { ok: false, message: error?.response?.data?.message || error?.message || t('api.auth.update_profile_failed') }
  }
}

export async function uploadUserAvatar(
  token: string,
  file: File,
): Promise<{ ok: boolean; data?: UserProfile; message?: string }> {
  try {
    const form = new FormData()
    form.append('file', file)
    const response = await client.post('/auth/profile/avatar', form, {
      headers: { Authorization: `Bearer ${token}` },
    })
    const payload = response.data
    if (!isOk(payload)) {
      return { ok: false, message: payload?.message || t('api.auth.upload_avatar_failed') }
    }
    return { ok: true, data: payload?.data, message: payload?.message }
  } catch (error: any) {
    return { ok: false, message: error?.response?.data?.message || error?.message || t('api.auth.upload_avatar_failed') }
  }
}

export async function logoutWithToken(token: string): Promise<void> {
  try {
    await client.post('/auth/logout', null, {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    })
  } catch {
    // ignore
  }
}

export async function fetchOrgBilling(token: string): Promise<{ ok: boolean; data?: any; message?: string }> {
  try {
    const response = await client.get('/quota/me', {
      headers: { Authorization: `Bearer ${token}` }
    })
    const payload = response.data
    if (!isOk(payload)) {
      return { ok: false, message: payload?.message || t('api.auth.get_quota_failed') }
    }
    return { ok: true, data: payload?.data }
  } catch (error: any) {
    return { ok: false, message: error?.response?.data?.message || error?.message || t('api.auth.get_quota_failed') }
  }
}

export async function getAdminSSOToken(token: string): Promise<{ ok: boolean; ssoToken?: string; message?: string }> {
  try {
    const response = await client.post(
      '/auth/admin-sso',
      null,
      {
        headers: { Authorization: `Bearer ${token}` }
      }
    )
    const payload = response.data
    if (!isOk(payload)) {
      return { ok: false, message: payload?.message || t('api.auth.auth_failed') }
    }
    return { ok: true, ssoToken: payload?.data?.sso_token }
  } catch (error: any) {
    return { ok: false, message: error?.response?.data?.message || error?.message || t('api.auth.auth_failed') }
  }
}
