import type { AxiosError, AxiosInstance } from 'axios'

export const AUTH_EXPIRED_EVENT = 'askai:auth-expired'

function bearerTokenFromHeaders(headers: any): string {
  if (!headers) return ''
  const value = typeof headers.get === 'function'
    ? headers.get('Authorization') || headers.get('authorization')
    : headers.Authorization || headers.authorization
  return String(value || '').trim()
}

/**
 * 从 401 响应体里提取可读的失败原因，便于排查「到底是哪种会话失效」。
 * 兼容两种结构：
 * - FastAPI 的 ``detail`` 为字符串（如 ``"invalid_token"``）；
 * - 会话超时分支的 ``detail`` 为对象（``{code:"SESSION_TIMEOUT", reason:"idle_timeout", ...}``）。
 */
function describeAuthFailure(body: any): string {
  const detail = body?.detail
  if (!detail) {
    return body?.message ? String(body.message) : '(no detail in response body)'
  }
  if (typeof detail === 'string') return detail
  if (typeof detail === 'object') {
    const reason = detail.reason || detail.code || ''
    const message = detail.message ? ` — ${detail.message}` : ''
    return `${reason}${message}`.trim() || JSON.stringify(detail)
  }
  return String(detail)
}

export function notifyAuthExpired(reason?: string): void {
  if (typeof window === 'undefined') return
  if (reason) {
    console.warn(`[auth] session expired: ${reason}`)
  }
  window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT))
}

export function notifyAuthExpiredFromResponse(response: Response, authenticated: boolean): void {
  if (authenticated && response.status === 401) {
    void response
      .clone()
      .json()
      .then((body) => notifyAuthExpired(describeAuthFailure(body)))
      .catch(() => notifyAuthExpired('401 Unauthorized'))
  }
}

export function installAuthExpiryInterceptor(client: AxiosInstance): void {
  client.interceptors.response.use(
    (response) => response,
    (error: AxiosError) => {
      const hasBearerToken = /^Bearer\s+\S+/i.test(bearerTokenFromHeaders(error?.config?.headers))
      if (hasBearerToken && error?.response?.status === 401) {
        notifyAuthExpired(describeAuthFailure(error?.response?.data))
      }
      return Promise.reject(error)
    },
  )
}
