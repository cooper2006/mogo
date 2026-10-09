import { createServer } from 'node:http'

import { validBearerToken, assertSecureHost } from './host-auth.mjs'
import { HOST_STATES, runtimeHealth } from './host-protocol.mjs'
import { readBody, readJson, routeParts, sendJson } from './http-utils.mjs'
import {
  findOwner,
  findOwnerByIsolation,
  forwardRequest,
  HOP_HEADER,
  parsePeers,
  shouldForward,
} from './replica-forward.mjs'
import { RuntimeManager } from './runtime-manager.mjs'
import { resolveSessionSeed, sealSeed } from './session-seed.mjs'

const DRAIN_WAIT_MS = 30_000

export class RuntimeHttpServer {
  #server
  #manager
  #started = false
  #state = HOST_STATES.ready
  #draining = false
  #peers = []
  #selfUrl = ''

  constructor({ host = '127.0.0.1', port = 0, storageRoot, authToken = '', instanceId = '', peers = '', selfUrl = '' }) {
    if (!Number.isInteger(port) || port < 0 || port > 65535) throw new TypeError('port must be an integer from 0 to 65535')
    if (authToken && authToken.length < 32) throw new TypeError('authToken must contain at least 32 characters')
    assertSecureHost(host, authToken)
    this.host = host
    this.port = port
    this.authToken = authToken
    this.instanceId = instanceId || process.env.DSH_INSTANCE_ID || ''
    // Cross-replica hand-off (§方案 1). DSH_RUNTIME_PEERS is the pool's own
    // membership list, used only to locate the replica that holds a runtime
    // when the sticky LB hands us a request we cannot serve.
    this.#selfUrl = selfUrl || process.env.DSH_RUNTIME_SELF_URL || ''
    this.#peers = parsePeers(peers || process.env.DSH_RUNTIME_PEERS || '', this.#selfUrl)
    this.#manager = new RuntimeManager({ storageRoot })
    this.#server = createServer((request, response) => {
      if (!validBearerToken(request.headers.authorization, this.authToken)) {
        response.setHeader('www-authenticate', 'Bearer realm="askai-dsh-runtime"')
        sendJson(response, 401, { error: { code: 'unauthorized', message: 'valid runtime bearer token required' } })
        return
      }
      this.#dispatch(request, response).catch(error => {
        // A hand-off may have already relayed a response before a later error
        // surfaced; writing again would trip ERR_HTTP_HEADERS_SENT and kill
        // the process. Only answer when nothing has been sent yet.
        if (response.headersSent || response.writableEnded) return
        sendJson(response, 400, {
          error: {
            code: 'kernel_request_failed',
            message: error instanceof Error ? error.message : String(error),
          },
        })
      })
    })
  }

  async start() {
    if (this.#started) return this.address()
    await this.#manager.probe()
    await new Promise((resolvePromise, reject) => {
      const onError = error => reject(error)
      this.#server.once('error', onError)
      this.#server.listen(this.port, this.host, () => {
        this.#server.off('error', onError)
        resolvePromise()
      })
    })
    this.#started = true
    return this.address()
  }

  address() {
    const address = this.#server.address()
    if (address === null || typeof address === 'string') throw new Error('DSH Runtime Host is not listening')
    return { host: this.host, port: address.port }
  }

  async stop() {
    if (!this.#started) return
    this.#started = false
    // R1 two-phase shutdown: first drain (stop accepting new work, let
    // in-flight turns finish up to a bound) so a rolling upgrade no longer
    // force-cancels active sessions; then close connections and dispose.
    await this.#drain()
    const closed = new Promise(resolvePromise => this.#server.close(() => resolvePromise()))
    await this.#manager.disposeAll()
    this.#server.closeAllConnections()
    await closed
  }

  // Phase 1 of shutdown: reject new work, wait for in-flight turns to settle.
  async #drain() {
    if (this.#draining) return
    this.#draining = true
    this.#state = HOST_STATES.draining
    await this.#manager.whenSessionsIdle({ intervalMs: 200, timeoutMs: DRAIN_WAIT_MS })
    // Any session still busy after the timeout is disposed in phase 2; its
    // state is persisted so a later resume can recover it.
  }

  // Explicit drain trigger (R1): operations or the container's preStop hook
  // can call POST /drain to start draining without killing the process,
  // e.g. to let an active turn finish before a planned restart.
  async #drainNow() {
    await this.#drain()
  }

  get state() {
    return this.#state
  }

  /**
   * Relay a runtime-scoped request this replica cannot serve to the replica
   * that holds the runtime. Returns the response, or null when no peer holds
   * it (caller then falls through to the local "runtime not found" error, so
   * a genuinely unknown runtime still fails honestly).
   */
  async #handOff({ request, response, runtimeId, parts, query, body }) {
    const path = `/${parts.join('/')}`
    if (!shouldForward({ request, selfUrl: this.#selfUrl, path })) return null
    if (this.#peers.length === 0) return null

    const authorization = request.headers.authorization ?? ''
    let targetParts = parts
    // Prefer the isolation key: it is carried on every runtime/session call
    // and stays valid after a replica restart, whereas the runtime id changes
    // when chat-api rebuilds the binding.
    const isolationKey = request.headers['x-isolation-key']
    let target = null
    if (typeof isolationKey === 'string' && isolationKey !== '') {
      target = await findOwnerByIsolation({
        peers: this.#peers,
        isolationKey,
        authorization,
        instanceId: this.instanceId,
        selfUrl: this.#selfUrl,
      })
      if (target && target.runtimeId !== runtimeId) {
        // The owning replica minted its own runtime id; rewrite the path so
        // the peer serves its own runtime rather than the stale id.
        targetParts = parts.slice()
        targetParts[2] = target.runtimeId
      }
    }
    if (target === null) {
      target = await findOwner({
        peers: this.#peers,
        runtimeId,
        authorization,
        instanceId: this.instanceId,
        selfUrl: this.#selfUrl,
      })
    }
    if (target === null) return null

    const search = query.toString() === '' ? '' : `?${query.toString()}`
    const hops = Number.parseInt(request.headers[HOP_HEADER] ?? '0', 10) || 0
    // A peer that is draining refuses new sessions (R1 drain guard). That is
    // correct for the peer, but relaying its 503 to the caller would fail a
    // request another replica could still serve — so try the next owner.
    const attempted = new Set()
    while (target !== null) {
      attempted.add(target.url)
      let targetTargetParts = targetParts
      if (target.runtimeId && target.runtimeId !== runtimeId) {
        targetTargetParts = parts.slice()
        targetTargetParts[2] = target.runtimeId
      }
      const result = await forwardRequest({
        targetUrl: target.url,
        request,
        path: `/${targetTargetParts.join('/')}`,
        search,
        hops,
        body,
      })
      const draining = result.status === 503
        && result.body?.error?.code === 'service_draining'
      if (!draining || result.forwarded === false) {
        if (result.forwarded) {
          response.setHeader('x-dsh-forwarded-to', target.instanceId ?? target.url)
        }
        return sendJson(response, result.status, result.body)
      }
      target = await this.#nextTarget({ peers: this.#peers, attempted, isolationKey, runtimeId, authorization })
    }
    return null
  }

  /** Find another peer that holds the runtime, skipping already-tried ones. */
  async #nextTarget({ peers, attempted, isolationKey, runtimeId, authorization }) {
    const remaining = peers.filter(peer => !attempted.has(peer))
    if (remaining.length === 0) return null
    if (typeof isolationKey === 'string' && isolationKey !== '') {
      const byKey = await findOwnerByIsolation({
        peers: remaining,
        isolationKey,
        authorization,
        instanceId: this.instanceId,
        selfUrl: this.#selfUrl,
      })
      if (byKey) return byKey
    }
    return findOwner({
      peers: remaining,
      runtimeId,
      authorization,
      instanceId: this.instanceId,
      selfUrl: this.#selfUrl,
    })
  }

  async #dispatch(request, response) {
    const { parts, query } = routeParts(request)
    if (request.method === 'GET' && parts.join('/') === 'health') {
      // /health stays 200 while draining so the sticky LB does not evict the
      // replica mid-turn; the state field is the signal for operators and for
      // chat-api's aggregation to treat the replica as unavailable for new
      // work.
      return sendJson(response, 200, runtimeHealth(this.#manager.inventory(), this.instanceId, this.#state))
    }
    if (request.method === 'POST' && parts.join('/') === 'drain') {
      await this.#drainNow()
      return sendJson(response, 200, {
        state: this.#state,
        activeSessions: this.#manager.activeSessionCount(),
      })
    }
    // Drain guard: once the host is draining it must not take on new work.
    // Existing sessions keep their in-flight turns (send/resume/cancel/
    // events) so a rolling upgrade never force-cancels them; only new
    // runtimes, new sessions and new workspaces are refused.
    if (this.#state === HOST_STATES.draining && request.method === 'POST') {
      const path = parts.join('/')
      if (path === 'v1/runtimes'
        || /^v1\/runtimes\/[^/]+\/sessions$/.test(path)
        || /^v1\/runtimes\/[^/]+\/workspaces$/.test(path)) {
        return sendJson(response, 503, {
          error: { code: 'service_draining', message: `host is draining; new work is not accepted on ${path}` },
          instanceId: this.instanceId,
        })
      }
    }
    if (request.method === 'POST' && parts.join('/') === 'v1/runtimes') {
      const runtime = await this.#manager.create(await readJson(request))
      const health = runtimeHealth([], this.instanceId, this.#state)
      return sendJson(response, 201, {
        runtimeId: runtime.runtimeId,
        kernel: health.kernel,
        kernelVersion: health.version,
        protocolVersion: health.protocolVersion,
        instanceId: health.instanceId,
        profileVersion: runtime.profileVersion,
        isolationKey: runtime.isolationKey,
      })
    }
    if (request.method === 'GET' && parts.join('/') === 'v1/runtimes') {
      const isolationKey = query.get('isolationKey')
      if (isolationKey === null) return sendJson(response, 200, { runtimes: this.#manager.inventory() })
      const runtime = this.#manager.findByIsolation(isolationKey)
      return sendJson(response, 200, { runtime: runtime === undefined ? null : this.#manager.describe(runtime) })
    }
    if (parts[0] !== 'v1' || parts[1] !== 'runtimes' || parts[2] === undefined) {
      return sendJson(response, 404, { error: { code: 'not_found', message: 'route not found' } })
    }
    const runtimeId = parts[2]
    // Runtime-ownership probe used by cross-replica hand-off: answers for the
    // runtime itself (not a session), so a peer can be located before any
    // session exists there. Always 200 so probing never stops early.
    if (request.method === 'GET' && parts[3] === 'holds' && parts.length === 4) {
      const local = this.#manager.findByRuntimeId(runtimeId)
      return sendJson(response, 200, {
        holds: local !== undefined,
        instanceId: this.instanceId,
        runtimeId,
      })
    }
    if (request.method === 'DELETE' && parts.length === 3) {
      await this.#manager.dispose(runtimeId)
      return sendJson(response, 200, { disposed: true })
    }
    // Cross-replica session probes (§12.4) run *before* the runtime is
    // resolved: a replica that does not hold the runtime must answer
    // "owned: false" (B) or "seed: null" (A) instead of 400 "runtime not
    // found", otherwise the pool-wide probe stops at the first replica it
    // asks.
    if (parts[3] === 'sessions' && parts[4] !== undefined) {
      const sessionId = decodeURIComponent(parts[4])
      if (request.method === 'GET' && parts[5] === 'owner' && parts.length === 6) {
        const local = this.#manager.findByRuntimeId(runtimeId)
        return sendJson(response, 200, {
          owned: local !== undefined && local.ownsSession(sessionId),
          instanceId: this.instanceId,
          runtimeId,
          sessionId,
        })
      }
      if (request.method === 'GET' && parts[5] === 'export-seed' && parts.length === 6) {
        const local = this.#manager.findByRuntimeId(runtimeId)
        if (local === undefined) {
          return sendJson(response, 404, { seed: null, instanceId: this.instanceId })
        }
        try {
          const seed = await local.exportCompletedSeed(sessionId)
          return sendJson(response, 200, sealSeed(
            this.authToken,
            this.instanceId,
            sessionId,
            seed,
          ))
        } catch (error) {
          if (/session is not live/.test(String(error))) {
            return sendJson(response, 404, { seed: null, instanceId: this.instanceId })
          }
          throw error
        }
      }
    }
    let runtime = this.#manager.findByRuntimeId(runtimeId)
    if (runtime === undefined) {
      // The sticky LB handed this request to a replica that does not hold the
      // runtime. That happens when consistency-hash membership changes (most
      // visibly while a replica restarts). Instead of failing the caller with
      // 400 "runtime not found", locate the owning replica and relay the
      // request — the client then sees a normal answer across the remap.
      //
      // The body is buffered first: the hand-off may need it, and if no owner
      // exists the local path still has to parse it. Reading the stream twice
      // is impossible, so both paths share one buffer.
      const buffered = await readBody(request)
      const handoff = await this.#handOff({ request, response, runtimeId, parts, query, body: buffered })
      if (handoff) return handoff
      request._bufferedBody = buffered
      runtime = this.#manager.get(runtimeId)
    }
    if (request.method === 'GET' && parts.length === 3) return sendJson(response, 200, this.#manager.describe(runtime))
    if (parts[3] === 'workspaces') {
      if (request.method === 'GET' && parts.length === 4) {
        return sendJson(response, 200, { workspaces: await runtime.listWorkspaces() })
      }
      if (request.method === 'POST' && parts.length === 4) {
        return sendJson(response, 201, await runtime.createWorkspace(await readJson(request)))
      }
      if (parts[4] !== undefined && request.method === 'PATCH' && parts.length === 5) {
        return sendJson(response, 200, await runtime.renameWorkspace(decodeURIComponent(parts[4]), await readJson(request)))
      }
      if (parts[4] !== undefined && request.method === 'DELETE' && parts.length === 5) {
        return sendJson(response, 200, await runtime.deleteWorkspace(decodeURIComponent(parts[4])))
      }
    }
    if (request.method === 'PUT' && parts[3] === 'model-credential' && parts.length === 4) {
      return sendJson(response, 200, runtime.refreshModelCredential(await readJson(request)))
    }
    if (request.method === 'PUT' && parts[3] === 'tool-credential' && parts.length === 4) {
      return sendJson(response, 200, runtime.refreshToolCredential(await readJson(request)))
    }
    if (request.method === 'POST' && parts[3] === 'sessions' && parts.length === 4) {
      let body = await readJson(request)
      if (Object.hasOwn(body, 'cwd')) throw new Error('raw cwd is forbidden over the Runtime Host API; use workspaceId')
      body = await resolveSessionSeed(this.#manager, body, { authToken: this.authToken })
      if (body.presetId === 'code') {
        if (body.workspaceId === undefined) throw new Error('Code Session requires a DSH workspaceId')
        if (body.permissionPreset !== undefined && body.permissionPreset !== 'workspace-write') {
          throw new Error('desktop Code Session permissionPreset exceeds MOVO policy')
        }
        body.permissionPreset = 'workspace-write'
      }
      return sendJson(response, 201, await runtime.createSession(body))
    }
    if (parts[3] === 'sessions' && parts[4] !== undefined) {
      const sessionId = decodeURIComponent(parts[4])
      if (request.method === 'GET' && parts.length === 5) return sendJson(response, 200, await runtime.describeLiveSession(sessionId))
      if (request.method === 'POST' && parts[5] === 'resume') return sendJson(response, 200, await runtime.resumeSession(sessionId))
      if (request.method === 'POST' && parts[5] === 'send') {
        return sendJson(response, 202, runtime.send({ sessionId, ...await readJson(request) }))
      }
      if (request.method === 'POST' && parts[5] === 'cancel') {
        const body = await readJson(request)
        return sendJson(response, 202, await runtime.cancel(sessionId, body.cause ?? 'cancelled'))
      }
      if (request.method === 'GET' && parts[5] === 'events') {
        return sendJson(response, 200, { events: runtime.events(sessionId, Number(query.get('after') ?? -1)) })
      }
      if (request.method === 'GET' && parts[5] === 'approvals' && parts.length === 6) {
        return sendJson(response, 200, { approvals: runtime.pendingApprovals(sessionId) })
      }
      if (request.method === 'POST' && parts[5] === 'approvals' && parts[6] !== undefined && parts[7] === 'decision') {
        const body = await readJson(request)
        return sendJson(response, 200, runtime.decideApproval(
          sessionId, decodeURIComponent(parts[6]), body.outcome, body.grantScope ?? 'once',
        ))
      }
      if (request.method === 'GET' && parts[5] === 'event-stream') {
        const writeEvent = event => response.write(`${JSON.stringify(event)}\n`)
        const subscription = runtime.subscribeEvents(sessionId, Number(query.get('after') ?? -1), writeEvent)
        response.writeHead(200, {
          'content-type': 'application/x-ndjson; charset=utf-8',
          'cache-control': 'no-cache, no-transform',
          connection: 'keep-alive',
          'x-accel-buffering': 'no',
        })
        for (const event of subscription.replay) writeEvent(event)
        const heartbeat = setInterval(() => response.write('\n'), 2_000)
        const cleanup = () => {
          clearInterval(heartbeat)
          subscription.unsubscribe()
        }
        request.once('close', cleanup)
        response.once('close', cleanup)
        return
      }
      if (request.method === 'DELETE' && parts.length === 5) {
        return sendJson(response, 200, await runtime.disposeSession(sessionId))
      }
    }
    if (parts[3] === 'plugins') {
      const body = request.method === 'GET' ? {} : await readJson(request)
      if (request.method === 'GET' && parts.length === 4) {
        return sendJson(response, 200, { plugins: runtime.pluginInventory() })
      }
      if (request.method === 'POST' && parts[4] === 'load') return sendJson(response, 200, await runtime.loadPlugin(body.specifier))
      if (request.method === 'POST' && parts[4] === 'probe') return sendJson(response, 200, await runtime.probePlugin(body.specifier))
      if (request.method === 'POST' && parts[4] === 'unload') return sendJson(response, 200, await runtime.unloadPlugin(body.specifier))
    }
    return sendJson(response, 404, { error: { code: 'not_found', message: 'route not found' } })
  }
}
