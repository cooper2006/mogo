import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

/**
 * 029：门户 SSO 接收方——user-web 前端接线契约测试（source-contract）。
 *
 * 覆盖 App.vue onMounted 读票/清票、单租户直建会话、多租户透传选租户挑战、
 * 失败回退登录弹窗，以及 api/auth.ts 的换票调用与 PasswordLoginForm 的种子状态。
 * 与 022/028 一致，用 readFileSync 断言源码契约（App.vue 依赖重、无法直接 import）。
 */

const root = process.cwd()
const auth = readFileSync(resolve(root, 'src/api/auth.ts'), 'utf8')
const app = readFileSync(resolve(root, 'src/App.vue'), 'utf8')
const loginForm = readFileSync(resolve(root, 'src/components/login/PasswordLoginForm.vue'), 'utf8')
const loginModal = readFileSync(resolve(root, 'src/components/LoginModal.vue'), 'utf8')

// T010：票据经 history.state 传入，读取后立即 replaceState 清除（绝不下落 URL）。
assert.match(app, /window\.history\.state[\s\S]{0,80}portalToken/, 'App.vue must read portalToken from history.state')
assert.match(app, /window\.history\.replaceState\(\{\}, ''\)/, 'App.vue must clear history.state after reading the ticket')
assert.match(app, /await handlePortalEntry\(portalToken\)/, 'App.vue onMounted must consume the portal ticket')

// T011 / T014：单租户成功写 localStorage（token / account / profile），供常规启动流程建会话。
assert.match(app, /localStorage\.setItem\(authTokenKey, result\.token\)/, 'single-tenant success must persist the session token')
assert.match(app, /localStorage\.setItem\(authAccountKey, result\.profile\?\.username/, 'success must persist the account username')
assert.match(app, /localStorage\.setItem\(authUserProfileKey, JSON\.stringify\(result\.profile\)\)/, 'success must persist the inline profile')

// T013：多租户捕获选租户挑战并打开登录弹窗。
assert.match(app, /portalChallengeToken\.value = result\.challengeToken/, 'multi-tenant must capture the challenge token')
assert.match(app, /portalTenantCandidates\.value = result\.tenantCandidates/, 'multi-tenant must capture tenant candidates')
assert.match(app, /loginOpen\.value = true/, 'tenant selection must surface the login modal')

// T012 / T015：失败（签名/过期/复药/跨租户/未知用户）不写 token——仅 ok && token 分支写 token，
// 其余分支不触碰 localStorage，交由下方 !authToken 逻辑回退登录弹窗。
const writeTokenIdx = app.indexOf('localStorage.setItem(authTokenKey, result.token)')
const okGuardIdx = app.indexOf('if (result.ok && result.token)')
assert.ok(okGuardIdx !== -1 && okGuardIdx < writeTokenIdx, 'token must only be written inside the ok && result.token branch')

// api/auth.ts：换票调用——票据放请求体（POST body），绝不放 URL；识别多租户挑战并映射 candidates。
assert.match(auth, /client\.post\('\/auth\/portal-exchange', \{ portal_token: portalToken \}\)/, 'exchangePortalTicket must POST the ticket in the body (never the URL)')
// 2026-10-24 QA R12（0f1d7273）将 requiresTenantSelection 判定抽为
// tenantSelectionResult(payload) 函数（data && data.requiresTenantSelection），
// 断言同步为函数级语义，避免依赖内联字面量。
assert.match(auth, /function tenantSelectionResult\(/, 'exchange must extract the multi-tenant challenge into a function')
assert.match(auth, /data\s*&&\s*data\.requiresTenantSelection/, 'tenantSelectionResult must detect the multi-tenant challenge')
// 同 R12 重构口径：tenantSelectionResult 用局部 const data = payload?.data，
// 后续字段访问走 data.*（而非重复 payload?.data?.），断言同步。
assert.match(auth, /challengeToken: data\.challengeToken/, 'exchange must surface the challenge token')
assert.match(auth, /tenantCandidates: data\.candidates \|\| \[\]/, 'exchange must map backend candidates to tenantCandidates')

// PasswordLoginForm：从 props 种子"只选组织"状态，挑战清空时复位。
assert.match(loginForm, /challengeToken\?: string/, 'login form must accept a portal challenge token prop')
assert.match(loginForm, /tenantCandidates\?: TenantCandidate\[\]/, 'login form must accept portal tenant candidates prop')
assert.match(loginForm, /activeChallengeToken\.value = token/, 'login form must seed pendingSelection from the portal challenge')
assert.match(loginForm, /activeChallengeToken\.value = ''/, 'login form must reset pendingSelection when the challenge is cleared')
// 029 SSO：本地 ref 不得与同名 prop 碰撞（vue/no-dupe-keys），否则模板解析到
// ref 而不是 prop，"只选组织"态会读到陈旧值。QA R11 修 F11。
assert.doesNotMatch(loginForm, /const challengeToken = ref/, 'local ref must not shadow the challengeToken prop')

// LoginModal 透传挑战给 PasswordLoginForm。
assert.match(loginModal, /:challenge-token="challengeToken"/, 'LoginModal must forward the challenge token')
assert.match(loginModal, /:tenant-candidates="tenantCandidates"/, 'LoginModal must forward tenant candidates')

// App.vue 透传给 ProductLoginModal，并在登录成功后/关闭时清挑战。
// 注：`:challenge-token="portalChallengeToken"` 的表达式尾部带一个块注释
// `/* pragma: allowlist secret */`（check-secrets 对 `token="…"` 误报的行级豁免），
// 所以这里允许标识符与收尾引号之间夹一个块注释。
assert.match(
  app,
  /challenge-token="portalChallengeToken\s*(\/\*[^*]*\*\/)?\s*"/,
  'App must pass the portal challenge to the login modal',
)
assert.match(app, /:tenant-candidates="portalTenantCandidates"/, 'App must pass portal tenant candidates to the login modal')
assert.match(app, /portalChallengeToken\.value = ''\s*\n\s*portalTenantCandidates\.value = \[\]/, 'App must clear the portal challenge after login success / on close')

test('portal SSO receiver contracts hold', () => {
  assert.ok(true)
})
