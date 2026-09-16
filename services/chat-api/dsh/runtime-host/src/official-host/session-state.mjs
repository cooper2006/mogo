/**
 * The narrow boundary between MOVO and DSH's evolving Session APIs.
 * Keep persistence and in-memory history access out of the runtime facade so
 * later DSH upgrades have one compatibility surface instead of scattered
 * version checks.
 */

export function liveSessionEvents(session) {
  if (typeof session?.snapshotEvents !== 'function') {
    throw new Error('official DSH Session does not expose snapshotEvents()')
  }
  return session.snapshotEvents()
}

export function inheritedEventCount(session) {
  const value = session?.inheritedEventCount
  return Number.isSafeInteger(value) && value >= 0 ? value : 0
}

export function sessionCreationLineage(seed, parentSessionId) {
  if (seed === undefined) return { meta: {}, options: {} }
  if (!Array.isArray(seed) || parentSessionId === undefined) {
    throw new Error('a seeded Session requires an event seed and parent Session identity')
  }
  return {
    meta: {
      parentSession: parentSessionId,
      isSeeded: true,
    },
    options: {
      seed,
      inheritedEventCount: seed.length,
    },
  }
}

export async function readPersistedSession(persistence, sessionId) {
  if (typeof persistence?.open !== 'function') {
    throw new Error('official DSH session persistence does not expose open()')
  }
  const handle = await persistence.open(sessionId, 'read')
  try {
    const result = await handle.read()
    return {
      meta: handle.header,
      events: result.events,
      inheritedEventCount: handle.inheritedEventCount,
    }
  } finally {
    await handle.close()
  }
}
