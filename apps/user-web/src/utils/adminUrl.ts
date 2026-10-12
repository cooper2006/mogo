/**
 * 022 FR-14（T030 / QF-634）：SSO 令牌不出现在 URL 查询串。
 *
 * 原先 ``buildAdminSsoUrl(ssoToken)`` 会把令牌拼进 ``?sso_token=``，
 * 导致它进入浏览器地址栏、浏览历史、书签与分享链接 —— 任何能读到 URL 的
 * 地方都能拿到有效的管理端凭证。
 *
 * 现在的做法：只返回管理台的基础 URL；令牌通过 ``window.open`` 的第三个
 * 参数（windowFeatures 里的 ``state=`` 约定）随新窗口传入，落在目标窗口的
 * ``window.history.state.ssoToken`` 中，不落地址。
 */

const DEFAULT_ADMIN_WEB_URL = 'http://localhost:3100'

/** 管理台基础 URL；不含任何令牌信息。 */
export function buildAdminSsoUrl(): string {
  const configuredBase = String((import.meta as any).env?.VITE_ADMIN_WEB_URL || DEFAULT_ADMIN_WEB_URL).trim()
  const base = configuredBase || DEFAULT_ADMIN_WEB_URL
  try {
    const url = new URL(base, window.location.origin)
    // 顺带清掉遗留的查询串与 hash，避免旧版参数被带过去。
    url.search = ''
    url.hash = ''
    return url.toString()
  } catch {
    return base
  }
}

/**
 * 把 SSO 令牌编码成 ``window.open`` 的 windowFeatures 字符串片段。
 * 浏览器约定：features 里出现 ``state=<value>`` 时，目标窗口的
 * ``window.history.state`` 会被设为解码后的值。
 */
export function ssoWindowState(ssoToken: string): string {
  return `state=${encodeURIComponent(ssoToken)}`
}
