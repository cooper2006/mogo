const OUTCOMES = new Set(['allowed-once', 'rejected', 'cancelled'])

export class DesktopApprovalBroker {
  #pending = new Map()
  #sessionGrants = new Map()
  #asked = new Map()
  #disposeApproval
  #disposeEvents

  constructor(ctx, { excludedTools = [] } = {}) {
    this.excludedTools = new Set(excludedTools)
    this.#disposeEvents = ctx.on('session/event', (session, event) => {
      if (event.type === 'approval/asked') {
        const asked = this.#asked.get(session.id) ?? []
        asked.push(event)
        this.#asked.set(session.id, asked)
      } else if (event.type === 'approval/decided') {
        const asked = this.#asked.get(session.id) ?? []
        this.#asked.set(session.id, asked.filter(item => item.data.id !== event.data.id))
      }
    }, { global: true })
    this.#disposeApproval = ctx.on('approval/request', async (request, next) => {
      if (this.excludedTools.has(request.toolName)) return next()
      const sessionId = String(request.agent.id)
      if (this.#sessionGrants.get(sessionId)?.has(request.toolName)) return 'allowed-once'
      const asked = [...(this.#asked.get(sessionId) ?? [])].reverse().find(event => (
        event.data.toolName === request.toolName
        && (request.callId === undefined || event.data.callId === request.callId)
      ))
      if (asked === undefined) throw new Error('DSH approval request has no matching approval/asked event')
      const approvalId = String(asked.data.id)
      return await new Promise(resolve => {
        const finish = outcome => {
          request.signal?.removeEventListener('abort', abort)
          this.#pending.delete(approvalId)
          resolve(outcome)
        }
        const abort = () => finish('cancelled')
        this.#pending.set(approvalId, {
          approvalId,
          sessionId,
          toolName: request.toolName,
          callId: request.callId === undefined ? '' : String(request.callId),
          reason: request.reason ?? '',
          createdAt: Date.now(),
          finish,
        })
        request.signal?.addEventListener('abort', abort, { once: true })
      })
    })
  }

  list(sessionId) {
    return [...this.#pending.values()]
      .filter(item => item.sessionId === sessionId)
      .map(({ finish: _finish, ...item }) => ({ ...item }))
  }

  decide(sessionId, approvalId, outcome, grantScope = 'once') {
    if (!OUTCOMES.has(outcome)) throw new Error(`unsupported approval outcome: ${outcome}`)
    if (!['once', 'session'].includes(grantScope)) throw new Error(`unsupported approval grant scope: ${grantScope}`)
    const pending = this.#pending.get(approvalId)
    if (pending === undefined || pending.sessionId !== sessionId) throw new Error('pending approval not found')
    if (outcome === 'allowed-once' && grantScope === 'session') {
      const granted = this.#sessionGrants.get(sessionId) ?? new Set()
      granted.add(pending.toolName)
      this.#sessionGrants.set(sessionId, granted)
    }
    pending.finish(outcome)
    return { decided: true, approvalId, outcome, grantScope }
  }

  clearSession(sessionId) {
    for (const pending of [...this.#pending.values()]) {
      if (pending.sessionId === sessionId) pending.finish('cancelled')
    }
    this.#sessionGrants.delete(sessionId)
    this.#asked.delete(sessionId)
  }

  dispose() {
    for (const pending of [...this.#pending.values()]) pending.finish('cancelled')
    this.#sessionGrants.clear()
    this.#asked.clear()
    this.#disposeApproval?.()
    this.#disposeEvents?.()
  }
}
