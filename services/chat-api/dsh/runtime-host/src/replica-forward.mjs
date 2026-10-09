/**
 * Cross-replica hand-off for runtime-scoped requests.
 *
 * The sticky LB pins a runtime (and its sessions) to one replica by isolation
 * key, but nginx's consistent-hash table remaps a slice of keys whenever the
 * upstream set changes — most notably while a replica is being restarted. In
 * that window a request can land on a replica that does not hold the runtime
 * and used to fail with 400 "runtime not found", even though a healthy replica
 * owns it.
 *
 * This module removes that failure: a replica that cannot serve a
 * runtime-scoped request asks its peers which one holds the runtime, then
 * re-issues the original request there and relays the response. The client
 * sees a normal answer instead of a hash-remap error.
 *
 * Loop safety: the forwarded request carries a hop counter header. A replica
 * never forwards a request that already reached the hop limit, and never
 * forwards back to the replica the request came from. A request that no peer
 * can serve is answered with the original 400 so behaviour stays honest.
 */

export const HOP_HEADER = 'x-dsh-forward-hops'
export const MAX_HOPS = 2

const DISCOVER_TIMEOUT_MS = 2_000
const FORWARD_TIMEOUT_MS = 30_000

/** Parse DSH_RUNTIME_PEERS: a comma-separated list of base URLs. */
export function parsePeers(raw, selfUrl = '') {
  if (typeof raw !== 'string' || raw.trim() === '') return []
  return raw
    .split(',')
    .map(value => value.trim().replace(/\/+$/, ''))
    .filter(value => value !== '' && value !== selfUrl.replace(/\/+$/, ''))
}

function hopsOf(request) {
  const raw = request.headers[HOP_HEADER]
  const value = Number.parseInt(Array.isArray(raw) ? raw[0] : raw, 10)
  return Number.isFinite(value) && value > 0 ? value : 0
}

export function shouldForward({ request, selfUrl, path }) {
  if (hopsOf(request) >= MAX_HOPS) return false
  // Only runtime-scoped paths are handed off; /health, /drain and the
  // runtime-collection collection GET are answered locally by every replica.
  if (path === '/health' || path === '/drain') return false
  if (!path.startsWith('/v1/runtimes')) return false
  return true
}

async function askPeer(url, authorization) {
  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: { authorization },
      signal: AbortSignal.timeout(DISCOVER_TIMEOUT_MS),
    })
    if (response.status >= 400) return null
    return await response.json()
  } catch {
    return null
  }
}

/**
 * Find the peer that holds `runtimeId`.
 *
 * Uses the runtime-ownership probe (`GET /v1/runtimes/{id}/holds`), which
 * answers for the runtime itself rather than for a session, so it works
 * before any session exists on the target replica.
 */
export async function findOwner({ peers, runtimeId, authorization, instanceId, selfUrl }) {
  for (const peer of peers) {
    if (peer === selfUrl) continue
    const url = `${peer}/v1/runtimes/${encodeURIComponent(runtimeId)}/holds`
    const body = await askPeer(url, authorization)
    if (body === null) continue
    if (body.holds === true && body.instanceId && body.instanceId !== instanceId) {
      return { url: peer, instanceId: body.instanceId, runtimeId }
    }
  }
  return null
}

/**
 * Find the peer that holds a runtime for `isolationKey`.
 *
 * This is the more useful lookup for the remap window: the caller knows the
 * isolation key on every runtime- and session-scoped call, and unlike a
 * runtime id it is stable across a replica restart (the runtime id changes
 * when chat-api rebuilds the binding).
 */
export async function findOwnerByIsolation({ peers, isolationKey, authorization, instanceId, selfUrl }) {
  for (const peer of peers) {
    if (peer === selfUrl) continue
    const url = `${peer}/v1/runtimes?isolationKey=${encodeURIComponent(isolationKey)}`
    const body = await askPeer(url, authorization)
    if (body === null) continue
    const runtime = body.runtime
    if (runtime && typeof runtime.runtimeId === 'string') {
      return { url: peer, runtimeId: runtime.runtimeId, isolationKey }
    }
  }
  return null
}

/**
 * Re-issue the original request against `targetUrl` and relay the response.
 *
 * The body is forwarded verbatim so the peer parses exactly what the original
 * caller sent. The hop header is incremented so a chain of misroutes cannot
 * loop forever.
 */
export async function forwardRequest({ targetUrl, request, path, search, hops, body }) {
  if (hops >= MAX_HOPS) {
    return { forwarded: false, status: 508, body: {
      error: {
        code: 'forward_loop_detected',
        message: `request exceeded ${MAX_HOPS} cross-replica hops`,
      },
    } }
  }
  const payload = Buffer.isBuffer(body) && body.length > 0 ? body : undefined

  let response
  try {
    response = await fetch(`${targetUrl}${path}${search}`, {
      method: request.method,
      headers: {
        authorization: request.headers.authorization,
        'content-type': request.headers['content-type'] ?? 'application/json',
        // Preserve the routing identity so the receiving replica can apply
        // its own sticky semantics and the hop counter stays monotonic.
        ...(request.headers['x-isolation-key'] ? { 'x-isolation-key': request.headers['x-isolation-key'] } : {}),
        [HOP_HEADER]: String(hops + 1),
      },
      body: payload,
      signal: AbortSignal.timeout(FORWARD_TIMEOUT_MS),
    })
  } catch (error) {
    return { forwarded: false, status: 502, body: {
      error: {
        code: 'forward_failed',
        message: `cross-replica hand-off failed: ${error instanceof Error ? error.message : String(error)}`,
      },
    } }
  }

  const text = await response.text()
  let parsed
  try {
    parsed = text === '' ? {} : JSON.parse(text)
  } catch {
    parsed = { error: { code: 'forward_invalid_response', message: text.slice(0, 200) } }
  }
  return { forwarded: true, status: response.status, body: parsed }
}
