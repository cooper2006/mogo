/**
 * 门户前端示例：拿到一次性票据后，经 history.state 跳转 user-web（不落 URL）。
 *
 * 对应 spec 029 / docs/MOGO-Web应用集成方案.md §1.3.2「路径 1」。
 *
 * 流程：
 *   1. 用户在本门户已登录，前端向门户后端要一张一次性票据（门户后端已用服务身份
 *      调 chat-api portal-ticket 拿到 portal_token）。
 *   2. 用 history.pushState/replaceState 把票据放进 history.state.portalToken，
 *      再跳转到 user-web。票据**绝不**进 URL query / hash / localStorage。
 *   3. user-web onMounted 读到 history.state.portalToken 后立即 replaceState 清除，
 *      再 POST /api/auth/portal-exchange 换票建会话。
 *
 * ⚠️ 不要用 ?portal_token=... 传参——那会把票据落进 URL（浏览器历史、Referer、日志）。
 */

const USER_WEB_BASE = 'https://mogo.example.com' // user-web 入口地址

/**
 * 从门户后端取一次性票据。
 * 门户后端实现见 portal_backend.py（签 022 服务令牌 → 调 portal-ticket）。
 */
async function fetchPortalTicket(userId) {
  const resp = await fetch('/api/portal/sso-ticket', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId }),
    credentials: 'same-origin',
  })
  if (!resp.ok) throw new Error('failed to issue portal ticket')
  const data = await resp.json()
  return data.portal_token // 门户后端把 chat-api 返回的 token 原样透传
}

/**
 * 带票进入 MOGO 用户工作台。票据经 history.state 传递，不落 URL。
 */
export async function enterMogoWorkspace(userId) {
  const portalToken = await fetchPortalTicket(userId)
  if (!portalToken) return

  // 先 replaceState 写入票据，再整体导航到 user-web；同源时票据留在 history.state。
  // 跨域时浏览器不允许跨域写入对方 origin 的 history.state——此时改用"跳转到一个
  // 同源的引导页，由引导页再 window.location 到 user-web 并 pushState 票据"，
  // 或由 user-web 支持从 POST body 读票（见集成方案 §1.3.2 决策 4：跨域传票）。
  window.history.replaceState({ portalToken }, '')
  window.location.href = USER_WEB_BASE
}

/**
 * 同源内嵌（例如门户 iframe 指向 user-web 同源入口）时的最小用法：
 * 直接把票据塞进当前 history.state 并 reload，user-web 会消费它。
 */
export function enterMogoWorkspaceSameOrigin(portalToken) {
  window.history.replaceState({ portalToken }, '')
  window.location.reload()
}
